"""
test_flying_dragon_ban.py — v0.26.x: ban c4500, c4504, c4505 from the
swap pool. Three different reasons but one shared theme: every dragon
slot should land on something visually/mechanically interesting.

  c4500  Flying Dragon (Agheel-class base) — no element/status, the
         "no sauce" dragon.
  c4504  Elder Dragon Greyoll — too big. Giant prone elder dragon
         doesn't fit random arenas (clipping, absurd healthbar).
  c4505  Flying Dragon (Small) — same "no sauce" complaint as c4500,
         just smaller. Horde role wasn't enough to save it.

Saucy variants stay eligible: c4501/c4502 Ekzykes-class (scarlet rot),
c4503 Borealis (ice), c4510 Ancient (lightning), c5860 Ghostflame
(death), c7700 Gaping Dragon (bile/heritage). Every dragon swap from
now on lands on one of these.

There's a corresponding TODO in dev/TODO.md to investigate ER dragon
heritage imports (Smarag, Adula, Glintstone Dragon, etc.) — would
widen the saucy pool further.
"""
import pytest
import oops_v3


BANNED_FLYING_DRAGONS = {
    'c4500': 'Flying Dragon (Agheel-class base, no element/status)',
    'c4504': 'Elder Dragon Greyoll (too big)',
    'c4505': 'Flying Dragon (Small) — same no-sauce complaint as c4500',
}

SAUCY_DRAGONS_KEPT = {
    'c4501': 'Decaying Ekzykes (scarlet rot)',
    'c4502': 'Decaying Ekzykes-class (variants of rot dragon)',
    'c4503': 'Borealis the Freezing Fog (ice)',
    'c4510': 'Ancient Dragon (lightning)',
    'c5860': 'Ghostflame Dragon (death)',
    'c7700': 'Gaping Dragon (heritage, bile)',
}


class TestFlyingDragonBan:
    @pytest.mark.parametrize('cp,reason', list(BANNED_FLYING_DRAGONS.items()))
    def test_dragon_banned(self, cp, reason):
        """Each of the three banned dragons must be in V3_EXCLUDE_TARGET_PREFIXES.
        If one slips out, swap rolls will start landing on the
        uninteresting variants again."""
        assert cp in oops_v3.V3_EXCLUDE_TARGET_PREFIXES, (
            f"{cp} ({reason}) must be in V3_EXCLUDE_TARGET_PREFIXES.")

    @pytest.mark.parametrize('cp,name', list(SAUCY_DRAGONS_KEPT.items()))
    def test_saucy_dragon_still_eligible(self, cp, name):
        """The whole reason to ban the bland/oversized ones is to
        give the cool variants more swap presence. If any of these
        accidentally got banned, the change is self-defeating."""
        assert cp not in oops_v3.V3_EXCLUDE_TARGET_PREFIXES, (
            f"{cp} ({name}) must NOT be in V3_EXCLUDE_TARGET_PREFIXES — "
            f"banning the saucy variants would defeat the whole "
            f"point of banning the bland ones.")

    def test_at_least_six_saucy_dragons_remain(self):
        """Sanity floor — after the bans, the dragon pool shouldn't
        collapse to one or two options. If this drops, either someone
        added more bans without reviewing impact, or the saucy list
        in this test is stale."""
        remaining = [cp for cp in SAUCY_DRAGONS_KEPT
                     if cp not in oops_v3.V3_EXCLUDE_TARGET_PREFIXES]
        assert len(remaining) >= 6, (
            f'Only {len(remaining)} saucy dragons remain after bans: '
            f'{remaining}. Need at least 6 for healthy variety.')


class TestRationaleDocumented:
    """Each ban needs documented rationale — without it, a future
    maintainer might lift the bans thinking they were defensive
    against a since-fixed CTD.

    Post-Step-3 (v0.28.x): rationale lives in the JSON's editorial
    fields (`exclude_reason`, `rationale`, `since`) rather than in
    inline source comments. This class checks those JSON fields for
    the three banned dragons. Establishes the documentation pattern
    that other future bans should follow.

    The pre-Step-3 version of this class grepped oops_v3.py source
    code for keywords like 'sauce' / 'greyoll' near the inline literal
    entries. That literal is gone now (Step 3) — comments live in git
    history; structured rationale lives in the JSON.
    """

    def _load_json(self):
        import json
        import os
        ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(ROOT, 'data', 'placement_budget.json')) as f:
            return json.load(f)

    def test_no_sauce_rationale_in_json(self):
        """c4500 + c4505 ban rationale: 'no sauce' / 'no element'.
        Their JSON entries must mention this so a future maintainer
        doesn't lift the ban thinking it was defensive."""
        d = self._load_json()
        for cp in ('c4500', 'c4505'):
            e = d['chrs'].get(cp, {})
            reason = (e.get('exclude_reason') or '') + ' ' + (e.get('rationale') or '')
            reason_lc = reason.lower()
            assert ('sauce' in reason_lc or 'no element' in reason_lc
                    or 'agheel' in reason_lc or 'bland' in reason_lc), (
                f"{cp} JSON entry needs an exclude_reason / rationale "
                f"explaining the 'no sauce' ban rationale. Edit "
                f"data/placement_budget.json — chrs.{cp}.exclude_reason. "
                f"Current: {reason!r}"
            )

    def test_greyoll_size_rationale_in_json(self):
        """c4504 ban rationale: 'too big' / Greyoll size. JSON entry
        must reflect this so it doesn't get lumped with the rot/ice
        dragons and lifted."""
        d = self._load_json()
        e = d['chrs'].get('c4504', {})
        reason = (e.get('exclude_reason') or '') + ' ' + (e.get('rationale') or '')
        reason_lc = reason.lower()
        assert ('greyoll' in reason_lc or 'too big' in reason_lc
                or 'giant' in reason_lc or 'clipping' in reason_lc), (
            f"c4504 JSON entry needs an exclude_reason / rationale "
            f"explaining the 'too big' / Greyoll-specific ban. Edit "
            f"data/placement_budget.json — chrs.c4504.exclude_reason. "
            f"Current: {reason!r}"
        )

    def test_todo_reference_in_at_least_one_dragon(self):
        """At least one of the three banned-dragon entries should
        reference dev/TODO.md so readers know about the planned
        ER-import widening work (the alternative to keeping the bans
        forever)."""
        d = self._load_json()
        any_mention = False
        for cp in ('c4500', 'c4504', 'c4505'):
            e = d['chrs'].get(cp, {})
            reason = (e.get('exclude_reason') or '') + ' ' + (e.get('rationale') or '')
            if 'TODO' in reason or 'dev/TODO.md' in reason:
                any_mention = True
                break
        assert any_mention, (
            "At least one of c4500/c4504/c4505 in "
            "data/placement_budget.json should reference dev/TODO.md "
            "in its exclude_reason or rationale, pointing at the "
            "planned ER-import widening work."
        )
