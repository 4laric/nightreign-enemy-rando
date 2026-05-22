"""Unit tests for variant-filter functions in oops_v3.

These functions take variant lists and return filtered subsets. They
read module globals (V3_AVOID_VARIANT_NPC_IDS) but don't mutate them
— safe to test against live module state. Tests use monkeypatch when
a global needs to be temporarily overridden.

The c6200 Gael/Scarab case for _filter_primary_identity is the canonical
bug the function was written to fix: c6200 ships with both Gael and
Scarab variants multiplexed via modelDispMask, so picking a Scarab
variant produces Gael's head + beard with no body. The filter prefers
variants whose name matches the c-prefix's primary identity.
"""
import pytest

import oops_v3


# ---------------------------------------------------------------------------
# _filter_avoid_npc — hard filter against V3_AVOID_VARIANT_NPC_IDS
# ---------------------------------------------------------------------------

class TestFilterAvoidNpc:
    """Hard filter (as of v0.23.25): if filtering would empty the list,
    returns empty. Caller is expected to handle the empty case by falling
    back to vanilla preserve (None return path in pick_variant_for_tier).
    """

    def test_removes_avoid_listed_npc_ids(self, monkeypatch):
        # Use synthetic ids to avoid coupling tests to the live avoid list
        monkeypatch.setattr(oops_v3, 'V3_AVOID_VARIANT_NPC_IDS', {1001, 1002})
        vs = [
            {'npc_param_id': 1001, 'variant_name': 'avoid'},
            {'npc_param_id': 9999, 'variant_name': 'keep'},
            {'npc_param_id': 1002, 'variant_name': 'avoid'},
        ]
        out = oops_v3._filter_avoid_npc(vs)
        assert len(out) == 1
        assert out[0]['variant_name'] == 'keep'

    def test_hard_filter_returns_empty_when_all_avoided(self, monkeypatch):
        # The v0.23.25 change: fail closed rather than fall back to the
        # original list. Caller handles emptiness — the c3670 case in
        # the docstring is what this protects against.
        monkeypatch.setattr(oops_v3, 'V3_AVOID_VARIANT_NPC_IDS', {1001, 1002})
        vs = [
            {'npc_param_id': 1001, 'variant_name': 'avoid'},
            {'npc_param_id': 1002, 'variant_name': 'avoid'},
        ]
        assert oops_v3._filter_avoid_npc(vs) == []

    def test_empty_input_passes_through(self):
        # Guard clause at top of function — no filtering happens on empty.
        assert oops_v3._filter_avoid_npc([]) == []

    def test_live_avoid_list_filters_known_margit_variant(self, engine):
        # Sanity: against the real V3_AVOID_VARIANT_NPC_IDS, a known
        # avoid-listed variant (Margit 20109000) gets filtered.
        vs = [
            {'npc_param_id': 20109000, 'variant_name': 'Margit (cinematic)'},
            {'npc_param_id': 99999999, 'variant_name': 'unrelated'},
        ]
        out = oops_v3._filter_avoid_npc(vs)
        assert len(out) == 1
        assert out[0]['npc_param_id'] == 99999999


# ---------------------------------------------------------------------------
# _filter_primary_identity — soft filter preferring tag.name matches
# ---------------------------------------------------------------------------

