#!/usr/bin/env python3
"""extract_think_param_ids.py — regenerate data/valid_think_param_ids.json.

Reads the NpcThinkParam table from a regulation CSV dump (the Smithbox /
WitchyBND export of regulation.bin's NpcThinkParam param) and writes the
sorted set of valid NpcThinkParam IDs to data/valid_think_param_ids.json.

load_data() validates every roster think_param_id against this manifest and
auto-avoid-lists any variant whose think id is absent — the c5251 / v0.27.23
AI-inert failure class. The engine writes the roster's think_param_id straight
into the MSB Part with NO runtime validation, so a think id that is missing
from the regulation spawns a chr with no AI (it loads, may aggro, but never
runs its battle logic). This manifest is what closes that hole at load time.

Run this whenever the regulation's NpcThinkParam table changes (new heritage
imports, authored think rows, etc.):

    python dev/extract_think_param_ids.py /path/to/regulation/NpcThinkParam.csv

If no path is given, it looks for ./NpcThinkParam.csv then
./regulation/NpcThinkParam.csv.

The CSV is expected to have the ID in the first column (Smithbox/WitchyBND
default export format: `ID,Name,...`). Rows whose first cell is not a base-10
integer (header, blanks, comment rows) are skipped.
"""
import csv
import json
import os
import sys
from datetime import date

# data/ lives one level up from dev/
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(os.path.dirname(_HERE), "data")
_OUT = os.path.join(_DATA, "valid_think_param_ids.json")

_DEFAULT_LOCATIONS = [
    "NpcThinkParam.csv",
    os.path.join("regulation", "NpcThinkParam.csv"),
]


def _resolve_input(argv):
    if len(argv) > 1:
        return argv[1]
    for cand in _DEFAULT_LOCATIONS:
        if os.path.isfile(cand):
            return cand
    return None


def extract_ids(csv_path):
    """Return the sorted set of integer IDs from column 0 of the CSV."""
    ids = set()
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if row and row[0].strip().lstrip("-").isdigit():
                ids.add(int(row[0]))
    return sorted(ids)


def write_manifest(ids, version_hint="dev"):
    manifest = {
        "_meta": {
            "description": (
                "Valid NpcThinkParam IDs present in the NR mod regulation. "
                "load_data() validates every roster think_param_id against this "
                "set and auto-avoid-lists any variant whose think id is absent "
                "(the c5251 / v0.27.23 AI-inert failure class: the engine writes "
                "the roster think_param_id straight into the MSB Part with no "
                "runtime validation, so a think id missing from the regulation "
                "spawns an AI-inert chr). Regenerate with "
                "dev/extract_think_param_ids.py whenever the regulation's "
                "NpcThinkParam table changes."
            ),
            "source": "regulation NpcThinkParam.csv",
            "count": len(ids),
            "generated_for_version": version_hint,
            "generated_on": date.today().isoformat(),
            "schema": "v1",
        },
        "valid_think_param_ids": ids,
    }
    with open(_OUT, "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    return _OUT


def main():
    csv_path = _resolve_input(sys.argv)
    if not csv_path:
        print(
            "usage: python dev/extract_think_param_ids.py "
            "<regulation/NpcThinkParam.csv>\n"
            "  (or run from a dir containing NpcThinkParam.csv "
            "or regulation/NpcThinkParam.csv)",
            file=sys.stderr,
        )
        sys.exit(1)
    if not os.path.isfile(csv_path):
        print(f"error: not found: {csv_path}", file=sys.stderr)
        sys.exit(1)
    ids = extract_ids(csv_path)
    if not ids:
        print(
            f"error: no integer IDs parsed from {csv_path} — "
            "wrong file or unexpected format?",
            file=sys.stderr,
        )
        sys.exit(1)
    out = write_manifest(ids)
    print(f"wrote {out}")
    print(f"  {len(ids)} valid NpcThinkParam IDs")
    print(f"  range: {ids[0]} .. {ids[-1]}")


if __name__ == "__main__":
    main()
