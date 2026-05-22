#!/usr/bin/env python3
"""er_to_nr_param_remap.py — schema-aware Elden Ring -> Nightreign param port.

Elden Ring and Nightreign use DIFFERENT paramdefs. They share a common
column prefix and then diverge:

    NpcParam       ER 322 cols  / NR 356 cols  (diverge at col 22)
    NpcThinkParam  ER 107 cols  / NR 110 cols  (diverge at col 72)
    AtkParam_Npc   ER 214 cols  / NR 223 cols  (diverge at col 39)

A position-based importer (Smithbox CSV import, paste, etc.) reading an
ER row into an NR paramdef lands the shared prefix correctly and then
SHIFTS every column after the divergence point. The row looks fine at a
glance -- Name, hp, behaviorVariationId are in the safe prefix -- but the
spEffect slots, AI-lock flags, NR-only fields, etc. are reading garbage.
That is the classic "imported chr loads but the AI is broken" failure.

This tool ports ER rows into NR's schema correctly: it maps **by column
name**, not by position. For each NR column it takes the ER value when
that column exists in ER; for NR-only columns it fills a sensible
default; ER-only columns are dropped.

It cannot invent NR-specific behavior. A ported ER chr will still need
its NR-side AI (NpcThinkParam logicId/battleGoalID must resolve in the
active aicommon) and matching chr assets. This tool only guarantees the
param ROW is well-formed in NR's schema -- it removes the schema-shift
corruption, nothing more.

Default strategy for NR-only columns (in priority order):
  1. If the same ID already exists in the NR dump, keep NR's own value
     for that column (preserves any NR authoring of that row).
  2. Else copy the value from NR's row "0" (the null/template row) for
     that column -- FromSoft's own "unset" baseline.
  3. Else "0".

Usage
=====
    python3 er_to_nr_param_remap.py \\
        --param NpcParam \\
        --er   /path/vanilla_er/NpcParam.csv \\
        --nr   /path/vanilla_nightreign/NpcParam.csv \\
        --ids  51900000,51900088,51900090 \\
        --out  remapped_NpcParam.csv

  --ids       comma-separated ER row IDs to port. Omit to port every ER
              row that is NOT already present in the NR dump.
  --out       output path (default: remapped_<param>.csv next to --er).

The output is an NR-schema CSV: NR's exact header, NR column order, one
row per requested ID. Import it into NR's regulation via Smithbox as new
rows (or a field patch). All values are already in NR's layout.

Idempotent and read-only with respect to the inputs.
"""
import argparse
import csv
import os
import sys

csv.field_size_limit(10 ** 7)


def load(path):
    with open(path, newline='', encoding='utf-8', errors='replace') as f:
        r = csv.reader(f)
        header = next(r)
        rows = {row[0]: row for row in r if row}
    return header, rows


def column_default(nr_header, nr_rows, col_idx, row_id):
    """Best default for an NR-only column: existing NR row -> NR row 0 -> '0'."""
    if row_id in nr_rows and col_idx < len(nr_rows[row_id]):
        return nr_rows[row_id][col_idx]
    zero = nr_rows.get('0')
    if zero and col_idx < len(zero):
        return zero[col_idx]
    return '0'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--param', required=True, help='param name, e.g. NpcParam (labels only)')
    ap.add_argument('--er', required=True, help='ER dump CSV for this param')
    ap.add_argument('--nr', required=True, help='NR dump CSV for this param (target schema)')
    ap.add_argument('--ids', help='comma-separated ER row IDs to port')
    ap.add_argument('--out', help='output CSV path')
    args = ap.parse_args()

    for p in (args.er, args.nr):
        if not os.path.isfile(p):
            print(f"ERROR: missing input: {p}")
            sys.exit(1)

    er_header, er_rows = load(args.er)
    nr_header, nr_rows = load(args.nr)

    if er_header == nr_header:
        print("NOTE: ER and NR headers are identical for this param -- no "
              "schema remap is needed; a direct copy is safe. Emitting anyway.")

    if er_header[0] != 'ID' or nr_header[0] != 'ID':
        print("WARNING: first column is not 'ID' in one of the dumps -- "
              "verify these are real param CSV exports.")

    # divergence diagnostics
    div = next((i for i in range(min(len(er_header), len(nr_header)))
                if er_header[i] != nr_header[i]), min(len(er_header), len(nr_header)))
    er_only = [c for c in er_header if c not in set(nr_header)]
    nr_only = [c for c in nr_header if c not in set(er_header)]
    print(f"{args.param}: ER {len(er_header)} cols / NR {len(nr_header)} cols, "
          f"identical through col {div}.")
    print(f"  ER-only columns dropped on port: {len(er_only)}  {er_only[:8]}{'...' if len(er_only) > 8 else ''}")
    print(f"  NR-only columns defaulted:       {len(nr_only)}  {nr_only[:8]}{'...' if len(nr_only) > 8 else ''}")

    # which IDs
    if args.ids:
        want = [i.strip() for i in args.ids.split(',') if i.strip()]
        missing = [i for i in want if i not in er_rows]
        if missing:
            print(f"WARNING: {len(missing)} requested ID(s) not in the ER dump: {missing}")
        want = [i for i in want if i in er_rows]
    else:
        want = sorted((i for i in er_rows if i not in nr_rows), key=lambda x: int(x))
        print(f"  --ids omitted: porting every ER row absent from NR ({len(want)} rows).")

    # build NR-schema rows. map by NAME.
    er_idx = {name: i for i, name in enumerate(er_header)}
    out_rows = []
    defaulted_overlap = 0   # NR-only cols filled from an existing NR row
    for rid in want:
        er_row = er_rows[rid]
        new_row = []
        for nr_i, col in enumerate(nr_header):
            if col in er_idx and er_idx[col] < len(er_row):
                new_row.append(er_row[er_idx[col]])
            else:
                if rid in nr_rows:
                    defaulted_overlap += 1
                new_row.append(column_default(nr_header, nr_rows, nr_i, rid))
        out_rows.append(new_row)

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.er)), f"remapped_{args.param}.csv")
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(nr_header)
        w.writerows(out_rows)

    print(f"\nPorted {len(out_rows)} row(s) into NR schema -> {out_path}")
    if defaulted_overlap:
        print(f"  ({defaulted_overlap} NR-only cell(s) were filled from an "
              f"existing NR row of the same ID, preserving NR authoring.)")
    print("\nReminder: this fixes the param ROW layout only. The ported chr "
          "still needs its AI to resolve in NR -- NpcThinkParam "
          "logicId/battleGoalID must exist in the active aicommon, and the "
          "chr's anibnd/behbnd must be NR-compatible. Schema-correct param "
          "rows are necessary, not sufficient.")


if __name__ == '__main__':
    main()
