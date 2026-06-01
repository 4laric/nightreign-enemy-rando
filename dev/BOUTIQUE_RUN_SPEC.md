# Spec: "Boutique Run" — per-tier opt-in pool selection (v0.29.x)

## Problem statement

Today the user has one binary lever for pool composition: **excluded_prefixes**. A
chr is either in the pool (default) or out. The existing dynamic pool adjustment
covers three things — exclude individual chrs, override caliber (NB-arena
eligibility), override individual caps — all global toggles applied uniformly
across every slot the chr would otherwise reach.

What's missing: tier-scoped pool control. Users want to say "for THIS run, use
only these grunts, these minibosses, these field bosses, and these night bosses."
A "boutique run" — hand-curated rosters per tier, like building a deck instead of
banning cards from a uniform pool.

This is an additive expansion: the existing exclude/caliber/cap controls all
remain. The new control is a per-tier whitelist of chrs that the user has
opted-in for that tier; if the whitelist is set, only those chrs are eligible
for slots of that tier; if it's empty/unset, the tier behaves at default
(current behavior).

## Tier semantics in the engine

The engine recognizes these tier values on `tags[cp]['tier']`:

- **grunt** — base mob (189 chrs in current roster). Field-strength tier.
  Includes the "trash" subcategory historically but it was folded into grunt at
  line 3945-3946 (`if _t.get('tier') == 'trash': _t['tier'] = 'grunt'`).
- **miniboss** — field elite (100 chrs). Field-strength tier; can roll up from
  grunt slots via the v0.27.13 field upgrade chance.
- **field_boss** — open-world boss (15 chrs). Boss-strength tier; non-arena.
- **night_boss** — Night arena anchor (64 chrs). Boss-strength tier; eligible
  for NB-anchor slots iff also in `V3_NIGHT_BOSS_CALIBER_TARGETS`.
- **nightlord** — heaviest tier (17 chrs). True Nightlords + arena-bound boss
  imports. Field-roll explicitly excludes this tier (line 13701-13708 comment).
- **cinematic / non_combat / mount_component** — never placeable; the existing
  `pools_caps_panel._load_engine_defaults()` already hides these from the UI.

The user-facing tiers are exactly the four placeable combat tiers: **grunt,
miniboss, field_boss, night_boss**. nightlord is engine-internal (Nightlord
expedition bosses), not a user knob.

## Naming

