# bundled_material

MMV's material binders for end-user deployment.

## What's here

| File                              | Size   | Source | Purpose                                                                |
|-----------------------------------|--------|--------|------------------------------------------------------------------------|
| `allmaterial.matbinbnd.dcx`       | ~3.4 MB | MMV    | Material/shader registry — covers base + cross-game / heritage chrs   |
| `allmaterial_dlc01.matbinbnd.dcx` | ~1.0 MB | MMV    | DLC material/shader registry — covers SoTE heritage chrs              |

These are **MMV's `allmaterial.matbinbnd.dcx` files**: the shader
and material binders that almost every chr model's surface references
at render time. MMV's versions are supersets of vanilla NR's — they
carry the MATBIN entries that cross-game and SoTE-heritage chr models
need (ER DLC bosses' shaders, MMV cross-game chrs' custom materials,
etc.).

## Why we bundle this

`dev/chr_asset_resolver.py` declares `material/` as a `DIR_DEPLOYED`
shared dep — any heritage chr import flow checks for its presence at
the package's `material/` subdir, because heritage chr models that
reference MATBINs outside NR's base registry fail to render correctly
without it:

- Models reference missing material slots → broken / black / invisible
  surfaces on rendered chrs, or
- The MATBIN lookup fails outright → model fails to load, chr spawn
  silently no-ops or CTDs depending on the asset path.

The required MATBIN IDs are baked into the chrs' FLVER model metadata
and into the regulation's effect-resource manifest, so dropping back
to vanilla NR's `allmaterial.matbinbnd.dcx` would require re-authoring
every cross-game / heritage chr's material references — far worse
than shipping MMV's bundle.

This is the same "MMV is the canonical asset base" pattern as
`bundled_regulation/regulation.bin`, `bundled_aicommon/`, and
`bundled_sfx/`. The five bundles travel together.

## Deployment

Drop both files into your me3 mod profile under the `material/`
subdirectory:

```
<me3 profile>/<package>/material/allmaterial.matbinbnd.dcx
<me3 profile>/<package>/material/allmaterial_dlc01.matbinbnd.dcx
```

me3 substitutes them at load time. Nightreign reads material binders
from these copies instead of the install's vanilla bundle.

## Verifying integrity

Format: DCX-compressed MATBINBND archive. Expected sizes approximately
3.4 MB (main) and 1.0 MB (dlc01). Significantly smaller suggests a
truncated download. First 4 bytes should be `DCX\0`.

```
ls -lh bundled_material/allmaterial.matbinbnd.dcx        # ~3.4 MB
ls -lh bundled_material/allmaterial_dlc01.matbinbnd.dcx  # ~1.0 MB
head -c 4 bundled_material/allmaterial.matbinbnd.dcx | od -An -c
# Should show: D C X \0
```

## Regeneration

If MMV ships a material update (new cross-game chrs with new
materials, or fixed MATBIN references), drop the new
`.matbinbnd.dcx` files in here, replacing the existing ones. No code
change needed — the bundle installer reads whatever's in this
directory (the `bundled_material` entry in `BUNDLED_INSTALLS` has no
extension filter; everything that isn't `README.md` or a dotfile
copies).

A future Python-side MATBIN patcher would let us layer rando-specific
material tweaks on top of MMV's bundle (the same way
`bundled_regulation/` layers param patches on top of MMV's
regulation), but that's not in scope today. For now the bundle ships
verbatim from MMV.
