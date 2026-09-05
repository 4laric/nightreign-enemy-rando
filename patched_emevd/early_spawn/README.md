# patched_emevd/early_spawn/

Alternate **`common_func.emevd.dcx`** for the "Early night-boss spawn (RoR2
teleporter)" GUI toggle.

When the user enables **Early night-boss spawn** on the Generate /
Heritage tab, the GUI installs the `common_func.emevd.dcx` from THIS folder
instead of the default one in `patched_emevd/`. Every other EMEVD file
(`common_func` aside) is reused byte-for-byte from `patched_emevd/` — only
`common_func` differs.

## What the difference is

The only change vs. the shipped (clock-gated) build is the trigger condition
inside common_func event **`90065950`** (`nb_night_transition`):

- **Default (clock):** the night gate arms on the vanilla 23:00–23:59 window
  — `PlayAreaCurrentTimeInRange(23,0,0,23,59,59)`.
- **Early spawn (this folder):** the night gate arms on **player proximity**
  to the night boss — `EntityInRadiusOfEntity(20000, bossEntityId, 5, 1)` —
  so a player can walk up to a night-boss arena and start the fight before
  the storm reaches night.

Everything else is identical and intentionally retained: the
`WaitFor(EventFlag(gateFlag))` night-scoping, the N2 `EventFlag(7512)`
"a night boss has died" softlock guard, and the redundant
7501/7504/7707 (N1) and 7506/7509/7727 (N2) storm / night-progress flag
firing (so day-rollover behaves exactly the same).

The per-map night-tile binaries already pass the boss entity id as the
first arg to `90065950`, so they don't change — that's why only
`common_func` lives here.

## How to (re)generate this file

From a clean decompile of vanilla `common_func.emevd.dcx` (DarkScript3):

```
# 1. Decompile vanilla common_func -> common_func.emevd.dcx.js (DarkScript3)
# 2. Emit the proximity variant (only nb_night_transition changes):
python emevd_patch.py patch <decompiled_dir> <out_dir> \
    --patch nb_night_transition --early-boss-spawn
# 3. Recompile <out_dir>/common_func.emevd.dcx.js -> .emevd.dcx (DarkScript3)
# 4. Drop the result here:
#       patched_emevd/early_spawn/common_func.emevd.dcx
```

(If you want the full batch in early-spawn mode, drop `--patch
nb_night_transition` and pass `--early-boss-spawn` to the whole run; the
per-map files come out identical to the default build, so you still only
need to copy `common_func.emevd.dcx` out of it.)

## Until the binary is here

The GUI treats the toggle as a no-op-with-warning if
`early_spawn/common_func.emevd.dcx` is missing: it logs that the early-spawn
binary isn't bundled and falls back to the default clock-gated build, so an
enabled toggle never ships a broken or half-applied EMEVD.

## Design caveat (worth a playtest)

Because the `gateFlag` wait is retained, the early spawn only arms once the
engine has flipped this arena's gate flag (AABB0000 N1 / AABB0001 N2).
Whether that happens at expedition start or only at the night transition was
the open empirical question from the design pass — if it's set late, "early"
is bounded by it. Dropping the gateFlag wait for truly-from-start spawning
is a separate change (it also loosens N1/N2 scoping) and is not what this
build does.