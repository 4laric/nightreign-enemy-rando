#!/usr/bin/env python3
"""
ctd_lookup.py — pre-fill a CTD report stub from a spoiler.

When a CTD happens, the investigator already knows three things: the
seed, the MSB, and the part index (from the in-game position or the
spoiler md). This script takes those three and writes a stub of
dev/CTD_REPORT_TEMPLATE.md with sections 1, 3, and 4 pre-filled from:

  - the spoiler JSON entry for (msb, pi)
  - the validator's verdict on that placement (calls validate_placements
    in-process — no need to run the validator separately)
  - the engine's V3_* state at v0.24.86 (named_locations, problem_slots,
    position_shifts, fragile_map membership, etc.)
  - chr tags for both vanilla source and substituted target

The investigator then fills sections 5-9 manually (the judgment parts).
This keeps the discipline from CTD_REPORT_TEMPLATE.md but removes the
copy-paste boilerplate.

Usage:
  python dev/ctd_lookup.py \
      --spoiler spoilers/20260515_115651_seed522250_v0.24.84.json \
      --msb m30_30_00_00.msb --pi 45 \
      --slug fort_rampart_emerge_v0_24_77

Writes to dev/ctd_reports/YYYY-MM-DD_<slug>.md by default. Override
with -o <path>. Use -o - to write to stdout.
"""

import argparse
import datetime
import json
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def _format_bool_for_template(b):
    return 'yes' if b else 'no'


def _gate_results_lines(gates_fired):
    """Render gate-fired list as Markdown bullets for section 4."""
    if not gates_fired:
        return '  *(no gates fired)*'
    lines = []
    for g in gates_fired:
        rel = (f' — released_by=`{g["released_by"]}`'
               if g['released_by'] else ' — **unreleased**')
        lines.append(f'  - `{g["name"]}`{rel}')
        if g.get('evidence'):
            lines.append(f'    - evidence: `{json.dumps(g["evidence"])}`')
    return '\n'.join(lines)


def _find_entry(spoiler, msb, pi):
    """Locate the spoiler entry at (msb, pi). Returns None if not found.
    The spoiler can have multiple entries per MSB so we scan."""
    for e in spoiler.get('entries', []):
        if e.get('map') == msb and int(e.get('part_index', -1)) == int(pi):
            return e
    return None


