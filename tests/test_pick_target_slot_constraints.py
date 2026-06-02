"""Tests for `pick_target_cp` — slot constraints.

Split from `tests/test_pick_target.py` in v0.28.x to make the
5,279-line monolith navigable. See sibling `test_pick_target*.py`
files for other themes; the split is enforced by
`tests/test_pick_target_split_lock.py` (lock the (class, method)
set across files).
"""
import random
import pytest
import oops_v3
from engine.state import GateState
from engine import shuffler as _engine_shuffler

class TestOopsAllNbPinnedSlot:
    """v0.24.25: surgical single-slot pin. When oops_all_nb_pinned_slot=
    (msb, pi) is passed alongside oops_all_nb_target_cp, only that exact
    slot gets the target. All other slots fall through to normal picker.

    Plumbing tests (kwarg threads through call chain) + behavioral tests
    (the gate logic in the per-slot loop fires only at the pinned slot).
    """

    def test_cmd_shuffle_v3_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine.cmd_shuffle_v3)
        assert 'oops_all_nb_pinned_slot' in sig.parameters
        # Default should be None so existing callers don't break
        assert sig.parameters['oops_all_nb_pinned_slot'].default is None

    def test_impl_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine._cmd_shuffle_v3_impl)
        assert 'oops_all_nb_pinned_slot' in sig.parameters

    def test_shuffle_msb_v3_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine.shuffle_msb_v3)
        assert 'oops_all_nb_pinned_slot' in sig.parameters

    def test_write_spoiler_logs_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine.write_spoiler_logs)
        assert 'oops_all_nb_pinned_slot' in sig.parameters

    def test_pinned_slot_threads_through_cmd_shuffle_v3(self, engine):
        # End-to-end plumbing: pass a pinned slot to the public wrapper,
        # confirm shuffle_msb_v3 receives it.
        import inspect
        captured = {}

        def fake_impl(*args, **kwargs):
            captured['kwarg'] = kwargs.get('oops_all_nb_pinned_slot')
            return 'fake-result'

        saved = engine._cmd_shuffle_v3_impl
        engine._cmd_shuffle_v3_impl = fake_impl
        try:
            engine.cmd_shuffle_v3(
                input_dir='/tmp/_nothing',
                output_dir='/tmp/_nothing',
                seed=1,
                oops_all_nb_target_cp='c8500',
                oops_all_nb_pinned_slot=('m60_43_37_00.msb', 120))
        finally:
            engine._cmd_shuffle_v3_impl = saved

        assert captured.get('kwarg') == ('m60_43_37_00.msb', 120), (
            f'pinned_slot did not thread through cmd_shuffle_v3 → impl: '
            f'got {captured.get("kwarg")!r}')

    def test_pinned_mode_disables_broad_scope_branch(self, engine):
        # The broad/extended scope branch is gated by
        # `oops_all_nb_pinned_slot is None`. Grep the source to confirm.
        import inspect
        src = inspect.getsource(_engine_shuffler.shuffle_msb_v3)
        # The marker comment is what we rely on
        assert 'v0.24.25' in src, (
            'v0.24.25 marker missing from shuffle_msb_v3 — pinned mode '
            'may have been removed')
        assert 'oops_all_nb_pinned_slot is None' in src, (
            'broad-scope branch is not guarded against pinned mode — '
            'pinned + scope=broad would BOTH fire, defeating the point')


class TestStartingEncampmentCatalog:
    """v0.24.28: data/nr_starting_encampments.json + V3_STARTING_ENCAMPMENT
    _MSBS + 'starting_encampment' scope value. Tests cover the loader,
    the spoiler annotation, and the picker-scope match.
    """

    def test_catalog_loaded(self, engine):
        # The catalog must load — at minimum, m43_01 is shipped.
        assert hasattr(engine, 'V3_STARTING_ENCAMPMENT_MSBS')
        assert hasattr(engine, 'V3_STARTING_ENCAMPMENT_META')
        assert 'm43_01_00_00.msb' in engine.V3_STARTING_ENCAMPMENT_MSBS, (
            'm43_01_00_00.msb missing from V3_STARTING_ENCAMPMENT_MSBS '
            '— is data/nr_starting_encampments.json present and valid?')

    def test_v0_24_34_m43_02_in_catalog(self, engine):
        # v0.24.34: m43_02 added as wandering_demi_human_camp from seed 544094.
        # The "walking route demi-humans" pattern Alaric identified.
        assert 'm43_02_00_00.msb' in engine.V3_STARTING_ENCAMPMENT_MSBS, (
            'm43_02 missing from starting encampment catalog — added in v0.24.34')
        meta = engine.V3_STARTING_ENCAMPMENT_META['m43_02_00_00.msb']
        assert meta.get('label') == 'wandering_demi_human_camp', (
            f'm43_02 label mismatch: {meta.get("label")}')
        assert meta.get('first_observed_seed') == 544094

    def test_catalog_is_frozenset(self, engine):
        # Frozenset prevents accidental mutation at runtime
        assert isinstance(engine.V3_STARTING_ENCAMPMENT_MSBS, frozenset), (
            'V3_STARTING_ENCAMPMENT_MSBS should be a frozenset, got '
            f'{type(engine.V3_STARTING_ENCAMPMENT_MSBS).__name__}')

    def test_catalog_meta_has_entry(self, engine):
        # The META dict should mirror the MSBS set with per-MSB info
        m43 = engine.V3_STARTING_ENCAMPMENT_META.get('m43_01_00_00.msb')
        assert m43 is not None, (
            'm43_01 entry missing from V3_STARTING_ENCAMPMENT_META')
        assert m43.get('label'), (
            'm43_01 entry missing label field — every starting '
            'encampment should have one')

    def test_loader_resilient_to_missing_file(self, engine, tmp_path,
                                                monkeypatch):
        # The loader should return empty containers if the file is
        # missing — the engine must operate without the catalog.
        # We can't easily delete the real file mid-test, but we can
        # call the loader with a redirected path.
        import os
        def fake_data_path(filename):
            return str(tmp_path / filename)  # tmp_path is empty
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        msb_set, meta, file_meta = engine._load_starting_encampments()
        assert msb_set == frozenset(), (
            'loader should return empty frozenset on missing file')
        assert meta == {}
        assert file_meta == {}

    def test_loader_resilient_to_malformed_json(self, engine, tmp_path,
                                                  monkeypatch):
        # If the file is invalid JSON, loader returns empties
        bad = tmp_path / 'nr_starting_encampments.json'
        bad.write_text('{not valid json')
        def fake_data_path(filename):
            return str(tmp_path / filename)
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        msb_set, meta, file_meta = engine._load_starting_encampments()
        assert msb_set == frozenset(), (
            'loader should return empty frozenset on bad JSON')

    def test_starting_encampment_scope_known_to_picker(self, engine):
        # Structural check: the picker source must mention
        # 'starting_encampment' and V3_STARTING_ENCAMPMENT_MSBS.
        # If a future refactor removes the scope branch, catch it.
        import inspect
        src = inspect.getsource(_engine_shuffler.shuffle_msb_v3)
        assert "'starting_encampment'" in src, (
            "'starting_encampment' scope literal missing from "
            "shuffle_msb_v3 source — scope branch may have been "
            "removed")
        assert 'V3_STARTING_ENCAMPMENT_MSBS' in src, (
            'V3_STARTING_ENCAMPMENT_MSBS reference missing from '
            'shuffle_msb_v3 source — MSB-membership check broken')

    def test_starting_encampment_scope_does_not_match_marker_slot(
            self, engine):
        # When scope='starting_encampment', the picker should NOT also
        # fire on V3_BOSS_TIER_PINNED_SLOTS or variant markers. This is
        # asserted via source-grep — the condition includes
        # `_effective_scope != 'starting_encampment'` on the fall-
        # through branch.
        import inspect
        src = inspect.getsource(_engine_shuffler.shuffle_msb_v3)
        assert "_effective_scope != 'starting_encampment'" in src, (
            "fall-through scope branch isn't excluding "
            "starting_encampment — starting_encampment scope would "
            "ALSO match NB-marker slots, defeating the surgical "
            "intent")

    def test_spoiler_annotation_pattern_in_source(self, engine):
        # The spoiler construction site should reference both
        # V3_STARTING_ENCAMPMENT_MSBS and 'in_starting_encampment'.
        # We grep shuffle_msb_v3 source since that's where entries
        # are built.
        import inspect
        src = inspect.getsource(_engine_shuffler.shuffle_msb_v3)
        assert "'in_starting_encampment'" in src, (
            "'in_starting_encampment' field literal missing from "
            "spoiler-entry construction — annotation feature broken")
        assert 'V3_STARTING_ENCAMPMENT_MSBS' in src, (
            'V3_STARTING_ENCAMPMENT_MSBS not referenced in spoiler '
            'construction — annotation feature broken')


