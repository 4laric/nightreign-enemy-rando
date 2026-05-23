# patched_emevd_js/ — proximity_wake patched EMEVD source

These 111 `.emevd.js` files are the output of `emevd_patch.py`'s
`proximity_wake` patch (and ONLY that patch) applied to vanilla NR
decompiled EMEVD. They are EmevdScript SOURCE — not loadable as-is.

## What's in here

- `common_func.emevd.js` — has the new `$Event(99055500)` proximity-
  wake event appended (the parameterized one-shot wake handler).
- 110 per-map `mXX_YY_*.emevd.js` — each has one or more
  `$InitializeCommonEvent(0, 99055500, <entity>, 15)` calls injected:
    * after a 90015000/07/21 encounter registration, OR
    * into the constructor `$Event(0, ...)` for fragile-slot bosses
      (the data/fragile_slot_entities.json pass).

282 wake handlers total across the 111 files.

## To get loadable files

Recompile each `.js` back to `.emevd.dcx` with DarkScript3:

    DarkScript3.exe <file>.emevd.js   ->   <file>.emevd.dcx

Then drop the recompiled `.emevd.dcx` files into your me3 profile's
`event/` folder (or wherever you stage emevd overlays).

Maps NOT in this folder received no injections — keep their vanilla
EMEVD untouched.

## What this is testing

- Whitelist->blacklist fragile filter flip (MMV chrs eligible at
  fragile slots).
- proximity_wake widened to the 90015000/07/21 encounter family.
- The fragile-slot wake pass driven by data/fragile_slot_entities.json
  (105 fragile miniboss/field_boss entities, 42 maps).

The append-only binary serializer (healthbar_inplace/serialize.py) is
NOT exercised by this — that's the next step, to eliminate the
DarkScript3 recompile. This test run still uses the DarkScript3 path.