class TestFilterPrimaryIdentity:
    """Soft filter: tries to keep variants whose variant_name matches the
    c-prefix's primary creature identity (from tag.name). Falls back to
    the original list if filtering would empty it.

    Documented edge cases the function handles:
      - Dual-name chrs split on ' / ' (Beast Clergyman / Maliketh)
      - Parenthetical qualifiers stripped from tag.name before matching
      - Words >= 5 chars added as alternative match keys
      - Trailing/leading punctuation stripped from words for matching
      - Empty/None tag passes through unchanged
    """

    def test_c6200_gael_scarab_trap(self):
        # The canonical case from the docstring: c6200's chrbnd contains
        # both Gael and arena Scarabs. Picking a Scarab variant at a
        # c6200 placement produces Gael's floating head/beard. The filter
        # prefers Gael-named variants.
        tag = {'name': 'Slave Knight Gael'}
        variants = [
            {'variant_name': 'Slave Knight Gael (Boss)'},
            {'variant_name': 'Slave Knight Gael (Phase 2)'},
            {'variant_name': 'Scarab (cinematic)'},
            {'variant_name': 'Scarab (mask variant)'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        names = [v['variant_name'] for v in out]
        assert all('Gael' in n for n in names)
        assert len(out) == 2

    def test_dual_name_chr_matches_both_pieces(self):
        # 'Beast Clergyman / Maliketh' should match variants named after
        # EITHER form — they're the same creature, two names.
        tag = {'name': 'Beast Clergyman / Maliketh'}
        variants = [
            {'variant_name': 'Beast Clergyman (Boss)'},
            {'variant_name': 'Maliketh, the Black Blade'},
            {'variant_name': 'Some Other Boss'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        names = [v['variant_name'] for v in out]
        assert 'Beast Clergyman (Boss)' in names
        assert 'Maliketh, the Black Blade' in names
        assert 'Some Other Boss' not in names

    def test_parenthetical_qualifier_stripped_from_tag_name(self):
        # 'Mohg (Saw)' → 'Mohg' for matching, so variants named 'Mohg' or
        # 'Mohg the Omen' should match.
        tag = {'name': 'Mohg (Saw)'}
        variants = [
            {'variant_name': 'Mohg the Omen'},
            {'variant_name': 'Unrelated Boss'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        assert len(out) == 1
        assert out[0]['variant_name'] == 'Mohg the Omen'

    def test_long_word_used_as_alternative_key(self):
        # 'Lichdragon Fortissax' should match a variant named just
        # 'Fortissax (NB2)' because 'Fortissax' is >= 5 chars and gets
        # added as a key.
        tag = {'name': 'Lichdragon Fortissax'}
        variants = [
            {'variant_name': 'Fortissax (NB2)'},
            {'variant_name': 'Bear'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        assert len(out) == 1
        assert out[0]['variant_name'] == 'Fortissax (NB2)'

    def test_short_word_not_used_as_key(self):
        # Words < 5 chars (Gael, Wolf, Fire) don't become alternative
        # keys — too generic, would match unrelated variants. Tag with
        # short-word-only identity falls back via the full piece.
        # Tag 'Gael' is 4 chars; the full piece 'gael' is still a key
        # (the < 5 cutoff is for word-level keys, not piece-level).
        tag = {'name': 'Gael'}
        variants = [
            {'variant_name': 'Slave Knight Gael'},  # matches 'gael' as substring
            {'variant_name': 'Bear'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        assert len(out) == 1
        assert 'Gael' in out[0]['variant_name']

    def test_trailing_punctuation_stripped_from_word_keys(self):
        # 'Romina, Saint of the Bud' → word 'romina' (comma stripped)
        # matches 'Romina (Field Boss)'. From the docstring.
        tag = {'name': 'Romina, Saint of the Bud'}
        variants = [
            {'variant_name': 'Romina (Field Boss)'},
            {'variant_name': 'Other'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        assert len(out) == 1
        assert 'Romina' in out[0]['variant_name']

    def test_empty_filter_result_falls_back_to_original(self):
        # Soft filter: if no variants match the identity keys, return
        # the original list rather than nothing. Failure mode = no extra
        # filtering, not unexpectedly empty pool.
        tag = {'name': 'Some Boss'}
        variants = [
            {'variant_name': 'Unrelated A'},
            {'variant_name': 'Unrelated B'},
        ]
        out = oops_v3._filter_primary_identity(variants, tag)
        assert out == variants

    def test_none_tag_passes_through(self):
        variants = [{'variant_name': 'whatever'}]
        assert oops_v3._filter_primary_identity(variants, None) == variants

    def test_tag_without_name_passes_through(self):
        variants = [{'variant_name': 'whatever'}]
        assert oops_v3._filter_primary_identity(variants, {}) == variants
        assert oops_v3._filter_primary_identity(variants, {'name': ''}) == variants
        assert oops_v3._filter_primary_identity(variants, {'name': '   '}) == variants

    def test_parenthetical_only_name_passes_through(self):
        # Edge case: tag.name is '(Boss)' — after stripping the
        # parenthetical, nothing's left. Should fall through, not crash.
        variants = [{'variant_name': 'whatever'}]
        out = oops_v3._filter_primary_identity(variants, {'name': '(Boss)'})
        assert out == variants
