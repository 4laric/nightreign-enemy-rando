"""
verify.py — Cross-check the binary EMEVD parser against the DSAS3
.js oracle.

This is the moment-of-truth runbook when Alaric uploads the raw
.emevd files. For each (binary, js) pair, the verifier:

  1. Parses the binary -> [HealthbarCallsite]
  2. Parses the .js     -> [OracleCallsite]
  3. Joins them on (handler_id, event_id, chr_entity_ids, name_group_index)
  4. Confirms nameId values match across the join

If everything matches, the binary parser is trustworthy and we can
ship the in-place patcher. If there are mismatches, the verifier
prints them out and the byte-offset math needs revisiting before
shipping.

Usage:

  python verify.py <emevd_file> <emevd_js_file>

The two files should be the same map (e.g. m49_25_00_00.emevd and
m49_25_00_00.emevd.dcx.js).
"""

import sys
from collections import defaultdict
from emevd import EMEVD, extract_healthbar_callsites
from oracle import extract_from_js, to_join_key


def verify_pair(emevd_path, js_path, *, verbose=True):
    """Returns (ok, report_dict)."""
    with open(emevd_path, 'rb') as f:
        raw = f.read()
    parsed = EMEVD.parse(raw)
    binary_cs = extract_healthbar_callsites(parsed)
    oracle_cs = extract_from_js(js_path)

    binary_by_key = {to_join_key(c.handler_id, c.event_id,
                                  c.chr_entity_ids, c.name_group_index): c
                     for c in binary_cs}
    oracle_by_key = {to_join_key(c.handler_id, c.event_id,
                                  c.chr_entity_ids, c.name_group_index): c
                     for c in oracle_cs}

    binary_keys = set(binary_by_key)
    oracle_keys = set(oracle_by_key)

    matched = binary_keys & oracle_keys
    only_binary = binary_keys - oracle_keys
    only_oracle = oracle_keys - binary_keys

    # For each matched callsite, do nameIds agree?
    nameid_mismatches = []
    for k in matched:
        b = binary_by_key[k]
        o = oracle_by_key[k]
        if b.name_id != o.name_id:
            nameid_mismatches.append({
                'key': k,
                'binary_name_id': b.name_id,
                'oracle_name_id': o.name_id,
                'binary_offset': b.name_id_file_offset,
                'oracle_line': o.source_line,
            })

    report = {
        'emevd': emevd_path,
        'js': js_path,
        'binary_callsites': len(binary_cs),
        'oracle_callsites': len(oracle_cs),
        'matched': len(matched),
        'only_in_binary': sorted(only_binary),
        'only_in_oracle': sorted(only_oracle),
        'nameid_mismatches': nameid_mismatches,
    }

    ok = (
        not only_binary and not only_oracle and not nameid_mismatches
    )

    if verbose:
        print(f"=== {emevd_path} ===")
        print(f"  binary callsites: {len(binary_cs)}")
        print(f"  oracle callsites: {len(oracle_cs)}")
        print(f"  matched: {len(matched)}")
        if only_binary:
            print(f"  ONLY IN BINARY ({len(only_binary)}):")
            for k in sorted(only_binary)[:10]:
                print(f"    {k}")
            if len(only_binary) > 10:
                print(f"    ... and {len(only_binary) - 10} more")
        if only_oracle:
            print(f"  ONLY IN ORACLE ({len(only_oracle)}):")
            for k in sorted(only_oracle)[:10]:
                print(f"    {k}")
            if len(only_oracle) > 10:
                print(f"    ... and {len(only_oracle) - 10} more")
        if nameid_mismatches:
            print(f"  NAMEID MISMATCHES ({len(nameid_mismatches)}):")
            for m in nameid_mismatches[:10]:
                print(f"    {m['key']}: binary={m['binary_name_id']} "
                      f"oracle={m['oracle_name_id']} "
                      f"(byte@{m['binary_offset']}, .js line {m['oracle_line']})")
        print(f"  {'PASS' if ok else 'FAIL'}")

    return ok, report


def main():
    if len(sys.argv) != 3:
        print("usage: python verify.py <emevd_file> <emevd_js_file>", file=sys.stderr)
        sys.exit(2)
    ok, _ = verify_pair(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
