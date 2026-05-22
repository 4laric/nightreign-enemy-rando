"""
test_validate_placements.py — smoke + unit tests for the placement
validator (dev/validate_placements.py).

Scope is intentionally narrow: confirm that
  (a) the validator imports and loads the engine without crashing,
  (b) known-good placements classify as CLEAN,
  (c) known-bad placements (constructed to fire specific gates) classify
      as WOULD_REJECT or RELEASED appropriately,
  (d) the spoiler→manifest pipeline produces a sorted, JSON-safe dict.

Run with pytest from the repo root:
  pytest tests/test_validate_placements.py -q
"""

import json
import os
import sys

import pytest


# Add dev/ to path so we can import the validator. We're in tests/, the
# validator is in dev/.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEV = os.path.join(REPO, 'dev')
if DEV not in sys.path:
    sys.path.insert(0, DEV)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


@pytest.fixture(scope='module')
def ctx():
    """Loaded ValidationContext, shared across tests in this module.
    Engine load is ~3s so we don't want to repeat it per test."""
    import validate_placements as vp
    return vp.build_context(chaos_mode=False)


@pytest.fixture(scope='module')
def vp_module():
    import validate_placements as vp
    return vp


def _make_placement(vp, msb='m32_00_00_00.msb', pi=56,
                    pos=(-17.65, 11.48, -41.2),
                    src_cp='c4371', src_name='Godrick Foot Soldier',
                    src_npc_param=43710000,
                    target_cp='c4314', target_name='Radahn Soldier',
                    target_npc_param=43140010,
                    spoiler_flags=None):
    if spoiler_flags is None:
        spoiler_flags = (('disable_resilient_filter', False),
                         ('multiplayer_safe', False),
                         ('oops_all_nb_target_cp', None))
    return vp.Placement(
        seed=999999,
        engine_fingerprint='test',
        msb=msb, pi=pi, pos=pos,
        src_cp=src_cp, src_name=src_name, src_npc_param=src_npc_param,
        target_cp=target_cp, target_name=target_name,
        target_npc_param=target_npc_param,
        entity_id=0, is_boss=False,
        catalog_tier=None, catalog_scope=None,
        spoiler_flags=spoiler_flags,
    )


def test_engine_loads(ctx):
    """Sanity: engine import + load_data succeeds."""
    assert ctx.tags, 'tags dict should be populated'
    assert ctx.engine is not None
    # Spot-check a known constant is non-empty.
    assert ctx.engine.V3_NIGHT_BOSS_NAME_MARKERS, \
        'NB markers should be populated post-load_data'


def test_clean_placement(vp_module, ctx):
    """A regular grunt-tier swap at a non-fragile slot should be CLEAN.

    c4371 Godrick Foot Soldier at m32_00 pi=56 is documented in the
    seed 522250 spoiler as a real slot (we use it as the canonical
    test fixture)."""
    # Pick a placement we know to be clean by inspection: c4371 →
    # c4314 (Radahn Soldier) at m11 (Roundtable hub, not fragile).
    # m11 is in V3_HUB_MAPS so the picker copies it through, but the
    # gate logic still applies — and grunt→grunt is clean.
    p = _make_placement(vp_module,
                        msb='m11_00_00_00.msb', pi=10,
                        pos=(0.0, 0.0, 0.0),
                        target_cp='c4314', target_name='Radahn Soldier')
    v = vp_module.validate_placement(p, ctx)
    assert v.status in ('CLEAN', 'SUSPICIOUS'), (
        f'expected CLEAN or SUSPICIOUS, got {v.status} with gates '
        f'{[(g.name, g.released_by) for g in v.gates]}')