class TestQuadrupedUnsafeSlots:
    """v0.24.31: per-(msb, pi) excludes for quadruped (locomotion=3)
    chr targets. The catalog protects against the seed-924056 freeze
    pattern where Rats and other quadrupeds spawn into biped-on-mesh
    slots that are actually too sparse for quadruped pathfinding."""

    def test_catalog_loaded(self, engine):
        # m45_01 pi=3 is the seed entry — the seed-924056 Rat freeze
        assert hasattr(engine, 'V3_QUADRUPED_UNSAFE_SLOTS')
        assert ('m45_01_00_00.msb', 3) in engine.V3_QUADRUPED_UNSAFE_SLOTS, (
            'm45_01_00_00.msb pi=3 missing from V3_QUADRUPED_UNSAFE_SLOTS '
            '— is data/nr_quadruped_unsafe_slots.json present and valid?')

    def test_catalog_is_frozenset(self, engine):
        assert isinstance(engine.V3_QUADRUPED_UNSAFE_SLOTS, frozenset), (
            'V3_QUADRUPED_UNSAFE_SLOTS should be a frozenset, got '
            f'{type(engine.V3_QUADRUPED_UNSAFE_SLOTS).__name__}')

    def test_catalog_meta_has_entry(self, engine):
        meta = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(
            ('m45_01_00_00.msb', 3))
        assert meta is not None, (
            '(m45_01, pi=3) entry missing from V3_QUADRUPED_UNSAFE_SLOTS_META')
        assert meta.get('first_observed_seed') == 924056, (
            f'(m45_01, pi=3) first_observed_seed mismatch: '
            f'{meta.get("first_observed_seed")}')

    def test_loader_resilient_to_missing_file(self, engine, tmp_path,
                                                monkeypatch):
        def fake_data_path(filename):
            return str(tmp_path / filename)
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        slot_set, meta, file_meta = engine._load_quadruped_unsafe_slots()
        assert slot_set == frozenset()
        assert meta == {}
        assert file_meta == {}

    def test_loader_resilient_to_malformed_json(self, engine, tmp_path,
                                                  monkeypatch):
        bad = tmp_path / 'nr_quadruped_unsafe_slots.json'
        bad.write_text('{not valid json')
        def fake_data_path(filename):
            return str(tmp_path / filename)
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        slot_set, meta, file_meta = engine._load_quadruped_unsafe_slots()
        assert slot_set == frozenset()

    def test_predicate_rejects_quadruped_at_unsafe_slot(self, engine, tags):
        # Pick a known quadruped (loco=3). c4080 Rat is in the loaded tag
        # set and is the seed-924056 frozen chr.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result == 'quadruped_unsafe_slot', (
            f'quadruped gate should reject c4080 at (m45_01, pi=3), '
            f'got {result!r}')

    def test_predicate_allows_biped_at_quadruped_unsafe_slot(self, engine, tags):
        # Same slot but biped target — should pass (not a quadruped concern)
        # c3000 Exile Soldier is loco=0
        if tags.get('c3000', {}).get('locomotion') != 0:
            pytest.skip('c3000 not loco=0 in this tag set')
        result = engine._reject_target_for_slot(
            'c3000', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result is None, (
            f'biped target should pass quadruped gate at unsafe slot, '
            f'got {result!r}')

    def test_predicate_allows_quadruped_at_safe_slot(self, engine, tags):
        # Same Rat but at a different (m45_01, pi=2) NOT in catalog
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=2)
        assert result is None, (
            f'quadruped target should pass at slots not in unsafe '
            f'catalog, got {result!r}')

    def test_legacy_callers_unaffected(self, engine, tags):
        # Predicate called without msb_base/pi (pre-v0.24.31 signature
        # equivalent) must skip the quadruped gate and preserve old
        # behavior. Otherwise we'd break callers that hit the predicate
        # without slot identity.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags)
        assert result is None, (
            f'legacy call without slot identity should skip quadruped '
            f'gate, got {result!r}')

    def test_picker_passes_slot_identity_to_predicate(self, engine):
        # Source-grep: pick_target_cp must pass msb_base and pi to the
        # predicate. Otherwise the gate silently no-ops for picker calls.
        #
        # v0.28.x: the picker body has been extracted to
        # engine.picker.pick_target_cp; the shim in oops_v3 doesn't
        # itself reference the predicate. Grep the engine module.
        import inspect
        from engine import picker
        src = inspect.getsource(picker.pick_target_cp)
        assert 'msb_base=slot_msb_name' in src, (
            'engine.picker.pick_target_cp does not pass msb_base to '
            'reject_target_for_slot — quadruped gate silently no-ops')
        assert 'pi=slot_pi' in src, (
            'engine.picker.pick_target_cp does not pass pi to '
            'reject_target_for_slot — quadruped gate silently no-ops')

    def test_scorer_passes_slot_identity_to_predicate(self, engine):
        # Source-grep: the scorer must pass slot identity to the
        # predicate. Without it, the reservation pre-pass can commit
        # a quadruped at an unsafe slot before runtime can reject
        # (the reservation bypass bug — see v0.24.26 for prior cases
        # of this pattern).
        #
        # v0.28.x: the scorer body has been folded into
        # engine.rejection.score_slot_for_unique. The shim in oops_v3
        # delegates; the actual call to reject_target_for_slot lives
        # in the engine module — that's where we grep.
        import inspect
        from engine import rejection
        src = inspect.getsource(rejection.score_slot_for_unique)
        assert "msb_base=slot_info.get('msb')" in src, (
            'engine.rejection.score_slot_for_unique does not pass '
            'msb to reject_target_for_slot — quadruped gate silently '
            'no-ops at reservation time, same bug shape as v0.24.26')
        assert "pi=slot_info.get('pi')" in src, (
            'engine.rejection.score_slot_for_unique does not pass '
            'pi to reject_target_for_slot — quadruped gate silently '
            'no-ops at reservation time')

    def test_v0_24_32_unverified_reposition_keeps_gate_active(
            self, engine, tags):
        # v0.24.32: a slot with reposition_proposed but playtest_
        # verified=false MUST still reject quadrupeds. Conservative
        # default — hypothesis untested, gate enforces.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        entry = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(
            ('m45_01_00_00.msb', 3))
        assert entry is not None
        repo = entry.get('reposition_proposed')
        assert repo is not None, (
            'm45_01 pi=3 should have reposition_proposed field added in v0.24.32')
        assert repo.get('playtest_verified') is False, (
            'm45_01 pi=3 reposition has playtest_verified=true but the '
            'in-game test has not been recorded. If verified, also remove '
            'this test or update the assertion accordingly.')
        # Verify gate still fires
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result == 'quadruped_unsafe_slot'

    def test_v0_24_32_verified_reposition_releases_gate(
            self, engine, tags, monkeypatch):
        # Simulate a playtest-verified reposition by mutating the meta
        # dict for the test. The gate should then PASS the quadruped.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        key = ('m45_01_00_00.msb', 3)
        original_entry = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(key)
        assert original_entry is not None
        # Copy and flip the verification flag
        import copy
        new_entry = copy.deepcopy(original_entry)
        new_entry.setdefault('reposition_proposed', {})['playtest_verified'] = True
        # Monkeypatch the meta dict with the flipped entry
        new_meta = dict(engine.V3_QUADRUPED_UNSAFE_SLOTS_META)
        new_meta[key] = new_entry
        monkeypatch.setattr(engine, 'V3_QUADRUPED_UNSAFE_SLOTS_META', new_meta)
        # Gate should now release — quadruped allowed
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result is None, (
            f'quadruped should be allowed at verified-safe slot, got {result!r}. '
            'The playtest_verified=true flag should release the gate.')

    def test_v0_24_32_slot_repositions_has_quadruped_safety_entry(self, engine):
        # The reposition data must actually be in slot_repositions.json
        # for the apply pipeline to pick it up. Source-of-truth check.
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__), 'data',
                            'slot_repositions.json')
        with open(path) as f:
            rd = json.load(f)
        m45 = rd.get('proposals', {}).get('m45_01_00_00.msb', {})
        entry = m45.get('3')
        assert entry is not None, (
            'm45_01 pi=3 entry missing from slot_repositions.json. The '
            'v0.24.32 reposition would not be applied by dcx_batch.')
        assert entry.get('status') == 'quadruped_safe_relocation', (
            f'm45_01 pi=3 status mismatch: {entry.get("status")}')
        # Target should match what nr_quadruped_unsafe_slots.json declares
        meta_entry = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(
            ('m45_01_00_00.msb', 3))
        repo = meta_entry.get('reposition_proposed')
        assert entry['to_pos_center'] == repo['to_pos'], (
            f'slot_repositions to_pos_center {entry["to_pos_center"]} '
            f'does not match nr_quadruped_unsafe_slots reposition_proposed '
            f'to_pos {repo["to_pos"]} — sources out of sync')

    # v0.24.33: prophylactic catalog expansion
    # ------------------------------------------------------------------
    # 4 new slots added based on the m45_01 pi=3 hypothesis (sparse navmesh
    # + biped vanilla source = likely quadruped freeze risk):
    #   - m43_01 pi=5, m43_01 pi=6   (wandering_noble_camp)
    #   - m44_01 pi=2                (commoner_settlement)
    #   - m45_01 pi=1                (roadside_thieves_camp, same MSB as pi=3)

    @pytest.mark.parametrize('msb,pi', [
        ('m43_01_00_00.msb', 5),
        ('m43_01_00_00.msb', 6),
        ('m43_02_00_00.msb', 4),
        ('m44_01_00_00.msb', 2),
        ('m45_01_00_00.msb', 1),
    ])
    def test_v0_24_33_prophylactic_slot_in_catalog(self, engine, msb, pi):
        # Each new entry must be in the frozenset AND in the meta dict
        # AND tagged as prophylactic (vs the original empirical m45_01 pi=3).
        assert (msb, pi) in engine.V3_QUADRUPED_UNSAFE_SLOTS, (
            f'({msb}, {pi}) missing from V3_QUADRUPED_UNSAFE_SLOTS — '
            'prophylactic scan entry not loaded')
        meta = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get((msb, pi))
        assert meta is not None
        assert meta.get('discovery_method') == 'prophylactic_density_scan', (
            f'({msb}, {pi}) discovery_method should be '
            f'"prophylactic_density_scan", got {meta.get("discovery_method")!r}')
        assert meta.get('reposition_proposed', {}).get('playtest_verified') is False, (
            f'({msb}, {pi}) prophylactic entries must default to '
            'playtest_verified=false until in-game confirmation')

    @pytest.mark.parametrize('msb,pi', [
        ('m43_01_00_00.msb', 5),
        ('m43_01_00_00.msb', 6),
        ('m43_02_00_00.msb', 4),
        ('m44_01_00_00.msb', 2),
        ('m45_01_00_00.msb', 1),
    ])
    def test_v0_24_33_prophylactic_slot_has_reposition(self, engine, msb, pi):
        # Each prophylactic entry must have a corresponding
        # quadruped_safe_relocation in slot_repositions.json, sources synced.
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__), 'data',
                            'slot_repositions.json')
        with open(path) as f:
            rd = json.load(f)
        sr_entry = rd['proposals'].get(msb, {}).get(str(pi))
        assert sr_entry is not None, (
            f'{msb} pi={pi} missing from slot_repositions.json — '
            'v0.24.33 prophylactic reposition not registered')
        assert sr_entry.get('status') == 'quadruped_safe_relocation', (
            f'{msb} pi={pi} status mismatch: {sr_entry.get("status")} '
            '(expected quadruped_safe_relocation)')
        # to_pos must match the catalog's reposition_proposed.to_pos
        catalog = engine.V3_QUADRUPED_UNSAFE_SLOTS_META[(msb, pi)]
        repo = catalog['reposition_proposed']
        assert sr_entry['to_pos_center'] == repo['to_pos'], (
            f'{msb} pi={pi}: slot_repositions to_pos_center '
            f'{sr_entry["to_pos_center"]} != catalog to_pos {repo["to_pos"]} '
            '— sources out of sync')

    def test_v0_24_33_catalog_distinguishes_discovery_methods(self, engine):
        # The catalog should now have at least 1 empirical and 4+ prophylactic
        empirical = [s for s in engine.V3_QUADRUPED_UNSAFE_SLOTS_META.values()
                     if s.get('discovery_method') == 'empirical_freeze_observation']
        prophylactic = [s for s in engine.V3_QUADRUPED_UNSAFE_SLOTS_META.values()
                        if s.get('discovery_method') == 'prophylactic_density_scan']
        assert len(empirical) >= 1, (
            f'Should have at least 1 empirical entry, got {len(empirical)}. '
            'Did the original m45_01 pi=3 lose its discovery_method tag?')
        assert len(prophylactic) >= 5, (
            f'Should have at least 4 prophylactic entries (added v0.24.33), '
            f'got {len(prophylactic)}.')

    def test_v0_24_33_prophylactic_gate_still_blocks_quadrupeds(
            self, engine, tags):
        # Confirm that prophylactic slots gate quadrupeds with
        # playtest_verified=false (same as empirical entries).
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3')
        # Try a Rat at m43_01 pi=5 (prophylactic). Should reject.
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m43_01_00_00.msb', pi=5)
        assert result == 'quadruped_unsafe_slot', (
            f'Rat at prophylactic slot m43_01 pi=5 should be rejected, '
            f'got {result!r}')


