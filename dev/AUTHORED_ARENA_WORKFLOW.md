# Authored Test Arena — Workflow

A how-to for using `dev/build_test_arena.py` to create a custom mob-only
test arena. Companion to `dev/TEST_MODE.md` (which covers the wider
architectural context and why this exists).

## What this gives you

A single Limveld overlay arena, hijacking one of the existing N1/N2 map
slots (default: m48_70), populated with a chr roster of your choosing.
Each chr is set to `GameEditionDisable=NeverDisable` so they're alive
the instant the map loads — no waiting for night-1, no flag dependencies.

The matching EMEVD uses MMV's `9001x` post-spawn-dressing pattern
(music, healthbar, death observer per chr). Because the chrs are alive
at load, this pattern actually works on this MSB — the same pattern
that was wrong for v0.25.8 (vanilla MSBs with disabled chrs) is right
here because we control both halves.

## Workflow

### One-time setup

You'll need [Witchy](https://github.com/ividyon/WitchyBND) for the MSB
binary round-trip. Confirm Witchy Repack works on a witchy'd MMV MSB
as a sanity check before doing anything else:

```
1. Pick a directory like `/tmp/mmv_msb/m46_56_00_00-msb-dcx/`
2. Run Witchy Repack on it
3. Confirm the output `.msb.dcx` is byte-identical to MMV's original
   (or very close — Witchy may not preserve every padding byte)
4. Drop the repacked .msb.dcx into a test me3 profile, launch the game,
   confirm the arena still works
```

If this passes, the round-trip is viable. If not, hex-patching the
binary directly is needed (see `dev/TEST_MODE.md` Path B for the
fallback).

### Per-arena build

```bash
# Generate MSB XML directory + matching EMEVD binary in one command
python3 dev/build_test_arena.py \
    --host m48_70_00_00 \
    --out-dir /tmp/my_test_arena
```

Output:
```
/tmp/my_test_arena/
├── m48_70_00_00-msb-dcx/      ← Witchy directory, ready for repack
│   ├── _witchy-msbe.xml
│   ├── Model/{Enemy,Asset}/...
│   ├── Part/{Enemy,Asset}/...
│   └── Event/PatrolInfo/
└── m48_70_00_00.emevd         ← Pre-DCX EMEVD binary
```

### Customize the roster

Edit `DEFAULT_ROSTER` in `dev/build_test_arena.py`:

```python
DEFAULT_ROSTER = [
    # c_prefix, npc_param,  think_param, position_x
    ('c4580',   904580600,  0,           0),    # Large Wormface
    ('c2280',   228000000,  0,           10),
    # ... add more
]
```

Keep:
- `c_prefix` is the chr model (the engine looks for `c{NNNN}` chrbnd
  bindings at runtime)
- `npc_param` is the chr's stats row. Use NpcParam IDs from regulation.bin
  or from observed vanilla placements (a vanilla EMEVD passes the
  NpcParam for the chr that was originally at that slot).
- `think_param` can usually be 0 (regulation derives it). Set explicitly
  if you want a specific AI variant.
- `position_x` spreads chrs along the X axis. Untested whether NR's
  Limveld-overlay positioning respects these — if all chrs stack at
  the same spot in-game, MSB Position is being overridden by the host
  tile's positional data and we'll need a different approach (e.g., set
  positions to match where vanilla mob spawns are in the host tile).

Each new chr gets:
- `eid = eid_base + 800 + i*10` (so 48700800, 48700810, ...)
- `instance_id = 9000 + i` (so 9000, 9001, ...)
- Auto-derived death_flag in the matching EMEVD

### Pick a host arena

The host is the existing N1/N2 MSB slot we're hijacking. The engine
loads OUR `.msb.dcx` instead of vanilla's. Default is m48_70 (a
single-boss arena). Other simple hosts:

- m48_70, m49_10, m49_17, m49_18, m49_19, m49_20, m49_21, m49_23 — all
  single-boss expedition arenas using vanilla 90065910 pattern.

Avoid as hosts:
- m48_50, m48_60 — Tricephalos (3-boss, complex multi-phase)
- m48_80 — Godskin Duo (2-boss, specialized 90065131 variant)
- m49_25 — BBH (specialized 90065121 variant)
- m48_90 — multi-phase 90065100/101
- m47_70 — Augur (4-wave map-local events)

