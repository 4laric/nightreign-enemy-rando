# Boss Reward Injection — EMEVD Route (v0.4)

**Goal:** Every boss slot in the rando triggers the standard NR choice-of-3
reward picker on confirmed boss kill, regardless of which c-prefix the
randomizer placed there.

**Approach:** Pure EMEVD. No regulation.bin patching — preserves
compatibility with other mods that touch NpcParam, ItemLotParam, etc.

## How it works

The patcher (`emevd_patch.py boss_reward_inject`) modifies
`common_func.emevd.dcx.js` only — no per-map files touched.

### What it changes

For each of the 7 boss-wake handler events (`90015000`, `90015007`,
`90015021`, `90015023`, `90015026`, `90015406`, plus the encampment-clear
handler `90085016`), it inserts:

```js
if (chr2.Passed) {
    HandleMinibossDefeat(chrEntityId);
}
```

right before the event's `EndIf(chr2.Passed)` exit point. `chr2.Passed`
is the engine signal that the boss is confirmed dead.

### Why HandleMinibossDefeat

`HandleMinibossDefeat(chrEntityId)` is NR's built-in instruction for
"this miniboss died, run the standard reward flow." It's the same call
every vanilla per-map dungeon-boss death handler uses (see m46_50,
m34_10, m35_90, m60_4X for canonical examples).

It triggers the choice-of-3 reward picker UI without requiring an item
lot ID — the engine's internal logic picks NR-appropriate rewards and
presents the floating-item picker.

### Why not AwardItemLot

Earlier versions used `AwardItemLot(<lot_id>)` to grant a fixed lot.
This was wrong:

1. `AwardItemLot` delivers items DIRECTLY to inventory. NR's lot tables
   include items that don't render correctly when granted directly
   (Remembrances with no usage path, ER weapons with no NR access path).
2. Even when the item was the right category, "directly into inventory"
   is not the player-expected outcome of a boss kill — the picker UI
   is.

`HandleMinibossDefeat` sidesteps both by routing through NR's intended
boss-reward path.

## Universality

Every boss with a healthbar in NR is registered with one of the boss-
wake handler events via `$InitializeCommonEvent` in its map's `.emevd`.
The wake handler IS the healthbar mechanism — if there's a healthbar,
the handler ran, and our `HandleMinibossDefeat` will fire on death.

This is why the patch needs no static inventory of boss slots: the
"is this a boss?" determination is delegated to NR's own healthbar-
registration mechanism.

## Trade-offs

* **Double-fire on vanilla dungeon bosses.** About 28 boss positions
  already have map-specific `HandleMinibossDefeat` calls. Those will
  trigger the picker twice (once from their map handler, once from this
  common_func hook). NR appears to coalesce repeat triggers within a
  short window; worst case is a redundant picker on a small subset of
  boss kills. If this causes user-visible duplication, the fix is to
  exclude the relevant entity IDs from the common_func hook — but
  that requires a static inventory.

* **Empty picker on under-configured swap-ins.** If a randomized
  c-prefix's NpcParam lacks the boss-reward-set config, the picker
  may appear empty. Not observed yet — a known unknown.

## Applying the patch

The patch is part of `emevd_patch.py`'s standard pipeline:

```
python emevd_patch.py patch <decompiled_dir> <output_dir>
```

This applies all five patches (death_timeout, permissive_boss_wake,
permissive_spawn_emerge, disable_corpse_collision, boss_reward_inject) in
one pass.

To run only this one:

```
python emevd_patch.py patch <decompiled_dir> <output_dir> --patch boss_reward_inject
```

Then recompile each modified `.emevd.dcx.js` with DarkScript3 and drop the
resulting `.emevd.dcx` files into `<me3_profile>/<package>/event/`.

## Idempotency

The patch detects "already injected" by string match on the v2 marker
(`'boss_reward_inject_v2'` in content) and skips. Running the patcher
twice on the same files is a no-op.

If the patcher detects an OLD v1 injection (`AwardItemLot`-based, no
`_v2` marker) it refuses to apply on top and warns to re-run from
vanilla. v1 and v2 inject in the same place via different patterns;
mixing them would corrupt the event flow.

## Reverting

To remove the injections from already-patched files:

* common_func: search for `// === boss_reward_inject_v2 ===` and delete
  the comment plus the `if (chr2.Passed) { HandleMinibossDefeat(...); }`
  block, OR re-run the patcher against fresh vanilla EMEVD.