def _axis_classification_lookup(engine, msb, pi, target_cp, src_cp, src_name):
    """Pre-compute axis-classification facts for section 5. Each axis
    entry says yes/no for slot-side and chr-side, so the investigator
    sees the data immediately and only has to decide attribution.

    Returns a dict[axis_name] -> dict of facts."""
    tags = json.load(open(os.path.join(REPO, 'data',
                                        'nr_enemy_tags.json'),
                          encoding='utf-8'))
    target_tags = tags.get(target_cp, {})
    src_tags = tags.get(src_cp, {})

    out = {}

    # Entrance animation
    out['entrance_animation'] = {
        'target_anim_class': engine.V3_ENTRANCE_ANIM_CLASS.get(target_cp,
                                                                'unknown'),
        'target_meta_note': (
            engine.V3_ENTRANCE_ANIM_META.get(target_cp, {})
            .get('_source_note', '')),
        'slot_in_no_emerge': (msb, pi) in engine.V3_NO_EMERGE_SLOTS,
        'no_emerge_meta': (
            engine.V3_NO_EMERGE_SLOTS_META.get((msb, pi), {})),
    }

    # Quadruped / navmesh footprint
    out['quadruped'] = {
        'target_anim_class': target_tags.get('anim_class'),
        'target_locomotion': target_tags.get('locomotion'),
        'slot_in_quadruped_unsafe': (
            (msb, pi) in engine.V3_QUADRUPED_UNSAFE_SLOTS),
        'quadruped_meta': (
            engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get((msb, pi), {})),
    }

    # Flying required
    out['flying'] = {
        'slot_in_flying_required': (
            (msb, pi) in engine.V3_FLYING_REQUIRED_SLOTS),
        'target_anim_is_flying': (
            target_tags.get('anim_class') == 'flying_dragon'),
    }

    # Scripted-intro dependence (chr-side: v0.24.86 Track B
    # scripted_intro_chrs.json — small empirical list; slot-side:
    # intro_anchored from Track C).
    catalog_entry_for_intro = (
        engine.V3_BOSS_SLOT_CATALOG.get((msb, pi)) or {})
    # Read Track B JSONs directly (engine doesn't wire them yet).
    import os as _os
    si_data, wk_data = {}, {}
    si_path = _os.path.join(REPO, 'data', 'scripted_intro_chrs.json')
    if _os.path.isfile(si_path):
        si_data = json.load(open(si_path, encoding='utf-8')).get(
            'scripted_intro_chrs', {})
    wk_path = _os.path.join(REPO, 'data', 'wakeup_chrs.json')
    if _os.path.isfile(wk_path):
        wk_data = json.load(open(wk_path, encoding='utf-8')).get(
            'wakeup_chrs', {})
    out['scripted_intro'] = {
        'target_in_scripted_intro_json': target_cp in si_data,
        'scripted_intro_class': (
            si_data.get(target_cp, {}).get('class', 'unknown')
            if target_cp in si_data else 'not_classified'),
        'target_in_nb_exclude': (
            target_cp in engine.V3_NIGHT_BOSS_EXCLUDE_TARGETS),
        'target_in_nb_strict': (
            target_cp in engine.V3_NIGHT_BOSS_STRICT_TARGETS),
        'target_in_nb_caliber': (
            target_cp in engine.V3_NIGHT_BOSS_CALIBER_TARGETS),
        'slot_in_catalog': (
            (msb, pi) in engine.V3_BOSS_SLOT_CATALOG),
        'slot_intro_anchored': catalog_entry_for_intro.get(
            'intro_anchored'),
        'catalog_tier': catalog_entry_for_intro.get('tier'),
        'catalog_entry': catalog_entry_for_intro,
    }

    # Wakeup-dormant (chr-side: v0.24.86 Track B wakeup_chrs.json;
    # axis empirically audit-closed v0.24.86-late — see _meta.
    # empirical_audit_v0_24_86 in that file. Suspicion retired, but
    # classification still surfaced here so a CTD investigator who's
    # looking at a dormant chr sees the audit's conclusion inline).
    out['wakeup'] = {
        'target_in_wakeup_json': target_cp in wk_data,
        'wakeup_class': (
            wk_data.get(target_cp, {}).get('class', 'unknown')
            if target_cp in wk_data else 'not_classified'),
        'audit_status_note': (
            'AXIS AUDIT-CLOSED v0.24.86-late: 103/103 vanilla wakeup-chr '
            'placements covered by existing EMEVD patches. If symptom '
            'is frozen-dormant, this CTD evidences a case the audit '
            'missed — see CTD template wakeup section for the EMEVD-'
            'inspection checklist before opening nr_no_wake_slots.json.'),
    }

    # Boss-bar tier
    target_tier = target_tags.get('tier')
    catalog_entry = engine.V3_BOSS_SLOT_CATALOG.get((msb, pi)) or {}
    out['boss_bar_tier'] = {
        'target_tier': target_tier,
        'target_in_gated_tiers': (
            target_tier in engine.V3_BOSS_BAR_GATED_TIERS),
        'target_in_safe_confirmed': (
            target_cp in engine.V3_FRAGILE_SAFE_CONFIRMED),
        'slot_catalog_tier': catalog_entry.get('tier'),
        'slot_in_boss_bar_tiers': (
            catalog_entry.get('tier') in engine.V3_BOSS_BAR_TIERS),
    }

    # Size class drift
    out['size_drift'] = {
        'src_size_class': src_tags.get('size_class'),
        'target_size_class': target_tags.get('size_class'),
    }

    # Source-anim forbidden
    src_anim = src_tags.get('anim_class')
    out['source_anim_forbidden'] = {
        'src_anim_class': src_anim,
        'src_anim_in_forbidden_map': (
            src_anim in engine.V3_FORBIDDEN_BY_SOURCE_ANIM),
        'target_in_forbidden_set_for_src': (
            target_cp in engine.V3_FORBIDDEN_BY_SOURCE_ANIM.get(
                src_anim, set())),
    }

    # Script-spawn boss off-arena
    out['script_spawn_boss'] = {
        'target_source': target_tags.get('_source'),
        'target_is_script_spawn': (
            target_tags.get('_source') == 'script_spawn'),
        'target_in_gated_tiers': (
            target_tier in engine.V3_SCRIPT_SPAWN_BOSS_GATED_TIERS),
        'msb_is_overworld': msb.startswith('m60_'),
    }

    # Fragile map / slot
    fragile_now = engine.is_fragile_slot(msb, pi, src_name)
    out['fragile'] = {
        'is_fragile_slot': fragile_now,
        'msb_in_fragile_maps': msb in engine.V3_FRAGILE_MAPS,
        'msb_matches_fragile_prefix': any(
            msb.startswith(p) for p in engine.V3_FRAGILE_MAP_PREFIXES),
        'src_name_has_fragile_qualifier': any(
            f'({q})' in src_name or f'({q}-' in src_name
            for q in engine.V3_FRAGILE_SOURCE_QUALIFIERS),
        'slot_in_problem_slots': (msb, pi) in engine.V3_PROBLEM_SLOTS,
        'problem_slot_reason': engine.V3_PROBLEM_SLOTS.get((msb, pi)),
        'position_shift_active': bool(
            engine.lookup_position_shift(msb, pi)),
        'target_in_resilient': target_cp in engine.V3_RESILIENT_BIPEDS,
        'target_in_safe_confirmed': (
            target_cp in engine.V3_FRAGILE_SAFE_CONFIRMED),
        'target_in_extra_allows': (
            target_cp in (
                engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get((msb, pi))
                or set())),
        'target_in_extra_bans': (
            target_cp in (
                engine.V3_PROBLEM_SLOT_EXTRA_BANS.get((msb, pi))
                or set())),
    }

    return out