class TestScriptSpawnBossCatalog:
    """v0.24.37: catalogs the 4 script_spawn boss slots whose 'missing boss'
    reports are EMEVD chain issues rather than picker issues."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_catalog_loads_and_has_4_entries(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_script_spawn_boss_slots.json')
        assert os.path.isfile(path)
        with open(path) as f:
            d = json.load(f)
        slots = d['script_spawn_boss_slots']
        assert len(slots) >= 4, (
            f'Expected at least 4 script_spawn boss slots (m46_64/65/90/91), '
            f'got {len(slots)}.')
        # m46_91 is the user-reported one
        msbs = {s['msb'] for s in slots}
        assert 'm46_91_00_00.msb' in msbs, (
            'm46_91 (Grafted Scion Castle) missing from script_spawn '
            'catalog — was the user-flagged case from seed 271328')

    def test_all_catalogued_slots_have_script_spawn_source(self, engine):
        """Sanity check: catalogued slots' cp _source should be script_spawn."""
        import io, json, os
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            _, tags = engine.load_data()
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_script_spawn_boss_slots.json')
        with open(path) as f:
            d = json.load(f)
        # v0.26.x: catalogued chrs are now _source='nr_placed' after the
        # byte-level MSB audit found them in vanilla MSBs (UTF-16-LE
        # references the original catalog parser missed). Arena gating
        # moved to V3_DEDICATED_ARENA_BOSS_CHRS membership; the catalog
        # remains as documentation of the historical script_spawn arena
        # slot mapping.
        for entry in d['script_spawn_boss_slots']:
            cp = entry['cp']
            src = tags.get(cp, {}).get('_source')
            assert src == 'nr_placed', (
                f'{cp} catalogued as dedicated-arena boss but tags say '
                f'_source={src!r}. Expected nr_placed after v0.26.x '
                f'reclassification.')
            assert cp in engine.V3_DEDICATED_ARENA_BOSS_CHRS or cp in ('c4690','c4670','c7910'), (
                f'{cp} catalogued as dedicated-arena boss but is NOT in '
                f'V3_DEDICATED_ARENA_BOSS_CHRS — arena gating would not '
                f'fire. (c4690 Grafted Scion deliberately excluded; see '
                f'V3_DEDICATED_ARENA_BOSS_CHRS comment.)')