def test_nb_strict_gate_removed_v0_26_x(vp_module, ctx):
    """v0.23.11 → v0.26.x: NB-strict gate retired. Was a variant-name
    string filter ("source slot variant must contain 'Night Boss'")
    that pretended to be a geometric gate but was actually doing
    string matching; real traversability concerns are handled by
    V3_ARENA_ONLY_TARGETS, V3_FRAGILE_SENSITIVE_TARGETS, and
    anim_class / size_class compat checks. Removed because the
    string filter was blocking 7 marquee NB chrs (Midra, Romina,
    Metyr, Fortissax, Dragonslayer Armor + vanilla c4510/c4580)
    from finding qualifying reservation slots at 65-81% rates.

    This test confirms the gate is truly gone: the constant is
    empty, the gate doesn't fire, and an old "should-reject" case
    (c5130 Messmer at a non-NB-marker slot) now passes through to
    a normal CLEAN/SUSPICIOUS verdict subject to the remaining
    gates."""
    assert ctx.engine.V3_NIGHT_BOSS_STRICT_TARGETS == set(), (
        f'V3_NIGHT_BOSS_STRICT_TARGETS should be empty post-v0.26.x; '
        f'got {ctx.engine.V3_NIGHT_BOSS_STRICT_TARGETS}')
    p = _make_placement(vp_module,
                        msb='m32_00_00_00.msb', pi=56,
                        src_cp='c4371', src_name='Godrick Foot Soldier',
                        target_cp='c5130', target_name='Messmer the Impaler')
    v = vp_module.validate_placement(p, ctx)
    gate_names = [g.name for g in v.gates if g.rejected]
    assert 'nb_strict' not in gate_names, (
        f'nb_strict gate should not fire (was retired in v0.26.x); '
        f'got rejected gates {gate_names}')


def test_fragile_slot_rejected_grunt_target(vp_module, ctx):
    """At a fragile slot (m32_00 is in V3_FRAGILE_MAPS), a target not
    in RESILIENT_BIPEDS ∪ FRAGILE_SAFE_CONFIRMED must be rejected by
    the fragile_slot_filter gate."""
    assert 'm32_00_00_00.msb' in ctx.engine.V3_FRAGILE_MAPS, (
        'test assumes m32_00 in V3_FRAGILE_MAPS')
    p = _make_placement(vp_module,
                        msb='m32_00_00_00.msb', pi=56,
                        target_cp='c5130', target_name='Messmer the Impaler')
    v = vp_module.validate_placement(p, ctx)
    gate_names = [g.name for g in v.gates if g.rejected]
    assert 'fragile_slot_filter' in gate_names, (
        f'expected fragile_slot_filter, got {gate_names}')


def test_disable_resilient_filter_suppresses_fragile_gate(vp_module, ctx):
    """When the spoiler header says disable_resilient_filter=True,
    the diagnostic-mode run is intentionally exercising untested
    c-prefixes at fragile slots. Validator should suppress that gate."""
    flags = (('disable_resilient_filter', True),
             ('multiplayer_safe', False),
             ('oops_all_nb_target_cp', None))
    p = _make_placement(vp_module,
                        msb='m32_00_00_00.msb', pi=56,
                        target_cp='c5130', target_name='Messmer the Impaler',
                        spoiler_flags=flags)
    v = vp_module.validate_placement(p, ctx)
    gate_names = [g.name for g in v.gates if g.rejected]
    # nb_strict / other gates may still fire, but fragile_slot_filter
    # should NOT.
    assert 'fragile_slot_filter' not in gate_names, (
        f'expected fragile_slot_filter suppressed in diagnostic mode, '
        f'got {gate_names}')


def test_no_emerge_gate_fires(vp_module, ctx):
    """Place an emerge_from_ground chr at a no-emerge slot — must
    fire the no_emerge_terrain gate."""
    # Find any (msb, pi) in V3_NO_EMERGE_SLOTS and any cp in
    # V3_ENTRANCE_ANIM_CLASS with anim='emerge_from_ground'.
    no_emerge = sorted(ctx.engine.V3_NO_EMERGE_SLOTS)
    emerge_cps = [cp for cp, a in ctx.engine.V3_ENTRANCE_ANIM_CLASS.items()
                  if a == 'emerge_from_ground']
    if not no_emerge or not emerge_cps:
        pytest.skip('no V3_NO_EMERGE_SLOTS or V3_ENTRANCE_ANIM_CLASS entries')
    msb, pi = no_emerge[0]
    p = _make_placement(vp_module, msb=msb, pi=pi,
                        src_cp='c4300', src_name='Wandering Noble',
                        target_cp=emerge_cps[0],
                        target_name='emerge test chr')
    v = vp_module.validate_placement(p, ctx)
    gate_names = [g.name for g in v.gates if g.rejected]
    assert 'no_emerge_terrain' in gate_names, (
        f'expected no_emerge_terrain, got {gate_names}')


