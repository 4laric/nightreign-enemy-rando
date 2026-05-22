#!/usr/bin/env python3
"""navmesh_polygon_metrics.py — Polygon-derived per-slot metrics from
hkaiNavMesh data in NR .nvmhktbnd files.

Rebuilds the tooling from chat b2e767c9 ("Baba booey", 2026-05-13), which
went from "polygon parsing deferred" to "polygon parsing working" via the
soulstruct-havok hk2018 _hkcd monkeypatch.

USAGE
    from navmesh_polygon_metrics import load_navmesh, slot_metrics
    nm = load_navmesh('path/to/m34_30_00_00.nvmhktbnd')
    m = slot_metrics(nm, slot_xyz=(-20.3, 24.8, -41.1))
    # m has keys: face_idx, face_dist, slope_deg, border_edge_dist,
    #            area_3m, area_5m, area_10m, reach_count_5m

WHY POLYGONS, NOT AABBs
    AABBs from hkcdStaticAabbTree give coarse on-mesh / off-mesh classification
    + extent-based roughness proxies (n10, s_y). They can't distinguish "flat
    cathedral nave" from "rocky cathedral exterior" within a single tile.

    Polygons give:
      - actual face slope (normal · up)
      - actual border-edge distance (real wall, not AABB corner)
      - connected walkable area within a radius (elbow room around the slot)

    Empirical anchor from the May 13 corpus run (m30_30 Fort tile):
        FROZEN pi=30 Foot Soldier rampart  : area_5m = 14.3 m²  (bottom 18%)
        ROBUST rat pi=21                   : area_5m = 26.7 m²
        ROBUST rat pi=22                   : area_5m = 23.4 m²
        ROBUST rat pi=23                   : area_5m = 19.5 m²

REQUIRES
    soulstruct + soulstruct-havok from PyPI, plus the _hkcd import
    monkeypatch (applied automatically on module import).
"""
import os
import sys
import importlib
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# soulstruct-havok bootstrap. Grimrukh's hk2018/__init__.py imports
# _hcl/_hka/_hkai/_hkb/_hknp/_hkp/_hkx but forgets _hkcd — so hkcd types
# (which Elden Ring / Nightreign navmeshes reference for the BVH) aren't
# registered in the type module, and parsing fails with TypeNotDefinedError.
# Force-import them at module load time.
# ---------------------------------------------------------------------------
def _bootstrap_soulstruct_havok():
    import soulstruct.havok.types.hk2018._hkcd as _hkcd_pkg
    import soulstruct.havok.types.hk2018 as _hk2018_mod
    hkcd_dir = os.path.dirname(_hkcd_pkg.__file__)
    for fn in os.listdir(hkcd_dir):
        if fn.endswith('.py') and not fn.startswith('_'):
            mod = importlib.import_module(
                f'soulstruct.havok.types.hk2018._hkcd.{fn[:-3]}')
            cls_name = fn[:-3]
            if hasattr(mod, cls_name):
                setattr(_hk2018_mod, cls_name, getattr(mod, cls_name))


_bootstrap_soulstruct_havok()

from soulstruct.havok.core import HKX  # noqa: E402

# Reuse the BND4 reader from dev/bnd4.py (the rando's existing parser).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from bnd4 import read_bnd4  # noqa: E402


# Sentinel: hkaiNavMeshEdge.oppositeFace = 0xFFFFFFFF means "no opposite
# face" — the edge is a border (wall, cliff, mesh boundary).
EDGE_BORDER_SENTINEL = 0xFFFFFFFF


