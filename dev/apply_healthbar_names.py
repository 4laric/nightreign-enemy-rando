#!/usr/bin/env python3
"""
apply_healthbar_names.py — Rewrite EMEVD boss-wake nameIds so on-screen
healthbars match the chrs the randomizer actually placed at each entity_id.

Operates in two phases:

PHASE 1 — GENERATE name_table.json (run first):

  python apply_healthbar_names.py GENERATE \
      --spoiler seeds/seed12345/_spoilers.json \
      --callsites callsites.json \
      --chr-nameid chr_to_nameid.json \
      --out name_table.json

  Produces a curatable name table. Each entry describes one healthbar slot
  (one nameId arg position in one $InitializeCommonEvent call) with the
  default new name the tool would auto-pick. Edit `user_override.new_name`
  on any entry to use a custom name (e.g. "Putrid Shaman of the King
  Consort" for a mashup); leave it null to keep the default.

PHASE 2 — APPLY (run after curating):

  python apply_healthbar_names.py APPLY \
      --name-table name_table.json \
      --in-emevd vanilla_emevd_js/ \
      --out-emevd patched_emevd_js/ \
      --fmg-additions fmg_additions.json

  Reads each .emevd.dcx.js in the input dir, rewrites the targeted
  nameId arg positions per name_table.json, and writes patched copies
  to the output dir. Emits fmg_additions.json listing every new nameId
  the patched EMEVD references along with the text it should display —
  feed this to your FMG editor of choice (WitchyBND, etc.) to add the
  entries to the appropriate boss-name FMG before recompiling.

Naming policy:

  Solo bar: use the swapped chr's display name from the spoiler.
  Shared bar with all chrs identical after swap: use that chr's name.
  Shared bar with heterogeneous swaps (the squad-desync case): use a
    fallback composite name. Default policy is "list with count":
    "Lichdragon Fortissax + Wormface ×2". Override via the
    user_override field per callsite.

  When the swapped chr is also a chr that appears in vanilla NR with
  its own canonical nameId (per chr_to_nameid.json), we REUSE that
  vanilla nameId where possible to avoid bloating the FMG additions.
  Composite names always require fresh nameIds.

  Fresh nameIds are auto-allocated from a base starting at 9700000000.
  Pick a base that doesn't collide with the vanilla NR / DLC FMG ID
  ranges; the default sits above the highest known vanilla healthbar
  nameId (~907xxxxxx) and is unlikely to clash. Override with
  --fmg-id-base if you have specific FMG-table requirements.
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict, OrderedDict


# Same regex as audit. We re-find the call by line number during APPLY so we
# can rewrite individual args in-place without rebuilding the whole file.
_CALL_RE = re.compile(
    r'(\$InitializeCommonEvent\s*\(\s*)'   # 1: opener
    r'(\d+)\s*,\s*'                        # 2: slot
    r'(\d+)\s*'                            # 3: event_id
    r'((?:,[^)]*)?)'                       # 4: rest
    r'(\s*\)\s*;?)',                       # 5: closer
    re.DOTALL
)


DEFAULT_FMG_ID_BASE = 9700000000


# -----------------------------------------------------------------------------
# Phase 1: GENERATE name_table.json
# -----------------------------------------------------------------------------

def _index_spoiler(spoiler):
    """entity_id (int) -> spoiler entry dict (with new.c_prefix, new.name, ...)."""
    out = {}
    for e in spoiler.get('placements', spoiler.get('entries', [])):
        eid = e.get('entity_id')
        if eid is not None:
            out[int(eid)] = e
    return out


def _load_spoiler(path):
    """The spoiler shape ships entries in different shapes depending on engine
    version; we accept either a flat 'placements' / 'entries' list or a nested
    'entries_by_map' grouping. Normalize to a flat list keyed by entity_id."""
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    if 'placements' in d:
        return d, _index_spoiler(d)
    if 'entries' in d:
        return d, _index_spoiler(d)
    if 'entries_by_map' in d:
        flat = []
        for entries in d['entries_by_map'].values():
            flat.extend(entries)
        d['placements'] = flat
        return d, _index_spoiler(d)
    raise ValueError(f"Spoiler {path} has no recognized entries field")


def _composite_squad_name(swapped_chrs):
    """Produce a 'list with count' composite name for a heterogeneous squad.
    swapped_chrs: list of (c_prefix, display_name) for each chr in the group.
    Returns a single string, e.g. 'Lichdragon Fortissax + Wormface ×2'.
    Order is by descending count then by name for determinism."""
    # Count by display name (so two variants of the same chr don't get
    # listed separately just because their npcParamIds differ).
    counts = defaultdict(int)
    for _cp, name in swapped_chrs:
        counts[name] += 1
    # Sort: most-frequent first, then alphabetical for ties.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = []
    for name, n in ordered:
        if n == 1:
            parts.append(name)
        else:
            parts.append(f"{name} ×{n}")
    return " + ".join(parts)


def _resolve_callsite_default(callsite, eid_index, chr_to_nameid, fmg_id_allocator):
    """Decide what new_name + new_name_id this callsite group should display
    after rando. Returns a dict suitable for embedding in the name_table.

    Strategy:
      1. Look up each chrEntityId in the spoiler. Skip ids that aren't in the
         spoiler (these are EMEVD-direct-spawn entities that the rando doesn't
         touch — Generator-rewire territory, deferred to v0.24).
      2. If all surviving entries share a display name → that's the new name.
         Try to reuse a vanilla nameId for that c_prefix from chr_to_nameid.
      3. If they don't share a name → it's a heterogeneous squad. Build a
         composite name and allocate a fresh nameId for it.
      4. If nothing was found in the spoiler at all (every chrEntityId missing
         OR every chr_entity_id_arg_value is 0) → mark inactive_in_seed; the
         APPLY phase will leave the vanilla nameId untouched.
    """
    chr_ids = callsite['chr_entity_id_arg_values']
    swapped_chrs = []
    missing_ids = []
    for cid in chr_ids:
        if not isinstance(cid, int) or cid == 0:
            continue
        sp = eid_index.get(cid)
        if sp is None:
            missing_ids.append(cid)
            continue
        new = sp.get('new', {})
        cp = new.get('c_prefix', '?')
        name = new.get('name', cp)
        swapped_chrs.append((cp, name))

    if not swapped_chrs:
        return {
            'status': 'inactive_in_seed',
            'reason': ('no chrEntityIds in spoiler' if missing_ids
                       else 'all chrEntityIds are zero'),
            'missing_chr_entity_ids': missing_ids,
            'default_new_name': None,
            'default_new_name_id': None,
            'requires_fmg_addition': False,
        }

    # Are they all the same display name?
    names = {n for _cp, n in swapped_chrs}
    if len(names) == 1:
        cp = swapped_chrs[0][0]
        new_name = swapped_chrs[0][1]
        existing = chr_to_nameid.get(cp)
        if existing:
            # Reuse the first known vanilla nameId for this c_prefix. Stable
            # across runs (chr_to_nameid is deterministic) and avoids an FMG
            # addition for chrs that already have a vanilla name.
            return {
                'status': 'reuse_vanilla',
                'default_new_name': new_name,
                'default_new_name_id': existing[0],
                'requires_fmg_addition': False,
            }
        else:
            new_id = fmg_id_allocator(new_name)
            return {
                'status': 'fresh_allocation',
                'default_new_name': new_name,
                'default_new_name_id': new_id,
                'requires_fmg_addition': True,
            }
    else:
        # Heterogeneous squad → composite + fresh allocation.
        new_name = _composite_squad_name(swapped_chrs)
        new_id = fmg_id_allocator(new_name)
        return {
            'status': 'heterogeneous_squad',
            'default_new_name': new_name,
            'default_new_name_id': new_id,
            'requires_fmg_addition': True,
        }


def _build_fmg_id_allocator(base):
    """Return a function that mints unique sequential nameIds for unique text
    strings. Two callsites that resolve to the SAME text get the SAME id —
    one FMG entry serves both. Order-stable across runs as long as the
    callsites are visited in the same order."""
    next_id = [base]
    by_text = {}
    def allocate(text):
        if text in by_text:
            return by_text[text]
        nid = next_id[0]
        next_id[0] += 1
        by_text[text] = nid
        return nid
    return allocate, by_text


def cmd_generate(args):
    with open(args.callsites, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    spoiler, eid_index = _load_spoiler(args.spoiler)
    with open(args.chr_nameid, 'r', encoding='utf-8') as f:
        chr_to_nameid = json.load(f)

    allocator, _by_text = _build_fmg_id_allocator(args.fmg_id_base)
    table_entries = []
    n_inactive = 0
    n_reuse = 0
    n_fresh = 0
    n_squad = 0
    for cs in manifest['callsites']:
        if not cs.get('is_active', True):
            # Vanilla-inactive (chrEntityId=0); skip in name table since there's
            # nothing to rewrite. We don't even emit an inactive_in_seed row.
            continue
        resolution = _resolve_callsite_default(cs, eid_index, chr_to_nameid, allocator)
        if resolution['status'] == 'inactive_in_seed':
            n_inactive += 1
        elif resolution['status'] == 'reuse_vanilla':
            n_reuse += 1
        elif resolution['status'] == 'fresh_allocation':
            n_fresh += 1
        elif resolution['status'] == 'heterogeneous_squad':
            n_squad += 1
        table_entries.append({
            # Locator: uniquely identifies the arg slot to rewrite.
            'file': cs['file'],
            'line': cs['line'],
            'event_id': cs['event_id'],
            'name_group_index': cs['name_group_index'],
            'name_id_arg_position': cs['name_id_arg_position'],
            # For inspection / curation context:
            'vanilla_name_id': cs['name_id_arg_value'],
            'chr_entity_ids': cs['chr_entity_id_arg_values'],
            'is_shared_bar': cs['is_shared_bar'],
            'swapped_chrs': [
                {'c_prefix': sp.get('new', {}).get('c_prefix'),
                 'name': sp.get('new', {}).get('name')}
                for sp in (eid_index.get(c) for c in cs['chr_entity_id_arg_values'])
                if sp is not None
            ],
            # Resolution: what the tool picked.
            **resolution,
            # User curation: edit this field to override the default.
            'user_override': {'new_name': None, 'new_name_id': None},
        })
    out = OrderedDict([
        ('_meta', {
            'spoiler_path': os.path.abspath(args.spoiler),
            'spoiler_seed': spoiler.get('seed'),
            'spoiler_engine_fingerprint': spoiler.get('engine_fingerprint'),
            'callsites_path': os.path.abspath(args.callsites),
            'chr_nameid_path': os.path.abspath(args.chr_nameid),
            'fmg_id_base': args.fmg_id_base,
            'composite_naming_policy': 'list_with_count',
        }),
        ('_summary', {
            'total_entries': len(table_entries),
            'reuse_vanilla': n_reuse,
            'fresh_allocation': n_fresh,
            'heterogeneous_squad': n_squad,
            'inactive_in_seed': n_inactive,
        }),
        ('entries', table_entries),
    ])
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    sys.stderr.write(f"GENERATE complete. {len(table_entries)} entries.\n")
    sys.stderr.write(f"  reuse_vanilla:        {n_reuse}\n")
    sys.stderr.write(f"  fresh_allocation:     {n_fresh}\n")
    sys.stderr.write(f"  heterogeneous_squad:  {n_squad}\n")
    sys.stderr.write(f"  inactive_in_seed:     {n_inactive}\n")
    sys.stderr.write(f"Wrote {args.out}\n")


# -----------------------------------------------------------------------------
# Phase 2: APPLY — rewrite .js files
# -----------------------------------------------------------------------------

def _effective_resolution(entry, allocator):
    """Pick the (name, name_id) the APPLY phase will write. user_override wins
    if present; allocator may need to mint a new id for a user-overridden name."""
    ov = entry.get('user_override') or {}
    if ov.get('new_name'):
        text = ov['new_name']
        nid = ov.get('new_name_id') or allocator(text)
        return text, nid, True  # True = requires FMG addition (overrides are always fresh)
    if entry['status'] == 'inactive_in_seed':
        return None, None, False
    return (entry['default_new_name'],
            entry['default_new_name_id'],
            entry.get('requires_fmg_addition', False))


def _rewrite_one_call(call_args, rewrites_for_call):
    """Given a list of args and a list of (arg_pos, new_value), return the
    new arg list. rewrites_for_call comes from the name table — multiple
    name groups in a 90015023 call produce multiple rewrites for the same
    call."""
    new_args = list(call_args)
    for pos, val in rewrites_for_call:
        if pos >= len(new_args):
            continue  # safety; shouldn't happen if audit was consistent
        new_args[pos] = val
    return new_args


def _format_arg(v):
    """Render an arg back into source text. Ints become decimal literals;
    string args (rare, things like Hero.Executor) pass through verbatim."""
    if isinstance(v, int):
        return str(v)
    return str(v)


def cmd_apply(args):
    with open(args.name_table, 'r', encoding='utf-8') as f:
        nt = json.load(f)

    # Group rewrites by (file, line). One call may need multiple arg rewrites
    # (90015023 has up to 3 name groups), so we collect them all before
    # touching any source.
    rewrites_by_call = defaultdict(list)
    text_by_id = {}
    allocator, _by_text = _build_fmg_id_allocator(
        nt['_meta'].get('fmg_id_base', DEFAULT_FMG_ID_BASE)
    )
    # Pre-seed allocator with all default ids to keep them stable.
    for e in nt['entries']:
        if e.get('default_new_name') and e.get('default_new_name_id'):
            _by_text[e['default_new_name']] = e['default_new_name_id']

    for e in nt['entries']:
        new_name, new_id, fresh = _effective_resolution(e, allocator)
        if new_id is None:
            continue  # inactive_in_seed; vanilla nameId stays
        rewrites_by_call[(e['file'], e['line'])].append(
            (e['name_id_arg_position'], new_id)
        )
        if fresh and new_name is not None:
            text_by_id[new_id] = new_name

    if not os.path.isdir(args.in_emevd):
        sys.stderr.write(f"ERROR: input dir {args.in_emevd} not found\n")
        sys.exit(1)
    os.makedirs(args.out_emevd, exist_ok=True)

    n_files = 0
    n_files_changed = 0
    n_rewrites_applied = 0
    n_calls_modified = 0

    for root, _dirs, files in os.walk(args.in_emevd):
        rel = os.path.relpath(root, args.in_emevd)
        out_root = os.path.join(args.out_emevd, rel) if rel != '.' else args.out_emevd
        os.makedirs(out_root, exist_ok=True)
        for fname in sorted(files):
            in_path = os.path.join(root, fname)
            out_path = os.path.join(out_root, fname)
            if not fname.endswith('.emevd.dcx.js'):
                # Copy non-.js files (e.g. companion .emevd.dcx binaries) so
                # the output dir is a drop-in replacement for the input.
                shutil.copy2(in_path, out_path)
                continue
            n_files += 1
            # Identify the rewrites relevant to this file.
            file_rewrites = {line: ops for (f, line), ops in rewrites_by_call.items()
                             if f == fname}
            if not file_rewrites:
                shutil.copy2(in_path, out_path)
                continue
            # newline='' disables Python's universal-newlines translation so
            # CRLF (DSAS3's default on Windows) round-trips intact. Forgetting
            # this turns the output into LF-only, which DSAS3 may still accept
            # but is a needless deviation from the input's style.
            with open(in_path, 'r', encoding='utf-8', newline='') as f:
                text = f.read()
            # Compute line offsets so we can find which call covers each
            # target line. A call may span multiple lines; we use the line
            # of its $InitializeCommonEvent token as the locator (matches
            # what audit recorded).
            line_starts = [0]
            for i, c in enumerate(text):
                if c == '\n':
                    line_starts.append(i + 1)

            def offset_to_line(off):
                lo, hi = 0, len(line_starts) - 1
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if line_starts[mid] <= off:
                        lo = mid
                    else:
                        hi = mid - 1
                return lo + 1

            new_chunks = []
            last_end = 0
            file_changed = False
            for m in _CALL_RE.finditer(text):
                line = offset_to_line(m.start())
                ops = file_rewrites.get(line)
                if not ops:
                    continue
                # Parse and rewrite this specific call.
                opener = m.group(1)
                slot = m.group(2)
                event_id = m.group(3)
                rest_text = m.group(4)
                closer = m.group(5)
                # Re-parse args using the same splitter as audit.
                rest = rest_text.lstrip(', ')
                args_list = []
                for tok in rest.split(','):
                    tok = tok.strip()
                    if tok == '':
                        continue
                    try:
                        if tok.startswith('0x') or tok.startswith('-0x'):
                            args_list.append(int(tok, 16))
                        else:
                            args_list.append(int(tok))
                    except ValueError:
                        args_list.append(tok)
                new_args = _rewrite_one_call(args_list, ops)
                # Rebuild the call string. Preserve whitespace style by
                # using ", " between args; this matches DSAS3's default output.
                rebuilt = (
                    f"{opener}{slot}, {event_id}, "
                    + ", ".join(_format_arg(a) for a in new_args)
                    + f"{closer}"
                )
                new_chunks.append(text[last_end:m.start()])
                new_chunks.append(rebuilt)
                last_end = m.end()
                file_changed = True
                n_rewrites_applied += len(ops)
                n_calls_modified += 1
            new_chunks.append(text[last_end:])
            new_text = ''.join(new_chunks)
            with open(out_path, 'w', encoding='utf-8', newline='') as f:
                f.write(new_text)
            if file_changed:
                n_files_changed += 1

    # Emit FMG additions JSON.
    fmg_out = OrderedDict()
    for nid in sorted(text_by_id):
        fmg_out[str(nid)] = text_by_id[nid]
    with open(args.fmg_additions, 'w', encoding='utf-8') as f:
        json.dump({
            '_meta': {
                'spoiler_seed': nt['_meta'].get('spoiler_seed'),
                'count': len(fmg_out),
                'fmg_id_base': nt['_meta'].get('fmg_id_base', DEFAULT_FMG_ID_BASE),
            },
            'entries': fmg_out,
        }, f, indent=2, ensure_ascii=False)

    sys.stderr.write(f"APPLY complete.\n")
    sys.stderr.write(f"  files scanned:    {n_files}\n")
    sys.stderr.write(f"  files changed:    {n_files_changed}\n")
    sys.stderr.write(f"  calls modified:   {n_calls_modified}\n")
    sys.stderr.write(f"  rewrites applied: {n_rewrites_applied}\n")
    sys.stderr.write(f"  FMG entries:      {len(fmg_out)}\n")
    sys.stderr.write(f"Wrote patched .js to: {args.out_emevd}\n")
    sys.stderr.write(f"Wrote FMG additions:  {args.fmg_additions}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    g = sub.add_parser('GENERATE', help='Create name_table.json from spoiler')
    g.add_argument('--spoiler', required=True)
    g.add_argument('--callsites', required=True)
    g.add_argument('--chr-nameid', required=True)
    g.add_argument('--out', default='name_table.json')
    g.add_argument('--fmg-id-base', type=int, default=DEFAULT_FMG_ID_BASE)
    g.set_defaults(func=cmd_generate)

    a = sub.add_parser('APPLY', help='Rewrite .js files from a curated name_table.json')
    a.add_argument('--name-table', required=True)
    a.add_argument('--in-emevd', required=True)
    a.add_argument('--out-emevd', required=True)
    a.add_argument('--fmg-additions', default='fmg_additions.json')
    a.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