def test_non_anchored_boss_slot_suspicion(vp_module, ctx):
    """v0.24.86: post-Track-C suspicion. A placement at a catalog-tagged
    boss slot whose intro_anchored=False, targeting a chr in
    V3_NIGHT_BOSS_CALIBER_TARGETS / STRICT_TARGETS, should produce a
    SUSPICIOUS verdict with the non_anchored_boss_slot tag.

    Worked example: m15_00 pi=325 — catalog entry exists with
    intro_anchored=False, target c5130 Messmer in NB_STRICT_TARGETS."""
    # Precondition: confirm the catalog entry has the new field.
    # Use pi=9, the first m15 catalog slot (catalog covers pi 9-63).
    cat_entry = ctx.engine.V3_BOSS_SLOT_CATALOG.get(
        ('m15_00_00_00.msb', 9))
    if cat_entry is None:
        pytest.skip('m15:9 not in V3_BOSS_SLOT_CATALOG '
                    '— catalog may not be at schema v2')
    if cat_entry.get('intro_anchored') is not False:
        pytest.skip('m15:9 expected intro_anchored=False; '
                    'catalog may be stale')
    if 'c5130' not in ctx.engine.V3_NIGHT_BOSS_STRICT_TARGETS:
        pytest.skip('c5130 not in NB_STRICT_TARGETS')
    p = _make_placement(vp_module,
                        msb='m15_00_00_00.msb', pi=9,
                        src_cp='c3661', src_name='Putrid Corpse (Remembrance)',
                        target_cp='c5130', target_name='Messmer the Impaler')
    v = vp_module.validate_placement(p, ctx)
    tags = v.suspicious_tags
    assert any('non_anchored_boss_slot_intro_dependent' in t
               for t in tags), (
        f'expected non_anchored_boss_slot_intro_dependent in '
        f'suspicious_tags, got {tags}')


def test_scripted_intro_required_at_non_anchored(vp_module, ctx):
    """v0.24.86 Track B: chr classified as scripted_intro_required
    placed at a slot with intro_anchored=False should produce the
    high-confidence confirmed suspicion. c3100 (Bell Bearing Hunter)
    at m15:9 (non-anchored per Track C v2 schema) is the canonical
    case."""
    if 'c3100' not in ctx.scripted_intro_class:
        pytest.skip('c3100 not loaded from scripted_intro_chrs.json')
    cat_entry = ctx.engine.V3_BOSS_SLOT_CATALOG.get(
        ('m15_00_00_00.msb', 9))
    if cat_entry is None or cat_entry.get('intro_anchored') is not False:
        pytest.skip('m15:9 not in catalog or not non-anchored')
    p = _make_placement(vp_module,
                        msb='m15_00_00_00.msb', pi=9,
                        target_cp='c3100', target_name='Bell Bearing Hunter')
    v = vp_module.validate_placement(p, ctx)
    tags = v.suspicious_tags
    assert any('scripted_intro_required_at_non_anchored' in t
               for t in tags), (
        f'expected scripted_intro_required_at_non_anchored, got {tags}')


def test_scripted_intro_intolerant_at_anchored(vp_module, ctx):
    """v0.24.86 Track B: opposite direction. scripted_intro_intolerant
    chr (NPC-style, e.g. c4490 Living Jar Warrior) at an anchored slot
    should fire the confirmed suspicion."""
    if 'c4490' not in ctx.scripted_intro_class:
        pytest.skip('c4490 not loaded from scripted_intro_chrs.json')
    anchored_slot = None
    for key, e in ctx.engine.V3_BOSS_SLOT_CATALOG.items():
        if e.get('intro_anchored') is True and e.get('eid', 0) != 0:
            anchored_slot = key
            break
    if anchored_slot is None:
        pytest.skip('no intro_anchored=True slot in catalog')
    p = _make_placement(vp_module,
                        msb=anchored_slot[0], pi=anchored_slot[1],
                        target_cp='c4490', target_name='Living Jar Warrior')
    v = vp_module.validate_placement(p, ctx)
    tags = v.suspicious_tags
    assert any('scripted_intro_intolerant_at_anchored' in t
               for t in tags), (
        f'expected scripted_intro_intolerant_at_anchored, got {tags}')


