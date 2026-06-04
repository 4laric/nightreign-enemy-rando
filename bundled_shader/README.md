# bundled_shader

MMV's shader binders for end-user deployment.

## What's here

| File                                     | Size    | Source | Purpose                                                        |
|------------------------------------------|---------|--------|----------------------------------------------------------------|
| `shaderbdle_dlc01.shaderbdlebnd.dcx`     | ~39 MB  | MMV    | DLC shader binder — covers SoTE heritage chrs                  |

This is **MMV's `shaderbdle_dlc01.shaderbdlebnd.dcx`**, the compiled
shader programs that ER-DLC and cross-game chr materials reference
at render time. Where `bundled_material/allmaterial*.matbinbnd.dcx`
is the *registry* mapping material names → shader IDs + parameters,
this is the *shader programs themselves* — the actual HLSL→DXBC
bytecode the GPU runs.

The two layers travel together: a material entry that references
shader ID `S_xxxx` is dead if `S_xxxx` isn't in the loaded shader
binder. NR's vanilla shader binder is missing entries that the
ER-DLC heritage chrs need, so dropping MMV's DLC shader binder
in alongside MMV's material binder unblocks the affected chrs.

## Why we bundle this

Playtest-confirmed dependency. Without MMV's
`shaderbdle_dlc01.shaderbdlebnd.dcx` deployed alongside the material
binders, heritage chrs whose materials reference DLC-introduced
shader IDs render with broken / black surfaces, missing visual
effects, or fail to load entirely — the material registry resolves
the shader ID, the shader binder can't, the model renders without
its intended shading pipeline.

This is the same "MMV is the canonical asset base" pattern as
`bundled_regulation/`, `bundled_aicommon/`, `bundled_material/`,
and `bundled_sfx/`. The five bundles travel together.

## Deployment

Drop `shaderbdle_dlc01.shaderbdlebnd.dcx` into your me3 mod profile
under the `shader/` subdirectory:

```
<me3 profile>/<package>/shader/shaderbdle_dlc01.shaderbdlebnd.dcx
```

me3 substitutes it at load time. Nightreign reads the DLC shader
binder from this copy instead of the install's vanilla version.

## Verifying integrity

Format: DCX-compressed shader binder archive. Expected size
approximately 38–40 MB. Significantly smaller suggests a truncated
download. First 4 bytes should be `DCX\0`.

```
ls -lh bundled_shader/shaderbdle_dlc01.shaderbdlebnd.dcx   # ~39 MB
head -c 4 bundled_shader/shaderbdle_dlc01.shaderbdlebnd.dcx | od -An -c
# Should show: D C X \0
```

## Regeneration

If MMV ships a shader update (new cross-game chrs with new shader
programs, or fixed shader references), drop the new `.dcx` in here,
replacing the existing file. No code change needed — the bundle
installer reads whatever's in this directory.

## Why only DLC, not base?

The base shader binder (`shaderbdle.shaderbdlebnd.dcx`, ~hundreds of
MB) hasn't been needed in playtest so far — vanilla NR's base shader
binder covers everything cross-game / heritage chrs need at the
non-DLC layer. Only the DLC-introduced shader IDs were missing, and
those are all in the DLC binder. If a future playtest finding flips
this, the base binder gets added as a second file in this directory
and the installer picks it up automatically (the installer iterates
every file in the bundle dir).