class TestStackingDetectorCrossCollision:
    """v0.24.37: distribute_stacked_repositions Pass 2 catches collisions
    between repositioned slots and non-repositioned slots in the same MSB.
    The flagship case is m45_01 pi=5 (repositioned from origin sentinel to
    (2.55, 1.98, 5.779)) which collided with m45_01 pi=2 (vanilla position
    (2.55, 1.98, 5.78), not in slot_repositions)."""

    def test_m45_01_pi5_nudged_away_from_pi2(self):
        """The m45_01 pi=5 entry must NOT have its to_pos_center at pi=2's
        vanilla position."""
        import json, os, math
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo_root, 'data/slot_repositions.json')) as f:
            rd = json.load(f)
        entry = rd['proposals']['m45_01_00_00.msb'].get('5')
        assert entry is not None
        tp = entry['to_pos_center']
        pi2_vanilla = (2.55, 1.98, 5.78)
        d_xz = math.hypot(tp[0]-pi2_vanilla[0], tp[2]-pi2_vanilla[2])
        assert d_xz >= 1.5, (
            f'm45_01 pi=5 to_pos_center {tp} is {d_xz:.3f}m from pi=2 vanilla '
            f'position {pi2_vanilla}. The v0.24.37 fix should have nudged '
            f'it away. Cross-collision pass either didn\'t run or didn\'t '
            f'persist.')

    def test_nr_all_part_positions_data_present(self):
        import json, os
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo_root, 'data/nr_all_part_positions.json')
        assert os.path.isfile(path), (
            'data/nr_all_part_positions.json missing — generated by '
            'dev/build_part_positions.py. Needed by the cross-collision '
            'detection pass.')
        with open(path) as f:
            d = json.load(f)
        # Should have a reasonable number of positions
        assert d['_meta']['n_slots'] >= 1000, (
            f'Expected >= 1000 part positions in catalog, got '
            f'{d["_meta"]["n_slots"]}.')
        # Specifically check m45_01 pi=2 is there with the right position
        m45 = d['positions'].get('m45_01_00_00.msb', {})
        pi2 = m45.get('2')
        assert pi2 is not None
        assert abs(pi2[0] - 2.55) < 0.05 and abs(pi2[2] - 5.78) < 0.05