# =============================================================================
# Parsed-navmesh data class. We pre-compute face centroids, areas, and
# normals as numpy arrays so per-slot queries are fast.
# =============================================================================
class ParsedNavmesh:
    __slots__ = ('vertices', 'face_polygons', 'face_edges_start', 'face_num_edges',
                 'edge_a', 'edge_b', 'edge_opp_face',
                 'face_centroid', 'face_area', 'face_normal', 'face_slope_deg',
                 'face_border_edge_dist', 'n_faces', 'n_vertices', 'aabb_min',
                 'aabb_max', 'source')

    def __init__(self):
        self.vertices = None              # (N, 3) float32 — Vec4 xyz only
        self.face_polygons = None         # list of np.ndarray vertex-index lists
        self.face_edges_start = None      # (F,) int — startEdgeIndex per face
        self.face_num_edges = None        # (F,) int
        self.edge_a = None                # (E,) int — vertex index
        self.edge_b = None                # (E,) int — vertex index
        self.edge_opp_face = None         # (E,) uint32 — opposite face or sentinel
        self.face_centroid = None         # (F, 3) float32
        self.face_area = None             # (F,) float32 — polygon area in xz
        self.face_normal = None           # (F, 3) float32 — unit normal (y-up)
        self.face_slope_deg = None        # (F,) float32
        self.face_border_edge_dist = None # (F,) float32 — min dist from centroid
                                          #                to a border edge (any face edge
                                          #                whose oppositeFace == sentinel)
        self.n_faces = 0
        self.n_vertices = 0
        self.aabb_min = None              # (3,) float
        self.aabb_max = None              # (3,) float
        self.source = ''                  # filename for debugging


def _read_largest_nav_hkx(bnd_path):
    """Pull the largest n_*.hkx payload from a .nvmhktbnd. NR ships
    multiple n_*.hkx in each binder; the largest is the master tile."""
    candidates = [(n, p) for n, p in read_bnd4(bnd_path)
                  if n.startswith('n') and n.endswith('.hkx')]
    if not candidates:
        return None
    return max(candidates, key=lambda np_: len(np_[1]))


