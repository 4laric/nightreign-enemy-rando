#!/usr/bin/env python3
"""er_source.py — read Elden Ring chr / AI-script / sfx files straight out of
ER's encrypted dvdbnd archives (via data_archive + the ER keys), so the heritage
import tools can pull heritage assets from a packed ER install without a UXM unpack.

Mirrors vanilla_source.py (the Nightreign side), but for the base ER game:
  - ELDEN_RING_KEYS / ELDEN_RING_ARCHIVES (from er_keys) drive the reader.
  - er_chr_manifest.json (paths from the UXM ER dictionary) lets us enumerate
    exactly which files belong to a c-prefix — including the variable per-phase
    animation banks (cXXXX_divNN) and texture banks (cXXXX_h/_l) that a glob over
    an unpacked dir would catch but a hash-indexed archive cannot enumerate itself.

Archive-first, loose-fallback: with no ER game dir / bad keys it degrades to the
loose dirs, so callers behave exactly as the unpacked-dir flow. Adds no third-party
dependency (data_archive is stdlib + the bundled aes128).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MANIFEST_PATH = _HERE / "er_chr_manifest.json"

# chr 'cABCD' -> its files live at /chr/cABCD(.|_)…, AI scripts at /script/ABCDnn_…,
# sfx at /sfx/sfxbnd_cABCD.ffxbnd.dcx. (Script ids are the 4-digit chr number plus a
# 2-digit sub-index, e.g. c5210 -> 521000/521010.)
_KIND_PREFIX = (("chr", "/chr/"), ("script", "/script/"), ("sfx", "/sfx/"))


def load_manifest() -> dict:
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _kind_of(rel: str):
    r = "/" + rel.replace("\\", "/").lstrip("/")
    for kind, pfx in _KIND_PREFIX:
        if r.startswith(pfx):
            return kind
    return None


class EldenRingSource:
    """Archive-first, loose-fallback reader for ER heritage assets.

    er_game_dir      : the ER ``.../Game`` dir (holds Data0-3.bhd/.bdt, DLC.bhd/.bdt).
    loose_chr_dir    : fallback flat dir of chr files (e.g. an unpacked ER ``chr/``).
    loose_script_dir : fallback flat dir of luabnd scripts (unpacked ER ``script/``).
    loose_sfx_dir    : fallback flat dir of sfx bundles (unpacked ER ``sfx/``).
    """

    def __init__(self, er_game_dir=None, loose_chr_dir=None,
                 loose_script_dir=None, loose_sfx_dir=None):
        self.loose = {
            "chr": Path(loose_chr_dir) if loose_chr_dir else None,
            "script": Path(loose_script_dir) if loose_script_dir else None,
            "sfx": Path(loose_sfx_dir) if loose_sfx_dir else None,
        }
        self._archive = None
        if er_game_dir:
            try:
                from data_archive import DataArchive
                from er_keys import ELDEN_RING_KEYS, ELDEN_RING_ARCHIVES
                a = DataArchive(er_game_dir, keys=ELDEN_RING_KEYS,
                                archives=ELDEN_RING_ARCHIVES)
                if len(a):
                    self._archive = a
            except Exception:
                self._archive = None
        self._man = None

    @property
    def has_archive(self) -> bool:
        return self._archive is not None

    def manifest(self) -> dict:
        if self._man is None:
            self._man = load_manifest()
        return self._man

    def read(self, rel: str) -> bytes:
        """Raw (still DCX-compressed) bytes for an ER path like
        ``chr/c5210.chrbnd.dcx`` or ``script/521000_battle.luabnd.dcx``.
        Archive first, then the matching loose dir."""
        rel = rel.replace("\\", "/").lstrip("/")
        if self._archive is not None:
            try:
                return self._archive.get("/" + rel)
            except KeyError:
                pass
        kind = _kind_of(rel)
        d = self.loose.get(kind) if kind else None
        if d:
            p = d / rel.rsplit("/", 1)[-1]
            if p.is_file():
                return p.read_bytes()
        raise KeyError(f"{rel}: not in ER archive and no loose fallback present")

    def files_for_prefixes(self, prefixes, kinds=("chr", "script", "sfx")):
        """Return the manifest paths belonging to the given c-prefixes, restricted
        to the requested kinds. Catches the variable cXXXX_divNN / cXXXX_h/_l banks
        and the per-prefix script sub-indices automatically."""
        man = self.manifest()
        prefixes = [p if p.startswith("c") else "c" + p for p in prefixes]
        out = []
        for pfx in prefixes:
            num = pfx[1:]                                   # c5210 -> 5210
            if "chr" in kinds:
                out += [p for p in man.get("chr", [])
                        if re.match(rf"^/chr/{re.escape(pfx)}(?:_|\.)", p)]
            if "script" in kinds:
                out += [p for p in man.get("script", [])
                        if re.match(rf"^/script/{re.escape(num)}\d\d_", p)]
            if "sfx" in kinds:
                out += [p for p in man.get("sfx", [])
                        if re.match(rf"^/sfx/sfxbnd_{re.escape(pfx)}\.", p)]
        seen, uniq = set(), []
        for p in out:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    def materialize(self, rels, dest_root, *, on_progress=None):
        """Write each ``rel``'s bytes to ``dest_root/<rel>`` (creating /chr,
        /script, /sfx as needed). Returns ``(n_ok, failed_list)``."""
        dest_root = Path(dest_root)
        n_ok, failed = 0, []
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

    def materialize_prefixes(self, prefixes, dest_root,
                             kinds=("chr", "script", "sfx"), *, on_progress=None):
        """Convenience: resolve prefixes -> files -> materialize. Returns
        ``(n_ok, failed_list, rels)``."""
        rels = self.files_for_prefixes(prefixes, kinds=kinds)
        n_ok, failed = self.materialize(rels, dest_root, on_progress=on_progress)
        return n_ok, failed, rels


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Read ER chr/script/sfx files for given c-prefixes straight "
                    "from the ER archives (no UXM unpack needed).")
    ap.add_argument("er_game_dir", help=".../ELDEN RING/Game")
    ap.add_argument("--prefixes", required=True,
                    help="comma-separated c-prefixes, e.g. c5210,c4810")
    ap.add_argument("--kinds", default="chr,script,sfx",
                    help="which kinds to include (default: chr,script,sfx)")
    ap.add_argument("--cache", help="materialize the files into this dir "
                                    "(preserving chr/ script/ sfx/ layout)")
    ap.add_argument("--validate", help="byte-compare each file against this "
                                       "unpacked ER root (oracle)")
    a = ap.parse_args()

    prefixes = [p.strip() for p in a.prefixes.split(",") if p.strip()]
    kinds = tuple(k.strip() for k in a.kinds.split(",") if k.strip())
    src = EldenRingSource(a.er_game_dir)
    if not src.has_archive:
        print("Could not open the ER archives (check the Game dir / keys).",
              file=sys.stderr)
        sys.exit(2)

    rels = src.files_for_prefixes(prefixes, kinds=kinds)
    print(f"{len(prefixes)} prefix(es) -> {len(rels)} files")

    if a.validate:
        root = Path(a.validate)
        match = diff = missing = 0
        for rel in rels:
            try:
                data = src.read(rel)
            except KeyError:
                print(f"  MISSING-IN-ARCHIVE {rel}")
                missing += 1
                continue
            loose = root / rel.lstrip("/")
            if not loose.is_file():
                print(f"  (no loose copy to compare: {rel})")
                continue
            if loose.read_bytes() == data:
                match += 1
            else:
                print(f"  DIFFER {rel}  (archive {len(data)}B vs loose "
                      f"{loose.stat().st_size}B)")
                diff += 1
        print(f"\n{match} match / {diff} differ / {missing} missing-in-archive")
        print("Reader matches your ER unpack byte-for-byte."
              if diff == 0 and missing == 0 else "Mismatch — see above.")
    elif a.cache:
        def _prog(n, t, rel):
            if n % 25 == 0 or n == t:
                print(f"  {n}/{t}", file=sys.stderr)
        n_ok, failed = src.materialize(rels, a.cache, on_progress=_prog)
        print(f"materialized {n_ok} files into {a.cache}")
        if failed:
            print(f"  {len(failed)} not fetched: {failed[:5]}"
                  f"{' …' if len(failed) > 5 else ''}")
    else:
        for rel in rels:
            print("  " + rel)