class TestScriptSpawnSpawnPoolCrossRef:
    """v0.24.38: ensure that every entry in nr_script_spawn_boss_slots.json
    is also in V3_SPAWN_POOL_MSBS (and vice-versa for script_spawn-cp entries).

    Catches drift where one catalog is updated but the other isn't. The
    architectural picture (script_spawn chrs go through spawn-pool runtime
    pull) only works if these two catalogs agree."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_every_script_spawn_slot_is_in_spawn_pool(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_script_spawn_boss_slots.json')
        with open(path) as f:
            d = json.load(f)
        for entry in d['script_spawn_boss_slots']:
            msb = entry['msb']
            msb_base = msb.replace('.msb', '')
            assert msb_base in engine.V3_SPAWN_POOL_MSBS, (
                f'{msb} is in nr_script_spawn_boss_slots.json but NOT in '
                f'V3_SPAWN_POOL_MSBS. Either the entry is wrong (slot is not '
                f'spawn-pool-related) or V3_SPAWN_POOL_MSBS is missing it.')
            assert entry.get('in_v3_spawn_pool_msbs') is True, (
                f'{msb} has in_v3_spawn_pool_msbs={entry.get("in_v3_spawn_pool_msbs")!r}; '
                'should be True since the MSB IS in V3_SPAWN_POOL_MSBS.')

    def test_spawn_pool_label_no_longer_says_putrid_avatar(self, engine):
        """v0.24.38 fixed the c4690 label inconsistency. 'Putrid Avatar'
        was a stale ER name; NR roster says 'Grafted Scion'."""
        for msb_base, desc in engine.V3_SPAWN_POOL_MSBS.items():
            assert 'Putrid Avatar' not in desc, (
                f'V3_SPAWN_POOL_MSBS[{msb_base!r}] still says "Putrid Avatar". '
                f'Fixed in v0.24.38 — should be "Grafted Scion".')

    def test_script_spawn_label_includes_marker(self, engine):
        """v0.24.38: script_spawn entries in V3_SPAWN_POOL_MSBS now include
        an explicit 'script_spawn' marker in the label, so the special
        handling is visible at a glance."""
        for msb_base in ['m46_64_00_00', 'm46_65_00_00',
                          'm46_90_00_00', 'm46_91_00_00']:
            desc = engine.V3_SPAWN_POOL_MSBS.get(msb_base, '')
            assert 'script_spawn' in desc, (
                f'V3_SPAWN_POOL_MSBS[{msb_base!r}] = {desc!r}; should include '
                f'"script_spawn" marker (v0.24.38 convention).')


class TestSpawnPoolRotationSourceExemption:
    """v0.24.97: the V3_TARGET_ONLY_SOURCES filter in the swap loop now
    exempts V3_SPAWN_POOL_MSBS pi=1.

    Pre-v0.24.97, c4670 Ancestor Spirit and c4690 Grafted Scion (both
    `_source: script_spawn`) at m46_64/65/90/91 pi=1 were skipped by the
    swap loop, leaving those four rotation entries vanilla every seed.
    The user-visible symptom was Grafted Scion / Ancestor Spirit
    appearing deterministically across all seeds at whichever live
    arena rolled those pool entries.

    The narrow exemption brings these four slots onto the same swap
    path as the 19 sibling non-script_spawn rotation entries (m46_52
    c3250 Draconic Tree Sentinel, etc.) which have been swapping pi=1
    successfully without issue. See the TODO(broad-fix) at the swap-
    loop call site for the broader cleanup that would also unlock
    c7700-c7920 at their legacy DS-import arena MSBs."""

    def test_predicate_recognises_every_spawn_pool_msb_at_pi_1(self, engine):
        """All 23 V3_SPAWN_POOL_MSBS entries should be recognised as
        rotation sources at pi=1."""
        for pool_base in engine.V3_SPAWN_POOL_MSBS:
            assert engine._is_spawn_pool_rotation_source(pool_base + '.msb', 1), (
                f'_is_spawn_pool_rotation_source({pool_base + ".msb"!r}, 1) '
                f'should be True — {pool_base} is in V3_SPAWN_POOL_MSBS.')
            # And without the .msb suffix
            assert engine._is_spawn_pool_rotation_source(pool_base, 1), (
                f'_is_spawn_pool_rotation_source({pool_base!r}, 1) '
                f'should be True (bare basename form).')

    def test_predicate_rejects_non_pi_1_indices(self, engine):
        """pi=0 (c1000 placeholder) and pi=2 (AEG asset) should NOT be
        treated as rotation sources, even though the MSB is in the pool."""
        for pi in (0, 2, 3, 5, 99):
            assert not engine._is_spawn_pool_rotation_source('m46_65_00_00.msb', pi), (
                f'_is_spawn_pool_rotation_source(m46_65_00_00.msb, {pi}) '
                f'should be False — only pi=1 is the rotation slot.')

    def test_predicate_rejects_non_spawn_pool_msbs(self, engine):
        """MSBs outside V3_SPAWN_POOL_MSBS should never match, regardless
        of pi. Sanity check that the predicate isn't accidentally too
        permissive."""
        for msb in ('m32_00_00_00.msb', 'm46_00_00_00.msb',
                    'm49_43_00_00.msb', 'm60_43_36_50.msb'):
            for pi in (0, 1, 2):
                assert not engine._is_spawn_pool_rotation_source(msb, pi), (
                    f'_is_spawn_pool_rotation_source({msb!r}, {pi}) '
                    f'should be False — {msb} is not in V3_SPAWN_POOL_MSBS.')

    def test_script_spawn_chrs_still_tagged(self, engine, tags):
        """v0.26.x: c4670 + c4690 are reclassified to _source='nr_placed'
        (they ARE in vanilla MSBs — m46_64/65/90/91 — as confirmed by
        the byte-level UTF-16-LE audit). The original "still tagged
        script_spawn" assertion no longer applies. The arena-only
        constraint is now carried by V3_DEDICATED_ARENA_BOSS_CHRS
        membership (for c4670; c4690 Grafted Scion deliberately
        excluded — see V3_DEDICATED_ARENA_BOSS_CHRS comment), and
        the V3_TARGET_ONLY_SOURCES filter no longer applies to these
        chrs at non-spawn-pool slots (it was a side-effect of the
        misclassification, not an intended gate).

        This test now guards against re-introducing the misclassification
        — both should remain nr_placed.
        """
        for cp in ('c4670', 'c4690'):
            assert tags.get(cp, {}).get('_source') == 'nr_placed', (
                f'{cp} should be _source=nr_placed after v0.26.x '
                f'reclassification (byte-level MSB audit confirmed '
                f'vanilla MSB placements). If you see script_spawn '
                f'here, the reclassification regressed.')

    def test_four_script_spawn_rotation_slots_are_now_exempt(self, engine):
        """The four specific slots that were causing the user-visible
        symptom (Grafted Scion / Ancestor Spirit every seed) should all
        be exempt under the new predicate."""
        for msb_base in ('m46_64_00_00', 'm46_65_00_00',
                          'm46_90_00_00', 'm46_91_00_00'):
            assert engine._is_spawn_pool_rotation_source(msb_base + '.msb', 1), (
                f'{msb_base}.msb pi=1 should be exempt from the '
                f'script_spawn target-only filter (this is the whole point '
                f'of v0.24.97).')


class TestFlyingRequiredSlots:
    """v0.24.45: slots with flying-anim vanilla chrs must keep aerial-anim
    targets. Asset-bundle and anim-bank mismatch causes CTD on cell-load.

    Discovered via seed 552688: m60_43_36_50 pi=23 (vanilla c4500 Flying
    Dragon at Y=106) → picker rolled c4620 Astel (giga_boss, ground) →
    CTD walking out castle front door (cell-load of m60_43_36_50)."""





    def test_flying_dragon_accepted_at_flying_slot(self, engine):
        """A flying chr should pass the flying-required filter."""
        roster, tags = engine.load_data()
        reason = engine._reject_target_for_slot(
            target_cp='c4500', src_cp='c4500',
            src_variant_name='Flying Dragon',
            tags=tags,
            msb_base='m60_43_36_50.msb', pi=23)
        # Filter shouldn't trip; other gates may or may not reject for
        # other reasons (we don't assert reason is None — just not flying)
        assert reason != 'flying_required_slot'

    def test_non_flying_slot_not_affected(self, engine):
        """A non-flying-required slot doesn't trigger this filter even
        for non-flying targets."""
        roster, tags = engine.load_data()
        # m43_01 pi=11 is a starting-encampment slot, not flying
        reason = engine._reject_target_for_slot(
            target_cp='c4090',  # Giant Rat - quadruped, not flying
            src_cp='c4080',     # Rat
            src_variant_name='Rat',
            tags=tags,
            msb_base='m43_01_00_00.msb', pi=11)
        assert reason != 'flying_required_slot', (
            'Filter triggered at a non-flying-required slot — wrongly broad')


class TestGuardianGolemPoolLooseningsV0_24_75:
    """v0.24.75 makes two changes to Guardian Golem source-slot handling
    + restricts merchant pool to vanilla NR.

    1. m30_30 pi=45 (Fort Guardian Golem) LIFTED from V3_PROBLEM_SLOTS —
       proven resilient per user playtest (Centipede Demon worked there).

    2. m38_00 pi=51 (Cathedral Guardian Golem) STAYS in V3_PROBLEM_SLOTS
       but loosened via new V3_PROBLEM_SLOT_EXTRA_ALLOWS mechanism that
       whitelists big dragons to bypass SAFE_CONFIRMED filter.

    3. V3_MERCHANT_MODEL_POOL restricted to vanilla NR — heritage/MMV/
       post_dlc entries commented out until MMV-asset-deploy reliability
       is nailed down (seed 454841 v0.24.74 mid-Day-2 CTD).
    """

    def test_m30_30_fort_gg_lifted(self, engine):
        """v0.24.75 lifted Fort GG; v0.24.77 RESTORED it after the c4810
        Erdtree Avatar emerge-anim CTD in seed 886942. Test renamed
        intent: keep the v0.24.75 spec assertion but invert the
        assertion. The TestFortGuardianGolemRestoredV0_24_77 class
        covers the v0.24.77 restoration in detail."""
        # v0.24.77: back in V3_PROBLEM_SLOTS — see that class's tests.
        assert ('m30_30_00_00.msb', 45) in engine.V3_PROBLEM_SLOTS

    def test_m38_00_cathedral_gg_still_fragile(self, engine):
        """Cathedral Guardian Golem source slot remains in V3_PROBLEM_SLOTS
        (the fragility is still real; just loosened via EXTRA_ALLOWS)."""
        assert ('m38_00_00_00.msb', 51) in engine.V3_PROBLEM_SLOTS

    def test_problem_slot_extra_allows_exists(self, engine):
        """v0.24.75 adds V3_PROBLEM_SLOT_EXTRA_ALLOWS mechanism."""
        assert hasattr(engine, 'V3_PROBLEM_SLOT_EXTRA_ALLOWS')
        assert isinstance(engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS, dict)

    def test_cathedral_dragons_whitelisted(self, engine):
        """Cathedral pi=51 should whitelist the big-dragon family via
        EXTRA_ALLOWS. With v0.24.75 removing anim_class restrictions
        globally, both grounded (Magma Wyrm) and flying (Great Wyrm,
        Lichdragon) dragons are geometrically eligible."""
        allows = engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
            ('m38_00_00_00.msb', 51))
        assert allows is not None
        assert 'c4910' in allows  # Magma Wyrm
        assert 'c4911' in allows  # Great Wyrm Theodorix
        assert 'c4540' in allows  # Lichdragon

    def test_cathedral_big_wyrm_passes_fragile_filter(self, engine, tags):
        """c4910 Magma Wyrm at m38_00 pi=51 should NOT be rejected
        by the fragile filter post-v0.24.75 — EXTRA_ALLOWS bypasses
        the SAFE_CONFIRMED requirement, AND anim_class drift gate
        no longer blocks quadruped_large at giga_boss source."""
        assert 'c4910' not in engine.V3_FRAGILE_SAFE_CONFIRMED, (
            'c4910 expected to be NOT in V3_FRAGILE_SAFE_CONFIRMED. '
            'If you added it there, this EXTRA_ALLOWS test is meaningless.')

        slot_info = {
            'msb': 'm38_00_00_00.msb',
            'pi': 51,
            'source_cp': 'c4660',
            'source_npc': 46600030,
            'source_variant_name': 'Guardian Golem (Cathedral)',
            'position': [0.0, 0.0, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, 'c4910', tags)
        assert score is not None, (
            'c4910 Magma Wyrm should be allowed at m38_00 pi=51 via '
            'EXTRA_ALLOWS, but _score_slot_for_unique rejected it.')

    def test_anim_class_drift_gate_removed(self, engine, tags):
        """v0.24.75: xxl_giga_anim_drift removed from _reject_target_for_slot.
        c4910 quadruped_large at c4660 giga_boss source should pass
        the gate (the v0.24.68 gate is gone)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4910', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51,
        )
        assert reason != 'xxl_giga_anim_drift', (
            f'Expected anim_class drift gate to be removed, got: {reason}')

    def test_size_drift_gate_still_active(self, engine, tags):
        """v0.24.75: size restrictions retained. c4040 Slug (size M) at
        c4660 (GIGA) should still reject as xxl_giga_size_drift."""
        reason = engine._reject_target_for_slot(
            target_cp='c4040', src_cp='c4660',
            src_variant_name='Guardian Golem',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51,
        )
        assert reason == 'xxl_giga_size_drift', (
            f'Expected size_drift gate to still fire for M target at '
            f'GIGA source, got: {reason}')


    def test_swap_compat_anim_class_helper_removed(self):
        """v0.24.75 neutered `swap_compat._compat_anim_class` to always
        return True (user directive removing anim_class restrictions).
        v0.26.x: function fully removed — the helper had no remaining
        callers after the neutering, and a constant-true function adds
        nothing. Lock in that it stays absent so a future refactor
        doesn't accidentally restore anim_class gating without an
        explicit user-policy review.
        """
        import swap_compat
        assert not hasattr(swap_compat, '_compat_anim_class'), (
            "swap_compat._compat_anim_class was removed in v0.26.x "
            "after being a no-op since v0.24.75. If you're re-adding it, "
            "first reconcile with the v0.24.75 user directive that "
            "anim_class CTD theories were misattributed.")

    def test_cathedral_non_sensitive_chr_now_allowed(self, engine, tags):
        """v0.27.0: fragile filter flipped to blacklist. A chr that is
        NOT in V3_FRAGILE_SENSITIVE_TARGETS and not in this slot's
        EXTRA_BANS is now accepted at a Cathedral fragile slot — the old
        SAFE_CONFIRMED whitelist requirement was archived.

        Companion to test_cathedral_sensitive_chr_still_rejected below.
        """
        slot_info = {
            'msb': 'm38_00_00_00.msb',
            'pi': 51,
            'source_cp': 'c4660',
            'source_npc': 46600030,
            'source_variant_name': 'Guardian Golem (Cathedral)',
            'position': [0.0, 0.0, 0.0],
        }
        extra_bans = engine.V3_PROBLEM_SLOT_EXTRA_BANS.get(
            ('m38_00_00_00.msb', 51), set())
        # Pick an M-humanoid chr that is neither SENSITIVE nor banned at
        # this slot — pre-flip this was rejected for not being whitelisted.
        candidate = None
        for cp, t in tags.items():
            if cp in engine.V3_FRAGILE_SENSITIVE_TARGETS or cp in extra_bans:
                continue
            if cp.startswith('c52') or cp.startswith('c6'):
                continue
            # v0.27.28: anim_class expunged. "humanoid" ≈ an M-size chr that is
            # not fragile-locomotion and not loco=3 (i.e. won't trip the Gate 4
            # quadruped/fragile filter), so the only thing under test is the
            # v0.27.0 fragile-blacklist flip.
            if (t.get('size_class') == 'M'
                    and not t.get('fragile_locomotion')
                    and t.get('locomotion') != 3):
                candidate = cp
                break
        assert candidate is not None, 'fixture: no suitable M-humanoid chr'
        score = engine._score_slot_for_unique(slot_info, candidate, tags)
        assert score is not None, (
            f'{candidate} (not SENSITIVE, not EXTRA_BANned) should now be '
            f'accepted at the Cathedral fragile slot post-v0.27.0 flip')

    def test_cathedral_sensitive_chr_still_rejected(self, engine, tags):
        """v0.27.0: the SENSITIVE blacklist still rejects at fragile
        slots — the flip widened the pool, it did not remove the guard."""
        slot_info = {
            'msb': 'm38_00_00_00.msb',
            'pi': 51,
            'source_cp': 'c4660',
            'source_npc': 46600030,
            'source_variant_name': 'Guardian Golem (Cathedral)',
            'position': [0.0, 0.0, 0.0],
        }
        sens = sorted(engine.V3_FRAGILE_SENSITIVE_TARGETS)
        assert sens, 'V3_FRAGILE_SENSITIVE_TARGETS unexpectedly empty'
        score = engine._score_slot_for_unique(slot_info, sens[0], tags)
        assert score is None, (
            f'{sens[0]} (SENSITIVE) must still be rejected at the '
            f'Cathedral fragile slot')

    def test_merchant_pool_vanilla_restricted(self, engine):
        """v0.24.75 RESTRICTED: merchant pool should exclude all
        non-vanilla NR chrs (heritage, post_dlc_dump, mmv_import)
        until MMV asset-deploy reliability is nailed down."""
        DISABLED_NON_VANILLA = {
            # Heritage
            'c3800', 'c3510', 'c3070', 'c3750', 'c3860', 'c4385', 'c4820',
            # Scholar Remembrance manual tags
            'c4352',
            # post_dlc_dump
            'c5081', 'c5320', 'c5651', 'c7720',
            # MMV imports
            'c1310', 'c2030', 'c4720', 'c4721', 'c5030', 'c5130', 'c5300',
            'c5740', 'c5840', 'c5880', 'c6200', 'c6210', 'c8300',
        }
        leaked = DISABLED_NON_VANILLA & engine.V3_MERCHANT_MODEL_POOL
        assert not leaked, (
            f'Non-vanilla merchant pool entries leaked: {sorted(leaked)}. '
            'These were disabled v0.24.75 pending MMV asset-deploy '
            'reliability fix. Should be commented out in '
            'V3_MERCHANT_MODEL_POOL.')

    def test_merchant_pool_keeps_vanilla(self, engine):
        """Sanity: vanilla NR chrs should still be in the merchant pool."""
        # Should be there — pre-v0.23.74 baseline merchant pool entries
        for cp in ('c3010', 'c4290', 'c4351', 'c4313', 'c2140', 'c2500',
                   'c3100', 'c4570', 'c5070'):
            assert cp in engine.V3_MERCHANT_MODEL_POOL, (
                f'{cp} (vanilla NR merchant pool member) missing — '
                'v0.24.75 restriction was too aggressive.')