User-facing label set (the original ask was "grunts, trash, miniboss, field,
night boss"; "trash" doesn't exist as a tier anymore — see grunt above):

| User label    | Engine tier      | Roster count (current) |
|---------------|------------------|------------------------|
| Grunts        | `grunt`          | 189                    |
| Minibosses    | `miniboss`       | 100                    |
| Field Bosses  | `field_boss`     | 15                     |
| Night Bosses  | `night_boss`     | 64                     |

The spec uses engine tier names internally and the user-facing labels in the GUI.
There is no separate "trash" knob — grunt covers it.

## Mental model: bans vs picks

Two complementary modes a tier opt-in can present as. Spec covers BOTH; the GUI
exposes one toggle per tier:

- **Ban mode (subtractive)** — start from all chrs of this tier, deselect the
  ones you don't want. Equivalent to today's exclude tab, but tier-scoped.
- **Pick mode (additive)** — start empty, click chrs to include. Inverse of ban
  mode; better for boutique runs where the curated list is short.

Internally these collapse to the same engine kwarg: a **whitelist set per tier**.
Whether the GUI was in ban or pick mode is a presentation detail; the engine
sees `tier_pool_whitelists[tier] = {cp, cp, ...}`.

If a tier's whitelist is **empty**, that means "all chrs of this tier
EXCLUDED" (boutique mode, nothing in this tier). If a tier's whitelist is
**None / absent**, that means "default behavior — no tier-level restriction"
(today's behavior).

This distinction is essential: empty-set and absent-key must be different,
because empty-set is a valid user choice ("I want zero night bosses this run")
that the engine has to honor.

## Engine integration point

Adds one filter step at the per-slot tier filter site, oops_v3.py line ~13724,
inside `pick_target_cp`. Where the engine today does:

```python
elif src_tier in V3_BOSS_STRENGTH_TIERS:
    tier_pool = {cp for cp in pool
                 if tags.get(cp, {}).get('tier') in V3_BOSS_STRENGTH_TIERS}
```

it gains an additional intersection:

```python
elif src_tier in V3_BOSS_STRENGTH_TIERS:
    tier_pool = {cp for cp in pool
                 if tags.get(cp, {}).get('tier') in V3_BOSS_STRENGTH_TIERS}
    # v0.29.x: per-tier boutique whitelist. If the user has opted-in
    # specific chrs for this slot's tier, intersect to that whitelist.
    tier_pool = _apply_tier_whitelist(tier_pool, src_tier, tags)
```

Same call slots into the field-roll branch and the boss-strength branch and the
fallback ladder (line 13712-13723) — one helper, applied wherever `tier_pool`
gets assigned.

Helper signature:

```python
def _apply_tier_whitelist(pool: set, tier: str, tags: dict) -> set:
    """Restrict `pool` to chrs the user has whitelisted for `tier`.

    Reads V3_TIER_WHITELISTS, a dict[tier_name] -> frozenset[cp] | None.
    Each value:
      None    — no restriction (default behavior, pool unchanged)
      frozenset() — empty whitelist (user opted-in zero chrs for this
                   tier, return empty set so the slot falls through
                   to vanilla or the fallback ladder)
      frozenset({...}) — whitelist; intersect pool with it

    The function is tier-aware so a boss-strength fallback (which may
    visit night_boss → miniboss → grunt during the v0.27.13 ladder)
    consults each tier's whitelist independently.
    """
    wl = V3_TIER_WHITELISTS.get(tier)
    if wl is None:
        return pool  # default
    if not wl:
        return set()  # empty allowlist — explicit "none of this tier"
    return pool & wl
```

The fallback ladder at line 13709-13723 (`night_boss → miniboss → grunt`)
already handles "tier_pool empty, try next-down tier." With per-tier
whitelists, the ladder works without changes: if night_boss's whitelist
empties the pool, the existing ladder moves down to miniboss naturally. The
user's choice of "no night bosses, just minibosses scaled up" emerges from
the existing fallback machinery.

## Storage shape: V3_TIER_WHITELISTS

A module-level dict on oops_v3, owned by the apply_run_overrides context
manager (added to `_OWNED_MODULE_FIELDS`):

```python
# v0.29.x: per-tier user whitelists for boutique runs. None values mean
# "no restriction for this tier" (default). Empty frozensets mean "user
# wants zero chrs of this tier." Populated by compose_pool_cap_overrides
# from the GUI's tier_pool_whitelists kwarg. Restored to {tier: None}
# defaults by apply_run_overrides on context exit.
V3_TIER_WHITELISTS = {
    'grunt':      None,
    'miniboss':   None,
    'field_boss': None,
    'night_boss': None,
}
```

Module default is all-None (every tier unrestricted). Adding tier_pool
restriction is a per-run override; module state never persists between runs.

## GUI sketch

Adds a "Per-Tier Boutique" tab (or section in the existing Pools & Caps tab).
For each of the four user-facing tiers, a vertically-split include/exclude
panel with two extra controls:

```
┌─ Grunts ───────────────────────────────────────────────────┐
│  Mode:    [○ Default]  [● Pick]  [○ Ban]                   │
│           Default = no restriction                          │
│                                                              │
│           Available (180)        ▶▶     Selected (9)        │
│           ┌──────────────────┐          ┌──────────────────┐ │
│           │ c3000 Exile Sol… │  ◀◀     │ c3010 Banished K│  │
│           │ c3020 Exile (L)  │  ▶      │ c3500 Skeletal M│  │
│           │ c3060 Giant Sk…  │  ◀      │ c4377 Highwayman│  │
│           │ c3080 Imp        │  ▶▶     │ c5651 Messmer F.│  │
│           │ ...               │          │ ...              │  │
│           └──────────────────┘          └──────────────────┘ │
│  Filter: [_______________]    [Sort: name ▾]                │
│  Presets: [SoTE only] [ER only] [Heritage only] [Reset]     │
└──────────────────────────────────────────────────────────────┘
```

Four such panels, one per tier. The Mode toggle controls how empty-selection
is interpreted:

- **Default** — selection is ignored; the tier behaves at engine default (no
  whitelist applied). Empty selected pane is fine, no effect.
- **Pick** — selection IS the whitelist. Empty selected pane = "no chrs of
  this tier" (empty frozenset, hits the fallback ladder).
- **Ban** — selection is INVERTED into the whitelist. Available - selected =
  whitelist. The display still shows "selected = banned" for UX clarity but
  the engine sees the complement.

Persisted in run config so reload reproduces the choice.

## Engine kwarg

Adds one kwarg to `cmd_shuffle_v3` and one to `compose_pool_cap_overrides`:

```python
tier_pool_whitelists: dict[str, frozenset[str] | None] | None = None
```

Schema:
- Outer dict keyed by engine tier name (`grunt`, `miniboss`, `field_boss`,
  `night_boss`)
- Outer-dict missing key = absent = tier at default (no whitelist)
- Inner value None = same as absent (no whitelist)
- Inner value frozenset() = explicit "none of this tier"
- Inner value frozenset({cp, cp, ...}) = whitelist
- Unrecognized tier keys are dropped with a warning (forward compat)
- cp values not in roster are dropped with a warning (typo guard)

Validation lives in `compose_pool_cap_overrides`, same place as the other
overrides' validation logic.

## Interaction with existing pool/cap mechanisms

The tier_pool_whitelist intersects AFTER the existing pool filters apply, so
all the engine's safety mechanisms still operate on a tier-restricted pool:

1. `excluded_prefixes` (hard exclude) — runs first. An excluded chr is OUT
   regardless of what whitelist contains it. Useful for "I picked these 12
   night bosses but Borealis CTDs on my hardware, exclude her separately."
2. `V3_GHOST_EXCLUDE_TARGET_PREFIXES` (multiplayer-safe etc.) — also wins.
3. `cap_exhausted` — still applies. A whitelisted chr at cap N gets blocked
   from further slots like normal.
4. **Then** the tier-strength filter (V3_BOSS_STRENGTH_TIERS / V3_FIELD_
   STRENGTH_TIERS membership) — unchanged.
5. **Then** the new tier_pool_whitelist intersection.
6. Then the v0.27.13 fallback ladder, if pool emptied.

Cap-groups (the v0.28.x mechanism we just shipped) work identically; whitelist
doesn't care about groups. If c3251 is whitelisted for night_boss and c6251
isn't, only c3251 places — but both still share the cap key, so the group's
cap budget is consumed by c3251 alone.

Reservation pre-pass interaction: a chr in `V3_RESERVATION_FLOORS` (per-seed
guarantees) that's NOT in its tier's whitelist would try to reserve and find
no qualifying slot (every slot of its tier has been narrowed past it). It
should fall through to the unplaced log gracefully, same as if a chr were
in floors but excluded. Worth a test case.

## Failure mode: empty pool fallback

The big design question. If a user selects only 3 chrs for grunt and the
engine reaches a grunt slot:

- For ~3000 placements/seed, 3 grunts means each is placed ~1000 times —
  cap=1000 implicit. That's fine; the cap mechanism naturally caps lower if
  the user sets caps explicitly.
- For a grunt slot whose specific compat constraints exclude all 3
  (e.g. a slot requiring flier-compat tag, none of the 3 whitelisted grunts
  fly), the existing fallback at line 13718 already returns to the broader
  pool (`if _cand: tier_pool = _cand else: ...`) — but with whitelist, even
  the broader pool is narrowed. The slot falls through to the `if not pool`
  branch which leaves the slot vanilla. Acceptable: vanilla is always a
  valid fallback.

This means a too-restrictive whitelist degrades gracefully: slots that can't
be satisfied stay vanilla, no CTD. The spoiler should report on this so the
user knows their choices didn't fit everywhere.

## Telemetry / spoiler additions

In the run summary log, when any tier whitelist is active, print:

```
Tier-pool whitelists active:
  grunt:      9 chrs whitelisted (out of 189 available)
  miniboss:   default (no restriction)
  field_boss: 3 chrs whitelisted (out of 15 available)
  night_boss: empty (user requested no night bosses)

Tier-pool whitelist outcomes:
  grunt:      2974 / 3056 grunt slots filled from whitelist;
              82 slots fell through to vanilla
  field_boss: 12 / 14 field_boss slots filled from whitelist;
              2 fell through to vanilla
  night_boss: 0 / 18 night_boss slots filled from whitelist;
              18 fell through to next-tier-down or vanilla
```

The "fell through to vanilla" line is the key user feedback — if a whitelist
is too tight, they'll see numbers like "12 / 100 grunt slots filled" and
know to widen.

## Test plan

`tests/test_tier_pool_whitelist.py`:

- Picker respects whitelist when set
- Picker uses full pool when whitelist is None
- Empty whitelist returns empty pool (slot falls through)
- Fallback ladder consults each tier's whitelist independently
- Exclude + whitelist interaction: excluded chr stays out even if
  whitelisted
- Cap interaction: cap-exhausted whitelisted chr still gets blocked
- Cap-group interaction: whitelisting one member places, but the group's
  count increments correctly (other member is non-whitelist; only c3251
  placements but cap budget still shared with c6251)
- Reservation pass: chr in floors but not whitelisted goes to unplaced log
- Unrecognized tier name in kwarg gets dropped with warning
- Unknown cp in whitelist gets dropped with warning
- apply_run_overrides restores module default on exit

End-to-end placement test: 10-seed sim with a known whitelist set and a
target percentage of slots filled from the whitelist; assert outcomes are
within tolerance.

## Implementation phasing

Recommend three commits, each independently shippable:

**Phase 1 — engine plumbing** (no GUI yet)
- Add V3_TIER_WHITELISTS module global
- Add `_apply_tier_whitelist()` helper
- Patch pick_target_cp's tier-pool sites to call it
- Add tier_pool_whitelists kwarg threading through cmd_shuffle_v3 →
  compose_pool_cap_overrides → V3_TIER_WHITELISTS
- Add to _OWNED_MODULE_FIELDS for restore
- Tests for the engine layer only

**Phase 2 — telemetry**
- Spoiler additions for whitelist state and outcomes
- The "fell through to vanilla" counter — needs a new accumulator in
  RunContext, incremented from pick_target_cp when whitelist narrows
  the pool to empty
- Spoiler test fixtures

**Phase 3 — GUI**
- Per-Tier Boutique tab (or expand Pools & Caps)
- Mode toggle (Default/Pick/Ban) per tier
- Reuse the existing dual-pane include/exclude widget from
  pools_caps_panel
- Presets per tier ("ER only", "SoTE only", "Heritage only", "Reset to
  default")
- Persistence: serialize chosen mode + selection in run config
- Pre-validation: warn if a tier's whitelist + caps combination would
  starve the reservation pass

## Out of scope (next-revision questions)

These are deliberately deferred. Each is its own micro-spec when the
boutique mode lands and people start using it:

- **Saved presets**: "Save this whitelist set as 'Cleanrot run'" with
  named profiles users can recall. Sketch: serialize to a presets JSON in
  the user config dir; preset = {name, mode, per_tier_selection,
  notes}; load/save buttons next to the mode toggle. Independent of the
  engine layer.
- **Caliber-pool tier-aware behavior**: caliber currently affects only
  NB-anchor eligibility, which is orthogonal to tier whitelist. If a chr
  is in night_boss whitelist but NOT in caliber, it places at non-NB-arena
  night_boss slots (open-field NB-tier locations) but not at the dedicated
  NB arenas. This emerges naturally from the existing caliber check
  layered on top — no spec needed, but worth documenting in the GUI
  tooltip so users aren't surprised.
- **Per-slot tier whitelist overrides** (e.g. "treat THIS specific arena
  as miniboss tier even though it's catalogued NB"): probably a feature
  in its own right, definitely out of scope for the boutique knob.
- **Composability with V3_SOTE_MODE**: SoTE-only mode and per-tier
  whitelist are both pool-narrowing filters; they compose by intersection.
  Document but don't gate; users running both at once just get a tighter
  result. If the result is too tight, the fallback-to-vanilla mechanism
  kicks in.
