# bundled_sfx

MMV's SFX bundle for end-user deployment.

## What's here

| File                          | Size   | Source | Purpose                                                          |
|-------------------------------|--------|--------|------------------------------------------------------------------|
| `sfxbnd_c0000.ffxbnd.dcx`     | ~28 MB | MMV (trimmed) | Particle effects for cross-game / DLC / heritage-imported chrs   |

This is **MMV's `sfxbnd_c0000.ffxbnd.dcx`, trimmed** to just the FFX
entries the rando's heritage / cross-game chrs actually consume (down
from MMV's full ~182 MB container). The c0000 SFX bundle is
the shared particle-effect container that almost every chr's
attack/buff/status visuals reference. MMV's version is a superset
of vanilla NR's: it carries the FFX entries cross-game and SoTE-
heritage chrs need (Bayle's flame breath, Romina's scarlet rot
clouds, Putrescent Knight's misted-aether attacks, etc.).

## Why we bundle this

Playtest-confirmed dependency. Without MMV's `sfxbnd_c0000.ffxbnd.dcx`
deployed, heritage-imported chrs and DLC chrs spawn and animate but
their attack/status particle effects either:

- silently no-op (attack lands but the visual signal is missing →
  the player can't tell what hit them), or
- reference an FFX ID that vanilla NR's bundle doesn't define →
  log-spammed FFX-lookup failures, potential crashes on some attacks.

The required SFX IDs are baked into the chrs' AtkParam / BehaviorParam
rows and into the regulation's effect-resource manifest, so dropping
back to vanilla NR's `sfxbnd_c0000.ffxbnd.dcx` would require
re-authoring every cross-game / DLC chr's effect references — far
worse than shipping MMV's bundle.

This is the same "MMV is the canonical asset base" pattern as
`bundled_regulation/regulation.bin` and `bundled_aicommon/`. The
three bundles travel together.

## Deployment

Drop `sfxbnd_c0000.ffxbnd.dcx` into your me3 mod profile under the
`sfx/` subdirectory:

```
<me3 profile>/<package>/sfx/sfxbnd_c0000.ffxbnd.dcx
```

me3 substitutes it at load time. Nightreign reads particle effects
from this copy instead of the install's vanilla bundle.

## Verifying integrity

Format: DCX-compressed FFXBND archive. Expected size approximately
180–190 MB. Significantly smaller suggests a truncated download.
First 4 bytes should be `DCX\0`.

```
ls -lh bundled_sfx/sfxbnd_c0000.ffxbnd.dcx   # ~182 MB
head -c 4 bundled_sfx/sfxbnd_c0000.ffxbnd.dcx | od -An -c
# Should show: D C X \0
```

## Regeneration

If MMV ships an SFX update (new cross-game chrs with new particles,
or fixed effect references), drop the new `.ffxbnd.dcx` in here,
replacing the existing file. No code change needed — the bundle
installer reads whatever's in this directory.

A future Python-side SFX patcher would let us layer rando-specific
effect tweaks on top of MMV's bundle (the same way
`bundled_regulation/` layers param patches on top of MMV's
regulation), but that's not in scope today. For now the bundle
ships verbatim from MMV.