Why simple is better as a host: we're authoring a brand-new MSB that
matches our brand-new EMEVD. Vanilla's complexity at the host slot is
discarded; whatever extra machinery was scripted there doesn't matter
because we replace both halves. Picking a simple host just makes the
"where does the player end up?" question easier to answer.

### Deploy to me3 profile

After Witchy Repack:

```bash
# The Witchy output ends up next to the source directory
ls /tmp/my_test_arena/m48_70_00_00.msb.dcx

# The EMEVD still needs DCX compression — easiest path is letting
# the regular pipeline compress it. Or do it manually with the
# project's DCX_KRAK helper if you have one handy.
# (Pipeline route: drop the .emevd into a staged build directory and
# run dcx_batch on it; the output .emevd.dcx goes where you need it.)

# Then drop both into the me3 profile, overwriting vanilla:
cp /tmp/my_test_arena/m48_70_00_00.msb.dcx \
   "${ME3_PROFILE}/map/mapstudio/"
cp /tmp/my_test_arena/m48_70_00_00.emevd.dcx \
   "${ME3_PROFILE}/map/mapstudio/"
```

### Test in-game

1. Launch via me3
2. Start an expedition. The Nightlord pick doesn't matter (we hijack a
   specific MSB slot regardless).
3. Walk to where the vanilla N1 arena would put the player. If you
   chose m48_70 as host, the engine's expedition routing for whichever
   Nightlord uses m48_70 takes you there. (Look up which Nightlord that
   is in the engine's nightlord_pools data, or just play through and
   see where the night-1 transition takes you.)
4. The 5 test chrs (or however many you configured) should be alive
   and waiting on arrival. Walk down the line, fight each.

## Troubleshooting

### "I don't see any chrs in the arena"

Possible causes:
- Witchy Repack failed silently or produced an invalid MSB. Check the
  byte size of the output vs the original vanilla — wildly different
  size suggests a serious parse problem.
- `me3` profile path mismatch: the file isn't where the game loads from.
- Engine took you to a different N1 arena than expected (depends on
  which Nightlord this seed's expedition selected). Verify by looking
  at the seed's spoiler for what map slot was used.

### "Chrs are there but stack on top of each other"

The Position field in the MSB Part is being overridden by the host
tile's positional data. The MMV references all use `(0, 0, 0)` for
position, so this is the expected MMV behavior. For a "walk down a line"
layout we'd need positions that match real vanilla spawn coordinates
within the host tile. Future work — patch positions per host.

### "No boss healthbar"

The MMV-style EMEVD includes `90015002` (healthbar dressing) per chr.
If the chr is alive but no healthbar:
- The healthbar event might gate on a flag we're not setting. Check
  `90015002` definition in `common_func.emevd.js` to see what it expects.
- The chr's NpcParam might not be a "boss tier" NpcParam (some
  NpcParams disable boss-bar UI). Try a known-boss-tier NpcParam.

### "Game crashes on map load"

Likely an MSB validation issue. The Asset Part is the most fragile
because our emitter doesn't fully cover all its fields — we rely on
copying MMV's reference XML verbatim and patching only EntityID. If
that fails (e.g., MMV reference path wrong), the fallback emitter is
known-incomplete.

Also: chrbnd availability. The engine needs to find binding data for
each `c_prefix` we list. Most c{NNNN} chrs are bundled in vanilla NR;
some need explicit imports (covered elsewhere in this project — see
the chr pack loader logic in `oops_v3.py`).

## Status / TODO

- **Sanity experiment** (recommended before deeper work): take a
  witchy'd MMV MSB unchanged, run Witchy Repack on it, drop into me3
  profile (replacing nothing initially — just confirm Witchy round-trip
  yields a loadable .msb.dcx). 30 min, big risk reduction.

- **Position-per-host**: extend the builder to know where vanilla mob
  spawns are in each host tile's region, so authored chrs spawn at
  recognizable arena spots instead of all at origin.

- **chrbnd validation**: cross-check the roster's c_prefix list against
  available chrbnds before emitting, so we don't emit a roster with
  unavailable chrs.

- **Roster-from-rando-pool**: helper that builds a roster directly from
  the rando's spawn pool / sensitive set, so we can test exactly the
  chrs the rando might place. Right now `DEFAULT_ROSTER` is hardcoded.

- **DCX integration**: the EMEVD output is pre-DCX. Either pipe through
  the project's existing DCX compression, or document the manual
  oodle-compress step.
