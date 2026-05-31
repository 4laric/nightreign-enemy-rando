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
    """Each ban needs an inline comment explaining why — without
    rationale, a future maintainer might lift the bans thinking
    they were defensive against a since-fixed CTD."""

    def test_inline_comment_explains_no_sauce(self):
        """c4500 + c4505 ban rationale: 'no sauce'."""
        import inspect
        src = inspect.getsource(oops_v3)
        exclude_idx = src.find('V3_EXCLUDE_TARGET_PREFIXES = {')
        c4500_idx = src.find("'c4500'", exclude_idx)
        assert exclude_idx != -1 and c4500_idx != -1
        # Look at the 1500 chars before c4500 — should contain rationale
        context = src[max(0, c4500_idx - 1500):c4500_idx]
        assert ('sauce' in context.lower() or 'no element' in context.lower()
                or 'agheel' in context.lower() or 'bland' in context.lower()), (
            "The c4500/c4505 ban needs an inline comment explaining the "
            "'no sauce' rationale — without it, a future maintainer "
            "might lift the ban thinking it was defensive.")

    def test_inline_comment_explains_greyoll_size(self):
        """c4504 ban rationale: too big."""
        import inspect
        src = inspect.getsource(oops_v3)
        exclude_idx = src.find('V3_EXCLUDE_TARGET_PREFIXES = {')
        c4504_idx = src.find("'c4504'", exclude_idx)
        assert exclude_idx != -1 and c4504_idx != -1
        context = src[max(0, c4504_idx - 1500):c4504_idx]
        assert ('greyoll' in context.lower() or 'too big' in context.lower()
                or 'giant' in context.lower() or 'clipping' in context.lower()), (
            "The c4504 ban needs an inline comment explaining the "
            "'too big' rationale (Greyoll-specific). Without it, a "
            "future maintainer might lump it in with the rot/ice "
            "dragons and lift the ban.")

    def test_todo_reference_present(self):
        """The comment block should mention the ER-dragon-import TODO
        so anyone reading the bans knows there's a plan to widen the
        pool rather than just shrink it."""
        import inspect
        src = inspect.getsource(oops_v3)
        exclude_idx = src.find('V3_EXCLUDE_TARGET_PREFIXES = {')
        c4500_idx = src.find("'c4500'", exclude_idx)
        context = src[max(0, c4500_idx - 1500):c4500_idx + 200]
        assert 'TODO' in context and 'dev/TODO.md' in context, (
            "The dragon-ban comment should reference dev/TODO.md so "
            "readers know about the planned ER-import widening work.")