def _parse_one_hkx(payload: bytes) -> ParsedNavmesh:
    """Parse a single n_*.hkx payload into a ParsedNavmesh."""
    hkx = HKX.from_bytes(payload)
    root = hkx.root
    # Find the hkaiNavMesh variant (first one — second is the QueryMediator)
    nm = None
    for v in root.namedVariants:
        if v.className == 'hkaiNavMesh':
            nm = v.variant
            break
    if nm is None:
        raise ValueError('No hkaiNavMesh variant in HKX root')

    parsed = ParsedNavmesh()

    # Vertices: hkaiNavMesh stores them as Vec4 (xyz + padding ~0.004).
    # Drop the 4th component. Handle both 2D ndarray (typical) and
    # 1D fallback (rare malformed maps like m48_20).
    verts_raw = np.asarray(nm.vertices, dtype=np.float32)
    if verts_raw.ndim == 1:
        # 1D vertices — coerce to (N, 4) assuming Vec4 packing
        if verts_raw.size % 4 != 0:
            raise ValueError(
                f'Vertices array is 1D but size {verts_raw.size} not '
                f'divisible by 4; cannot interpret as Vec4 list')
        verts_raw = verts_raw.reshape(-1, 4)
    parsed.vertices = verts_raw[:, :3].copy()
    parsed.n_vertices = parsed.vertices.shape[0]

    # AABB
    parsed.aabb_min = np.array([nm.aabb.min[0], nm.aabb.min[1], nm.aabb.min[2]],
                               dtype=np.float32)
    parsed.aabb_max = np.array([nm.aabb.max[0], nm.aabb.max[1], nm.aabb.max[2]],
                               dtype=np.float32)

    # Edges — extract all fields via fromiter (faster than per-edge Python loop)
    n_edges = len(nm.edges)
    parsed.edge_a = np.fromiter((e.a for e in nm.edges), dtype=np.int32, count=n_edges)
    parsed.edge_b = np.fromiter((e.b for e in nm.edges), dtype=np.int32, count=n_edges)
    parsed.edge_opp_face = np.fromiter(
        ((e.oppositeFace & 0xFFFFFFFF) for e in nm.edges),
        dtype=np.uint32, count=n_edges)

    # Faces — bulk extract startEdgeIndex and numEdges first
    n_faces = len(nm.faces)
    parsed.n_faces = n_faces
    parsed.face_edges_start = np.fromiter(
        (f.startEdgeIndex for f in nm.faces), dtype=np.int32, count=n_faces)
    parsed.face_num_edges = np.fromiter(
        (f.numEdges for f in nm.faces), dtype=np.int32, count=n_faces)
    parsed.face_polygons = [None] * n_faces
    parsed.face_centroid = np.zeros((n_faces, 3), dtype=np.float32)
    parsed.face_area = np.zeros(n_faces, dtype=np.float32)
    parsed.face_normal = np.zeros((n_faces, 3), dtype=np.float32)
    parsed.face_slope_deg = np.zeros(n_faces, dtype=np.float32)
    parsed.face_border_edge_dist = np.full(n_faces, np.inf, dtype=np.float32)

    UP = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    edge_a = parsed.edge_a
    vertices = parsed.vertices
    edge_opp_face = parsed.edge_opp_face
    edge_b = parsed.edge_b

    for fi in range(n_faces):
        s = int(parsed.face_edges_start[fi])
        n = int(parsed.face_num_edges[fi])
        # Polygon vertex indices: walk edges along the face, take edge.a
        poly_vi = edge_a[s:s + n]
        parsed.face_polygons[fi] = poly_vi
        poly_v = vertices[poly_vi]   # (n, 3)

        # Centroid
        c = poly_v.mean(axis=0)
        parsed.face_centroid[fi] = c

        # Area + normal via fan triangulation, vectorized across the
        # n-2 triangles of this polygon.
        if n >= 3:
            v0 = poly_v[0]
            # Triangle edges from v0: e1[i] = poly_v[i+1] - v0,
            #                          e2[i] = poly_v[i+2] - v0
            e1 = poly_v[1:n-1] - v0   # shape (n-2, 3)
            e2 = poly_v[2:n] - v0     # shape (n-2, 3)
            crosses = np.cross(e1, e2)  # (n-2, 3)
            tri_areas = 0.5 * np.linalg.norm(crosses, axis=1)
            total_area = float(tri_areas.sum())
            total_normal = crosses.sum(axis=0)
            parsed.face_area[fi] = total_area
            nrm_len = float(np.linalg.norm(total_normal))
            if nrm_len > 1e-9:
                nrm = total_normal / nrm_len
                if nrm[1] < 0:
                    nrm = -nrm
                parsed.face_normal[fi] = nrm
                cos_up = float(np.clip(np.dot(nrm, UP), -1.0, 1.0))
                parsed.face_slope_deg[fi] = float(np.degrees(np.arccos(cos_up)))

        # Border-edge distance: scan this face's edges for sentinels.
        # Cheap; fast path for "no border" stays inf.
        opp_slice = edge_opp_face[s:s + n]
        border_mask = opp_slice == EDGE_BORDER_SENTINEL
        if border_mask.any():
            # compute midpoints for the border edges of this face
            border_local = np.nonzero(border_mask)[0]
            min_d = np.inf
            for li in border_local:
                ei = s + int(li)
                va = vertices[edge_a[ei]]
                vb = vertices[edge_b[ei]]
                mid = 0.5 * (va + vb)
                d = float(np.linalg.norm(mid - c))
                if d < min_d:
                    min_d = d
            parsed.face_border_edge_dist[fi] = min_d

    return parsed


def load_navmesh(bnd_path: str) -> Optional[ParsedNavmesh]:
    """Load a .nvmhktbnd, parse its master n_*.hkx, return ParsedNavmesh.
    Returns None on missing file or unparseable BND.
    """
    if not os.path.isfile(bnd_path):
        return None
    nav = _read_largest_nav_hkx(bnd_path)
    if nav is None:
        return None
    name, payload = nav
    parsed = _parse_one_hkx(payload)
    parsed.source = os.path.basename(bnd_path)
    return parsed


# =============================================================================
# Per-slot metric query
# =============================================================================
def _nearest_face(nm: ParsedNavmesh, pos: np.ndarray) -> Tuple[int, float]:
    """Return (face_idx, distance) of the nearest face centroid to pos.
    Distance is full-3D Euclidean. If the nav has zero faces, returns (-1, inf).
    """
    if nm.n_faces == 0:
        return -1, float('inf')
    diff = nm.face_centroid - pos  # (F, 3)
    d2 = np.einsum('ij,ij->i', diff, diff)
    fi = int(np.argmin(d2))
    return fi, float(np.sqrt(d2[fi]))