def _render_axis_section(facts):
    """Render axis classification as Markdown bullets — terse, all data
    on the page so the investigator can mark verdicts inline."""
    lines = []
    e = facts['entrance_animation']
    lines.append(
        f'- entrance_animation: target_anim=`{e["target_anim_class"]}`, '
        f'slot_in_no_emerge=`{_format_bool_for_template(e["slot_in_no_emerge"])}`. '
        f'Source note: `{e["target_meta_note"][:120]}...`'
        if e['target_meta_note'] else
        f'- entrance_animation: target_anim=`{e["target_anim_class"]}`, '
        f'slot_in_no_emerge=`{_format_bool_for_template(e["slot_in_no_emerge"])}`'
    )
    q = facts['quadruped']
    lines.append(
        f'- quadruped: target_anim=`{q["target_anim_class"]}`, '
        f'target_loco=`{q["target_locomotion"]}`, '
        f'slot_unsafe=`{_format_bool_for_template(q["slot_in_quadruped_unsafe"])}`'
    )
    f = facts['flying']
    lines.append(
        f'- flying: slot_requires_flying=`{_format_bool_for_template(f["slot_in_flying_required"])}`, '
        f'target_is_flying=`{_format_bool_for_template(f["target_anim_is_flying"])}`'
    )
    s = facts['scripted_intro']
    intro_anc = s.get('slot_intro_anchored')
    intro_anc_str = ('yes' if intro_anc is True
                     else 'no (Track C confirms non-anchored)'
                     if intro_anc is False
                     else 'slot not in catalog')
    si_cls = s['scripted_intro_class']
    si_class_str = (f'`{si_cls}` (Track B confirmed)'
                    if si_cls in ('scripted_intro_required',
                                  'scripted_intro_intolerant')
                    else 'not classified')
    lines.append(
        f'- scripted_intro: slot_intro_anchored=`{intro_anc_str}`, '
        f'target_scripted_intro_class={si_class_str}, '
        f'catalog_tier=`{s["catalog_tier"]}`, '
        f'target_in_nb_strict=`{_format_bool_for_template(s["target_in_nb_strict"])}`, '
        f'target_in_nb_caliber=`{_format_bool_for_template(s["target_in_nb_caliber"])}`, '
        f'target_in_nb_exclude=`{_format_bool_for_template(s["target_in_nb_exclude"])}`'
    )
    w = facts['wakeup']
    wk_cls = w['wakeup_class']
    wk_class_str = (f'`{wk_cls}` (Track B confirmed; audit-closed)'
                    if wk_cls == 'wakeup_dormant'
                    else 'not classified')
    lines.append(
        f'- wakeup: target_wakeup_class={wk_class_str}'
        f' — {w["audit_status_note"]}'
    )
    b = facts['boss_bar_tier']
    lines.append(
        f'- boss_bar_tier: target_tier=`{b["target_tier"]}`, '
        f'slot_catalog_tier=`{b["slot_catalog_tier"]}`, '
        f'safe_exempt=`{_format_bool_for_template(b["target_in_safe_confirmed"])}`'
    )
    sd = facts['size_drift']
    lines.append(
        f'- size_drift: src=`{sd["src_size_class"]}`, target=`{sd["target_size_class"]}`'
    )
    sa = facts['source_anim_forbidden']
    lines.append(
        f'- source_anim_forbidden: src_anim=`{sa["src_anim_class"]}`, '
        f'forbidden_match=`{_format_bool_for_template(sa["target_in_forbidden_set_for_src"])}`'
    )
    ss = facts['script_spawn_boss']
    lines.append(
        f'- script_spawn_boss: target_source=`{ss["target_source"]}`, '
        f'msb_overworld=`{_format_bool_for_template(ss["msb_is_overworld"])}`'
    )
    fr = facts['fragile']
    lines.append(
        f'- fragile_slot: is_fragile=`{_format_bool_for_template(fr["is_fragile_slot"])}`, '
        f'in_problem_slots=`{_format_bool_for_template(fr["slot_in_problem_slots"])}`, '
        f'position_shifted=`{_format_bool_for_template(fr["position_shift_active"])}`, '
        f'target_in_RESILIENT=`{_format_bool_for_template(fr["target_in_resilient"])}`, '
        f'target_in_SAFE_CONFIRMED=`{_format_bool_for_template(fr["target_in_safe_confirmed"])}`'
    )
    if fr['problem_slot_reason']:
        lines.append(
            f'  - existing V3_PROBLEM_SLOTS rationale: `{fr["problem_slot_reason"][:160]}...`'
        )
    return '\n'.join(lines)