class TestFortGuardianGolemRestoredV0_24_77:
    """v0.24.77: m30_30 pi=45 (Fort GG) re-added to V3_PROBLEM_SLOTS
    after seed 886942 CTD (c4810 Erdtree Avatar emerge-anim failure
    on Fort rampart geometry).

    Same three-layer config as Cathedral pi=51:
    - V3_PROBLEM_SLOTS: SAFE-only base filter
    - V3_PROBLEM_SLOT_EXTRA_ALLOWS: whitelist big-creature variety
      (Centipede Demon, Gaping Dragon, big dragons)
    - V3_PROBLEM_SLOT_EXTRA_BANS: ban known-broken emerge-anim chrs
      (c4810 Erdtree Avatar, c4811 variant, c4441 Land Squirt)
    """

    def test_fort_back_in_problem_slots(self, engine):
        """Fort GG slot is in V3_PROBLEM_SLOTS again post-v0.24.77."""
        assert ('m30_30_00_00.msb', 45) in engine.V3_PROBLEM_SLOTS

    def test_fort_emerge_anim_banned(self, engine):
        """The 3 known emerge-anim chrs are in EXTRA_BANS for Fort slot."""
        bans = engine.V3_PROBLEM_SLOT_EXTRA_BANS.get(
            ('m30_30_00_00.msb', 45))
        assert bans is not None, 'Fort slot missing EXTRA_BANS entry'
        assert 'c4810' in bans  # Erdtree Avatar Remembrance (the CTD chr)
        assert 'c4811' in bans  # Erdtree Avatar Variant (defensive)
        assert 'c4441' in bans  # Land Squirt (original v0.24.18 case)

    def test_fort_extra_allows_preserves_centipede_demon(self, engine):
        """User-confirmed working chrs are in EXTRA_ALLOWS for Fort."""
        allows = engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
            ('m30_30_00_00.msb', 45))
        assert allows is not None
        assert 'c7710' in allows  # Centipede Demon (user-confirmed)
        assert 'c7700' in allows  # Gaping Dragon (sibling giga_boss)
        assert 'c4241' in allows  # Giant Fingercreeper

    def test_c4810_rejected_at_fort(self, engine, tags):
        """The seed 886942 CTD chr (c4810 Erdtree Avatar) must be
        rejected at the Fort slot via EXTRA_BANS — that's the fix."""
        slot_info = {
            'msb': 'm30_30_00_00.msb', 'pi': 45,
            'source_cp': 'c4660',
            'source_npc': 0,
            'source_variant_name': 'Guardian Golem (Fort)',
            'cluster_id': None,
            'position': [0.0, 42.8, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, 'c4810', tags)
        assert score is None, (
            f'c4810 Erdtree Avatar should be rejected at Fort slot '
            f'via EXTRA_BANS (seed 886942 CTD chr), got score={score}')

    def test_c7710_allowed_at_fort(self, engine, tags):
        """Centipede Demon must still land at Fort slot — the
        user-confirmed working case that motivated the v0.24.75 lift."""
        slot_info = {
            'msb': 'm30_30_00_00.msb', 'pi': 45,
            'source_cp': 'c4660',
            'source_npc': 0,
            'source_variant_name': 'Guardian Golem (Fort)',
            'cluster_id': None,
            'position': [0.0, 42.8, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, 'c7710', tags)
        assert score is not None, (
            f'c7710 Centipede Demon should be allowed at Fort slot '
            f'via EXTRA_ALLOWS (user-confirmed working), got None')