def test_proxy_does_not_double_flag_confirmed_chrs(vp_module, ctx):
    """v0.24.86 Track B: when a chr is in BOTH NB_CALIBER (proxy) AND
    scripted_intro_chrs.json, only the high-precision tag fires."""
    if 'c3100' not in ctx.scripted_intro_class:
        pytest.skip('c3100 not in scripted_intro_chrs.json')
    if 'c3100' not in ctx.engine.V3_NIGHT_BOSS_CALIBER_TARGETS:
        pytest.skip('c3100 not in NB_CALIBER (fixture assumption stale)')
    cat_entry = ctx.engine.V3_BOSS_SLOT_CATALOG.get(
        ('m15_00_00_00.msb', 9))
    if cat_entry is None or cat_entry.get('intro_anchored') is not False:
        pytest.skip('m15:9 not in catalog or not non-anchored')
    p = _make_placement(vp_module,
                        msb='m15_00_00_00.msb', pi=9,
                        target_cp='c3100', target_name='Bell Bearing Hunter')
    v = vp_module.validate_placement(p, ctx)
    tags = v.suspicious_tags
    has_proxy = any('non_anchored_boss_slot_intro_dependent' in t
                    for t in tags)
    has_confirmed = any('scripted_intro_required_at_non_anchored' in t
                        for t in tags)
    assert has_confirmed, 'confirmed suspicion should fire'
    assert not has_proxy, (
        f'proxy should NOT fire alongside confirmed; got tags {tags}')


def test_wakeup_dormant_placement_flag_retired(vp_module, ctx):
    """v0.24.86-late: audit-closed retirement of the wakeup_dormant
    suspicion. The empirical audit in wakeup_chrs.json's
    empirical_audit_v0_24_86 block proved 103/103 vanilla wakeup-chr
    placements are covered by existing patches (6 via permissive_boss_
    wake allowlist, 97 via permissive_spawn_emerge or explicit
    orchestrator EnableCharacterAI). The suspicion should no longer
    fire on any placement. Test ensures the retirement holds — if a
    future regression reactivates the noisy suspicion, this catches
    it."""
    if 'c4660' not in ctx.wakeup_class:
        pytest.skip('c4660 not loaded from wakeup_chrs.json')
    p = _make_placement(vp_module,
                        msb='m32_00_00_00.msb', pi=56,
                        target_cp='c4660', target_name='Guardian Golem')
    v = vp_module.validate_placement(p, ctx)
    assert not any('wakeup_dormant_placement' in t
                   for t in v.suspicious_tags), (
        f'wakeup_dormant_placement suspicion should be retired per '
        f'audit; got {v.suspicious_tags}')


def test_manifest_row_is_json_safe(vp_module, ctx):
    """The manifest row must serialize cleanly (no sets, no tuples
    inside lists, no non-JSON types)."""
    p = _make_placement(vp_module)
    v = vp_module.validate_placement(p, ctx)
    row = vp_module.manifest_row(p, v, ctx)
    # If this raises, the row contains a non-JSON-safe type.
    serialized = json.dumps(row)
    assert serialized, 'serialized row should not be empty'
    # Round-trip check.
    parsed = json.loads(serialized)
    assert parsed['msb'] == p.msb
    assert parsed['pi'] == p.pi


def test_manifest_is_deterministic(vp_module, ctx, tmp_path):
    """Same set of placements produces the same manifest (sorted,
    line-stable) so diffs across versions are meaningful."""
    placements = [
        _make_placement(vp_module, msb='m32_00_00_00.msb', pi=56,
                        target_cp='c5130'),
        _make_placement(vp_module, msb='m32_00_00_00.msb', pi=56,
                        target_cp='c2110'),
        _make_placement(vp_module, msb='m15_00_00_00.msb', pi=325,
                        target_cp='c5130'),
    ]
    rows1 = []
    rows2 = []
    for p in placements:
        v = vp_module.validate_placement(p, ctx)
        rows1.append(vp_module.manifest_row(p, v, ctx))
    for p in placements:
        v = vp_module.validate_placement(p, ctx)
        rows2.append(vp_module.manifest_row(p, v, ctx))
    path1 = tmp_path / 'm1.json'
    path2 = tmp_path / 'm2.json'
    vp_module.write_manifest(rows1, str(path1))
    vp_module.write_manifest(rows2, str(path2))
    assert path1.read_text() == path2.read_text(), \
        'same input must produce byte-identical manifest output'