def _render_stub(spoiler_path, spoiler, entry, validator_row,
                 axis_facts, named_location, slug):
    """Compose the pre-filled Markdown report."""
    seed = spoiler.get('seed')
    fingerprint = (spoiler.get('engine_fingerprint')
                   or spoiler.get('engine_version', 'unknown'))
    today = datetime.date.today().isoformat()

    orig = entry['original']
    new = entry['new']
    pos = entry.get('position', [0, 0, 0])

    status = validator_row['status'] if validator_row else 'NOT_FOUND'
    gates_md = (_gate_results_lines(validator_row['gates_fired'])
                if validator_row else
                '  *(placement not found in spoiler entries — check msb/pi)*')
    suspicious = (', '.join(validator_row['suspicious_tags'])
                  if validator_row and validator_row['suspicious_tags']
                  else 'none')

    nl_block = ''
    if named_location:
        nl_block = (
            f'\n**Named location:**\n'
            f'- slug: `{named_location["slug"]}`\n'
            f'- category: `{named_location.get("category", "?")}`\n'
            f'- label: `{named_location.get("label", "?")}`\n'
            f'- past CTD count at this location: '
            f'{len(named_location.get("ctd_history", []))}\n'
        )
    else:
        nl_block = ('\n**Named location:** *(MSB not in '
                    '`data/nr_named_locations.json` — '
                    'consider adding if recurring)*\n')

    return f'''# CTD Report: {slug}

*Generated by `dev/ctd_lookup.py` on {today}. Sections 1, 3, 4 are
pre-filled from spoiler + validator. Sections 5-9 require manual
attribution per the discipline in `dev/CTD_REPORT_TEMPLATE.md`.*

## 1. Quick reference

- **Filed:** {today}
- **Engine fingerprint at time of CTD:** {fingerprint}
- **Seed:** {seed}
- **Slug:** {slug}
- **Status:** open
- **Sibling reports:** *(check `dev/ctd_reports/` for related)*

One-sentence symptom: *TODO — describe in one sentence*

---

## 2. Symptom classification

*TODO — tick one bullet from CTD_REPORT_TEMPLATE.md section 2.*

---

## 3. Placement context

```
MSB:                 {entry['map']}
Part index (pi):     {entry['part_index']}
Position:            {pos}
Vanilla source cp:   {orig['c_prefix']}
Vanilla source name: {orig.get('name', '')}
Vanilla npc_param:   {orig.get('npc_param_id')}
Substituted cp:      {new['c_prefix']}
Substituted name:    {new.get('name', '')}
Substituted npc_param: {new.get('npc_param_id')}
entity_id:           {entry.get('entity_id')}
is_boss:             {entry.get('is_boss')}
catalog_tier:        {entry.get('catalog_tier')}
catalog_scope:       {entry.get('catalog_scope')}
```
{nl_block}
**Spoiler path:** `{spoiler_path}`

**Screenshot / video evidence:** *TODO*

---

## 4. Validator lookup

- **Validator status:** {status}
- **Gates fired:**
{gates_md}
- **Suspicious tags:** {suspicious}

**Interpretation:** *(see CTD_REPORT_TEMPLATE.md section 4 for the
four-way reading: WOULD_REJECT=picker bug; RELEASED=wrong release;
SUSPICIOUS=add to gate; CLEAN=missing axis)*

---

## 5. Axis attribution

*Pre-computed facts, one bullet per axis. Mark verdict (applies /
classifier incomplete / doesn't apply) inline next to each.*

{_render_axis_section(axis_facts)}

### Other axes / new axis

*TODO — only fill if all the above produce "doesn't apply" verdicts.
See CTD_REPORT_TEMPLATE.md for what to write here.*

---

## 6. Hypothesis

*TODO — one paragraph linking the most likely axis to the symptom.*

---

## 7. Decision

**Anti-pattern check:**

- [ ] CTD is NOT explained by any axis in section 5
- [ ] No behbnd/EMEVD/MSB signature would generalize the fix
- [ ] Next 5 organic placements at this slot would all need this
      slot-specific protection

Decision (tick one):

- [ ] Expand chr classification on existing axis
- [ ] Expand slot classification on existing axis
- [ ] Define new axis
- [ ] Fix gate bypass (picker bug)
- [ ] V3_PROBLEM_SLOTS quarantine — last resort (note owed classifier work)

**Decision rationale:** *TODO*

---

## 8. Action items

- [ ] *TODO*

---

## 9. Validation plan

- **Pre-fix baseline reproduction:** seed {seed}, MSB {entry['map']},
  pi {entry['part_index']} → confirm CTD reproduces
- **Post-fix seed:** *TODO*
- **Validator regression check:** after fix, re-run
  `python dev/validate_placements.py spoilers/<post-fix-spoiler>.json`
  and confirm `{entry['map']}:{entry['part_index']}` classifies as
  CLEAN or RELEASED.

---

## 10. Follow-ups

*TODO*
'''


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spoiler', required=True,
                    help='Spoiler JSON file containing the offending '
                         'placement.')
    ap.add_argument('--msb', required=True,
                    help='MSB filename, e.g. m30_30_00_00.msb')
    ap.add_argument('--pi', type=int, required=True,
                    help='Part index within the MSB.')
    ap.add_argument('--slug', required=True,
                    help='Short snake_case identifier for the report file '
                         '(e.g. fort_rampart_emerge_v0_24_77).')
    ap.add_argument('-o', '--output', default=None,
                    help='Output path. Default: '
                         'dev/ctd_reports/<date>_<slug>.md. Use "-" for '
                         'stdout.')
    args = ap.parse_args(argv)

    # Load spoiler + locate entry.
    with open(args.spoiler, encoding='utf-8') as f:
        spoiler = json.load(f)
    entry = _find_entry(spoiler, args.msb, args.pi)
    if entry is None:
        sys.stderr.write(
            f'ERROR: no entry for {args.msb} pi={args.pi} in '
            f'{args.spoiler}\n')
        return 2

    # Load engine + validator. Reuse validate_placements rather than
    # re-implementing — that's the parity guarantee.
    import validate_placements as vp
    vp._ensure_engine_loaded()
    ctx = vp.build_context(chaos_mode=False)

    # Build a Placement + Verdict for this single entry, then format
    # via the same manifest_row used by the batch path.
    spoiler_flags = (
        ('disable_resilient_filter',
         bool(spoiler.get('disable_resilient_filter'))),
        ('multiplayer_safe',
         bool(spoiler.get('multiplayer_safe'))),
        ('oops_all_nb_target_cp',
         spoiler.get('oops_all_nb_target_cp')),
    )
    p = vp._placement_from_entry(
        seed=int(spoiler.get('seed', 0) or 0),
        fingerprint=(spoiler.get('engine_fingerprint')
                     or spoiler.get('engine_version', 'unknown')),
        entry=entry,
        spoiler_flags=spoiler_flags,
    )
    v = vp.validate_placement(p, ctx)
    validator_row = vp.manifest_row(p, v, ctx)

    # Axis-classification lookup.
    axis_facts = _axis_classification_lookup(
        ctx.engine, args.msb, args.pi,
        target_cp=entry['new']['c_prefix'],
        src_cp=entry['original']['c_prefix'],
        src_name=entry['original'].get('name', '') or '')

    # Named-location lookup.
    named_location = ctx.named_locations.get(args.msb)

    rendered = _render_stub(args.spoiler, spoiler, entry, validator_row,
                            axis_facts, named_location, args.slug)

    if args.output == '-':
        sys.stdout.write(rendered)
        return 0
    out_path = args.output
    if not out_path:
        date = datetime.date.today().isoformat()
        out_dir = os.path.join(REPO, 'dev', 'ctd_reports')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'{date}_{args.slug}.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(rendered)
    sys.stderr.write(f'Wrote {out_path}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
