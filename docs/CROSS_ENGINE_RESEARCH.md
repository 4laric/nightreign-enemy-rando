# Cross-engine chr empirical observations

Living log of "should-have-CTD'd but didn't" observations. The point
is to update the engine's default blocklists when empirical play proves
the theoretical fragility wasn't real, while preserving the data that
explains WHY each guard exists.

## v0.24.24 — DS1 chr (Manus) working in Limveld field, solo

**Seed**: 738357 (also produced the m30_30 fort-roof c6260 CTD —
that one was real, see COMMIT_MESSAGE_v0.24.24.md).
**Engine fingerprint**: v0.24.23 reported by spoiler, but cross-engine
ban set didn't actually fire in this run (separate stale-state issue).
**Mode**: multiplayer_safe=True (reported) but gate stuck at module
default (V3_GHOST_EXCLUDE=7, not 197 — see _diagnose_engine_state.py).

### The four Manus placements

All four were `is_boss=False, entity_id=0` — none triggered a boss-
arena event chain. They replaced normal grunt/miniboss field slots:

| Map                | pi | Position          | Original (vanilla)              |
|--------------------|----|-------------------|---------------------------------|
| m43_00_00_00.msb   | 18 | (-179.8, -9.3, 1) | c4351 Lordsworn Captain        |
| m43_41_00_00.msb   |  8 | (-3.4, 2.1, -7)   | c4110 Demi-Human Shaman        |
| m48_50_00_00.msb   |  8 | (4.1, -2.0, 2.4)  | c4353                          |
| m60_44_39_30.msb   | 16 | (16.7, 127.4, -0.1)| c4110 Demi-Human Shaman       |

Plus 6 c1260 Hollow Manserving Servant (BB origin) placements in the
same run.

### What Alaric observed in-game

> "I saw a manus in the field in Limveld, and the Manus was working."

Walked up to a Manus in Limveld (likely m60_44_39_30 pi=16 — the y=127
high-altitude one), it loaded, rendered, attacked normally. No CTD.

### Why this contradicts v0.23.39's MMV_INCOMPATIBLE_ORIGINS premise

The cross-engine guard added in v0.23.39 bans `origin_game in {DS1, BB}`
on the assumption that their asset graphs (chrbnd contents, anim banks,
event handler systems) wouldn't resolve at runtime when NR's engine
tried to spawn them, especially at scripted-intro slots. Manus working
at non-scripted field slots, solo, with MMV installed, is direct
counterevidence to the wholesale ban.

### What the v0.23.39 ban actually protects against

The historical concern was probably boss-arena scripted intros: the
spawn-with-cinematic event chain references chr-specific intro anims,
camera cuts, and dialogue events that are NR-internal. A DS1/BB chr
hitting that path would either crash at the scripted-intro event
resolution or freeze the player input. **Field-tier placements
(is_boss=False, entity_id=0) skip the entire scripted-intro chain.**
They use the generic spawn-and-idle path, which only needs the chrbnd
to be present locally — and with MMV installed, it is.

### Updated hypothesis (working)

Cross-engine origin (DS1/BB) is **not** a host-side stability concern
when:
1. Solo play
2. Host has MMV (or whatever pack provides the chr) installed
3. Placement at non-scripted-intro slot (is_boss=False, entity_id=0)

The original concern was probably **scripted-intro CTDs** at boss-arena
slots, where the event chain references NR-internal cinematic systems.
Field placements bypass all of that.

### What that means for the gate

The current `MMV_INCOMPATIBLE_ORIGINS = {'DS1', 'BB'}` cross-engine
guard in `engine/pack_loaders/mmv_imports.py` is **too broad**. A
narrower version would gate on slot characteristic instead of chr
origin:
- DS1/BB chrs blocked at `expects_boss_arena=True` slots (where the
  scripted-intro chain fires) — this is the geometric/scripting risk
- DS1/BB chrs allowed at field-tier slots (is_boss=False, entity_id=0
  semantics) — empirically stable per this observation

But this is a slot-side gate, not a chr-side gate, and would need
the picker's source-slot characteristic available at exclude-fold
time (it isn't — the gate fires at load_data, before any slots are
inspected).

### Proposal: split the cross-engine ban

Instead of a binary `MMV_INCOMPATIBLE_ORIGINS` set, two separate sets:

1. `MMV_INCOMPATIBLE_AT_BOSS_ARENA = {'DS1', 'BB'}` — applied in
   pick_target_cp when `slot.expects_boss_arena=True` OR when the
   slot is in V3_BOSS_TIER_PINNED_SLOTS. Subtracts from pool.
2. `MMV_INCOMPATIBLE_EVERYWHERE = set()` — empty by default. Reserved
   for chrs that genuinely break at any slot. Add to this only after
   observed CTD with the chr at a non-scripted-intro field slot.

The current cross-engine bans fold into bucket #1. Bucket #2 starts
empty until field-slot CTDs are observed.

### Why we shouldn't act on this yet

1. Sample size = 1 playthrough. Need more data points across
   different DS1/BB chrs at different slot types.
2. **Coop concern is independent.** Even if cross-engine chrs are
   host-stable at field slots, a coop partner without MMV would still
   CTD on cell-load when their game can't resolve c8500's chrbnd. The
   gate's value for multiplayer_safe=True remains real.
3. **The MP-safe stale-state issue is muddying the data.** The Manus
   appeared in a run where mp_safe didn't fully apply. With mp_safe
   correctly applied (V3_GHOST_EXCLUDE=197), c8500 would be in the
   blocked set REGARDLESS of cross-engine status, just because it's
   `_source=mmv_import`. So this observation tells us about cross-
   engine compatibility but doesn't yet validate that mp_safe is over-
   conservative — we need a run with mp_safe=False where Manus loads.

### Action items (not yet done)

- [ ] Run a controlled test with `multiplayer_safe=False` and observe
      whether Manus / Lichdragon / Hollow Servant at field-tier slots
      remain stable for the entirety of an expedition (not just walked
      past).
- [ ] If stable: propose splitting `MMV_INCOMPATIBLE_ORIGINS` into
      arena-only and everywhere buckets per the proposal above.
- [ ] Audit other DS1/BB chrs at field slots from the same spoiler
      (c1260 Hollow x6) — were they stable too? Check Alaric's
      session for visual confirmation.
- [ ] Consider: extend the v0.24.24 anim_class backfill to also
      include `expects_boss_arena=False` for chrs that have only
      field variants — would let a future "block at arena, allow at
      field" gate use the existing tag field rather than introducing
      new metadata.

### Why this matters

Two priors that this finding pushes against:
1. v0.23.27 "non-vanilla chrs need boss-tier scaffolding" — this was
   updated for heritage in v0.24.20 (`_source` allow-list) but the
   cross-engine MMV ban from v0.23.39 wasn't revisited.
2. v0.23.39 "DS1/BB asset graphs break at runtime" — testable
   hypothesis. If field placements work, the issue was always
   scripted-intro chains, not asset resolution.

Both push toward a *narrower, more empirical* gate model: block
specific failure modes (scripted-intro chains, asset-missing in coop)
rather than entire categories (origin_game, _source).