def slot_metrics(nm: ParsedNavmesh, slot_xyz: Tuple[float, float, float],
                 radii: Tuple[float, ...] = (3.0, 5.0, 10.0)
                 ) -> Dict[str, float]:
    """Compute per-slot polygon metrics. Returns dict with:
        face_idx           — nearest face index (-1 if no faces)
        face_dist          — 3D distance from slot to that face's centroid
        slope_deg          — slope of that face
        border_edge_dist   — distance from that face's centroid to its
                             nearest border edge midpoint (inf if no border)
        area_3m, area_5m, area_10m — sum of face areas in connected-via-
                             opposite-edge walkable region whose centroids
                             are within R meters of slot_xyz (BFS)
        reach_count_5m     — number of faces walked in the 5m BFS
    """
    pos = np.asarray(slot_xyz, dtype=np.float32)
    fi, fd = _nearest_face(nm, pos)

    out = {
        'face_idx': fi, 'face_dist': fd,
        'slope_deg': float('nan'), 'border_edge_dist': float('nan'),
    }
    for r in radii:
        out[f'area_{int(r)}m'] = 0.0
    out['reach_count_5m'] = 0

    if fi < 0:
        return out

    out['slope_deg'] = float(nm.face_slope_deg[fi])
    bed = float(nm.face_border_edge_dist[fi])
    out['border_edge_dist'] = bed if np.isfinite(bed) else float('nan')

    # BFS over faces via opposite_face edges. Include a face only if its
    # centroid is within max(radii) meters of slot pos. Accumulate per-
    # radius area at each step.
    R_max = max(radii)
    R_max_sq = R_max * R_max

    diff0 = nm.face_centroid[fi] - pos
    if float(np.dot(diff0, diff0)) > R_max_sq:
        # Even the starting face is outside the largest radius — return zeros
        return out

    visited = np.zeros(nm.n_faces, dtype=bool)
    visited[fi] = True
    queue = deque([fi])
    radii_sq = {r: r * r for r in radii}

    while queue:
        cur = queue.popleft()
        cur_diff = nm.face_centroid[cur] - pos
        cur_d2 = float(np.dot(cur_diff, cur_diff))
        if cur_d2 > R_max_sq:
            continue

        cur_area = float(nm.face_area[cur])
        for r in radii:
            if cur_d2 <= radii_sq[r]:
                out[f'area_{int(r)}m'] += cur_area
        if cur_d2 <= radii_sq[5.0] if 5.0 in radii_sq else 25.0:
            out['reach_count_5m'] += 1

        # Walk neighbors via opposite_face on each edge of this face
        s = int(nm.face_edges_start[cur])
        n = int(nm.face_num_edges[cur])
        for ei in range(s, s + n):
            opp = int(nm.edge_opp_face[ei])
            if opp == EDGE_BORDER_SENTINEL or opp < 0 or opp >= nm.n_faces:
                continue
            if visited[opp]:
                continue
            # Cheap early reject: if the opposite face's centroid is way
            # outside the max radius, skip enqueueing (the BFS step would
            # bail anyway, but this saves the queue traffic).
            opp_diff = nm.face_centroid[opp] - pos
            if float(np.dot(opp_diff, opp_diff)) > R_max_sq:
                visited[opp] = True
                continue
            visited[opp] = True
            queue.append(opp)

    return out


# =============================================================================
# CLI smoke test
# =============================================================================
if __name__ == '__main__':
    import json
    if len(sys.argv) < 3:
        print('Usage: navmesh_polygon_metrics.py <bnd_path> <x> <y> <z> [<x> <y> <z>...]')
        sys.exit(1)
    bnd = sys.argv[1]
    nm = load_navmesh(bnd)
    if nm is None:
        print(f'Failed to load {bnd}')
        sys.exit(1)
    print(f'Loaded {os.path.basename(bnd)}: '
          f'{nm.n_faces} faces, {nm.n_vertices} verts, '
          f'aabb=[{nm.aabb_min.tolist()}, {nm.aabb_max.tolist()}]')
    coords = sys.argv[2:]
    for i in range(0, len(coords), 3):
        x, y, z = float(coords[i]), float(coords[i+1]), float(coords[i+2])
        m = slot_metrics(nm, (x, y, z))
        print(f'\nslot ({x:.2f}, {y:.2f}, {z:.2f}):')
        print(json.dumps(m, indent=2))
