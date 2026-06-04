# bundled_sfx

MMV's SFX bundle for end-user deployment.

## What's here

| File                          | Size    | Source | Purpose                                                          |
|-------------------------------|---------|--------|------------------------------------------------------------------|
| `sfxbnd_c0000.ffxbnd.dcx`     | ~182 MB | MMV    | Particle effects for base, cross-game, DLC, and heritage chrs    |

This is **MMV's full `sfxbnd_c0000.ffxbnd.dcx`**, shipped verbatim.
The c0000 SFX bundle is the shared particle-effect container that
almost every chr's attack / buff / status visuals reference. MMV's
version is a superset of vanilla NR's: it carries the FFX entries
cross-game and SoTE-heritage chrs need (Bayle's flame breath,
Romina's scarlet rot clouds, Putrescent Knight's misted-aether
attacks, etc.), AND it fixes FFX references on base NR chrs whose
particle effects were broken in the vanilla bundle.

### Note on sizing — v0.28.2 restored the full bundle

v0.28.1 shipped a trimmed ~28 MB version of this bundle, scoped to
just the FFX entries the heritage / cross-game chrs were known to
consume. v0.28.2 reverts the trim and ships the full ~182 MB bundle
because the trim missed FFX references on **base NR chrs** — some
of vanilla's own effects were broken without the full MMV bundle
deployed. The 154-MB-extra download is the cost of correctness.

## Why we bundle this

Playtest-confirmed dependency. Without MMV's `sfxbnd_c0000.ffxbnd.dcx`
deployed, chr particle effects either:

- silently no-op (attack lands but the visual signal is missing →
  the player can't tell what hit them), or
- reference an FFX ID that vanilla NR's bundle doesn't define →
  log-spammed FFX-lookup failures, potential crashes on some attacks.

This failure mode hits cross-game and DLC chrs hardest (their attacks
reference SOTE-and-later FFX IDs entirely absent from NR's bundle),
but as of v0.28.2 playtest it's confirmed to hit base NR chrs too on
specific attacks where vanilla's bundle has a missing or broken
reference — MMV's bundle restores the intended visual.

The required SFX IDs are baked into the chrs' AtkParam / BehaviorParam
rows and into the regulation's effect-resource manifest, so dropping
back to vanilla NR's `sfxbnd_c0000.ffxbnd.dcx` would require
re-authoring every chr's broken effect references in regulation —
far worse than shipping MMV's bundle.

This is the same "MMV is the canonical asset base" pattern as
`bundled_regulation/regulation.bin`, `bundled_aicommon/`, and
`bundled_material/`. The five bundles travel together.


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
