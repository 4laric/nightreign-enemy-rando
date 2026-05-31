#!/usr/bin/env python3
"""vanilla_source.py — supply vanilla Nightreign files (map MSBs, event EMEVDs)
from the game's own encrypted archives via data_archive, with a loose directory
as fallback.

Why this exists
---------------
The shuffle reads ``*.msb.dcx`` from an input dir, and the healthbar pipeline
reads ``*.emevd.dcx`` from an event dir. Both *enumerate a directory*. For a
UXM-unpacked install those dirs exist on disk; for a packed install they don't,
which is why ``input_dir``/``vanilla_emevd_dir`` come up blank there today.

``prefetch_vanilla()`` materializes exactly the files those dirs expect — read
straight out of the archives — so the existing directory-based pipelines run
unchanged, and ``vanilla_msbs/`` becomes an optional fallback instead of a
shipped payload. The file list comes from ``nr_vanilla_manifest.json`` (canonical
map + event paths; facts about the game's layout, not game content).

A read-through primitive (:meth:`VanillaSource.read`) is also provided for
callers that want raw DCX bytes directly — pair it with ``dcx.DCX.decompress_bytes``.

This module adds no third-party dependency: it leans on ``data_archive`` (which
is stdlib-only, plus the bundled ``aes128``) and the standard library.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MANIFEST_PATH = _HERE / "nr_vanilla_manifest.json"


def load_manifest() -> dict:
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


class VanillaSource:
    """Archive-first, loose-fallback reader for vanilla NR files.

    game_dir       : the NR ``.../Game`` dir (for the archive reader). Optional.
    loose_map_dir  : fallback dir of ``*.msb.dcx`` (e.g. bundled ``vanilla_msbs/``
                     or an unpacked ``map/mapstudio``). Optional.
    loose_event_dir: fallback dir of ``*.emevd.dcx`` (e.g. an unpacked ``event/``).
                     Optional.

    If neither an archive nor a loose dir can supply a file, :meth:`read` raises
    ``KeyError`` — so behavior degrades cleanly to "exactly the loose flow" when
    no game dir is available.
    """

    def __init__(self, game_dir=None, loose_map_dir=None, loose_event_dir=None):
        self.loose_map_dir = Path(loose_map_dir) if loose_map_dir else None
        self.loose_event_dir = Path(loose_event_dir) if loose_event_dir else None
        self._archive = None
        if game_dir:
            try:
                from data_archive import DataArchive
                a = DataArchive(game_dir)
                if len(a):                       # only adopt it if it indexed files
                    self._archive = a
            except Exception:
                self._archive = None             # no game dir / bad keys -> loose only

    @property
    def has_archive(self) -> bool:
        return self._archive is not None

    def read(self, rel: str) -> bytes:
        """Return raw (still DCX-compressed) bytes for an in-game relative path
        like ``map/mapstudio/m10_00_00_00.msb.dcx`` or ``event/common.emevd.dcx``.
        Tries the archive first, then the matching loose dir."""
        rel = rel.replace("\\", "/").lstrip("/")
        if self._archive is not None:
            try:
                return self._archive.get("/" + rel)
            except KeyError:
                pass                              # fall through to loose
        name = rel.rsplit("/", 1)[-1]
        if rel.startswith("map/mapstudio/") and self.loose_map_dir:
            p = self.loose_map_dir / name
            if p.is_file():
                return p.read_bytes()
        if rel.startswith("event/") and self.loose_event_dir:
            p = self.loose_event_dir / name
            if p.is_file():
                return p.read_bytes()
        raise KeyError(f"{rel}: not in archive and no loose fallback present")

    def materialize(self, rels, dest_root, *, on_progress=None):
        """Write each ``rel``'s bytes to ``dest_root/<rel>`` (creating the
        ``map/mapstudio`` and ``event`` subdirs). Returns ``(n_ok, failed_list)``.
        A file that's in neither the archive nor the loose dir is skipped and
        reported rather than aborting the batch."""
        dest_root = Path(dest_root)
        n_ok = 0
        failed = []
        rels = list(rels)
        for i, rel in enumerate(rels):
            rel = rel.replace("\\", "/").lstrip("/")
            try:
                data = self.read(rel)
            except KeyError:
                failed.append(rel)
                continue
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            n_ok += 1
            if on_progress:
                on_progress(i + 1, len(rels), rel)
        return n_ok, failed


def prefetch_vanilla(game_dir, cache_root, *, loose_map_dir=None,
                     loose_event_dir=None, on_progress=None):
    """Materialize the canonical vanilla map MSBs + event EMEVDs into
    ``cache_root`` (archive-first, loose-fallback), so the GUI's input-dir and
    vanilla-event-dir can point at ``cache_root/map/mapstudio`` and
    ``cache_root/event``.

    Returns ``(map_dir, event_dir, n_ok, failed_list)``. ``failed_list`` will
    typically be empty; entries here mean a file was in neither source (e.g. a
    ``dlc01``-resident file when that key isn't bundled)."""
    man = load_manifest()
    src = VanillaSource(game_dir, loose_map_dir=loose_map_dir,
                        loose_event_dir=loose_event_dir)
    rels = list(man.get("mapstudio", [])) + list(man.get("event", []))
    n_ok, failed = src.materialize(rels, cache_root, on_progress=on_progress)
    map_dir = str(Path(cache_root) / "map" / "mapstudio")
    event_dir = str(Path(cache_root) / "event")
    return map_dir, event_dir, n_ok, failed


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Prefetch vanilla NR map MSBs + event EMEVDs from the game "
                    "archives into a cache dir. Point the GUI's Vanilla MSBs "
                    "field at <cache>/map/mapstudio and Vanilla event/ at "
                    "<cache>/event.")
    p.add_argument("game_dir", help=".../ELDEN RING NIGHTREIGN/Game")
    p.add_argument("--cache", required=True, help="output cache directory")
    p.add_argument("--loose-map", help="fallback map/mapstudio dir (e.g. vanilla_msbs/)")
    p.add_argument("--loose-event", help="fallback event dir")
    a = p.parse_args()

    def prog(n, total, rel):
        if n % 50 == 0 or n == total:
            print(f"  {n}/{total}", file=sys.stderr)

    map_dir, event_dir, n_ok, failed = prefetch_vanilla(
        a.game_dir, a.cache, loose_map_dir=a.loose_map,
        loose_event_dir=a.loose_event, on_progress=prog)
    print(f"materialized {n_ok} files into {a.cache}")
    if failed:
        print(f"  {len(failed)} not fetched (e.g. dlc01-resident): "
              f"{failed[:5]}{' ...' if len(failed) > 5 else ''}")
    print(f"Vanilla MSBs  ->  {map_dir}")
    print(f"Vanilla event ->  {event_dir}")
