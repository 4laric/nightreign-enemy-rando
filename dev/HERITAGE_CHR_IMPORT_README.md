# Heritage chr/ asset import workflow

When the rando places a chr in a shuffled MSB, NR's runtime tries to load that
chr's `chrbnd.dcx` / `anibnd.dcx` / `behbnd.dcx` from the game's `chr/` folder.
If the file isn't there, the cell CTDs on approach.

NR's vanilla `chr/` folder ships ~209 c-prefixes — the base game roster.
But the rando's pool includes ~47 "heritage" chrs imported from ER + SOTE
(Bloodfiend, Curseblade, Dancing Lion, Imp, Man-Fly, Skeleton, etc.) plus
the 12 c2xxx ER NB-tier bosses we authored in `er_heritage_imports.json`.
Those chr files are NOT in vanilla NR — they need to be copied in from your
unpacked Elden Ring install.

This folder contains the tool + per-source attribution to do that cleanly,
into a me3 mod profile (NOT into your vanilla NR install).

## Why me3 profile, not the NR install

me3 (Mod Engine 3) layers profile files OVER vanilla at runtime without
modifying vanilla files. Putting heritage chrs in `me3-profile/chr/` means:

  - Vanilla NR install stays clean — uninstall the mod by removing the
    profile, no residue.
  - Profile is portable — zip the profile, share with someone else who has
    ER installed and they can use it.
  - No conflict with NR patches — when NR updates and replaces files in its
    own chr/ folder, your me3 profile chrs aren't touched.

## Files needed per chr

For each c-prefix, the full asset set is the glob `cXXXX*`:

```
cXXXX.chrbnd.dcx        REQUIRED  model + skeleton
cXXXX.anibnd.dcx        REQUIRED  animation bundle
cXXXX.behbnd.dcx        REQUIRED  behavior bundle (HSM logic)
cXXXX_h.texbnd.dcx      RECOMMENDED  high-res textures
cXXXX_l.texbnd.dcx      RECOMMENDED  low-res textures (LOD)
cXXXX_aXX.anibnd.dcx    SOMETIMES   additional animation banks
cXXXX_divNN.anibnd.dcx  MULTI-PHASE multi-phase boss anim splits
```

The import tool copies ALL files matching `cXXXX*` from source → target,
which catches all of these without needing per-chr knowledge.

## Tool usage

```bash
# Step 1: see what's missing for a given run (no source needed)
python dev/heritage_chr_import.py \
    --target /path/to/me3-profile/chr \
    --diagnose-spoiler /path/to/_spoilers.json

# Step 2: copy what's needed from your unpacked ER install
python dev/heritage_chr_import.py \
    --source "/path/to/elden-ring-unpacked/chr" \
    --target /path/to/me3-profile/chr \
    --from-spoiler /path/to/_spoilers.json

# Step 3 (alternative): explicit prefix list for fine control
python dev/heritage_chr_import.py \
    --source "/path/to/elden-ring-unpacked/chr" \
    --target /path/to/me3-profile/chr \
    --prefixes c5040,c5080,c5081,c5870,c5900

# Add --dry-run to preview without copying
# Add --overwrite to replace files that already exist in target
```

## Source attribution — which game ships which chr

The 43 missing c-prefixes for seed 711300 break down as:

| Source | Count | Examples |
|--------|-------|----------|
| ER base game | 20 | Skeleton (c3510), Clayman (c3750), Warhawk (c4210), Disciple of Rot (c4385), Mohg the Omen (c4800), Avionette (c3860), Cleanrot Knight (c3800)... |
| SOTE (ER DLC) | 16 | Curseblade (c5040), Death Knight (c5070), Bloodfiend (c5080), Chief Bloodfiend (c5081), Imp (c5870), Man-Fly (c5900), Messmer Soldier (c5830), Ghostflame Dragon (c5860)... |
| Wildlife (likely SOTE) | 2 | Bear variant (c6031), Goat (c6060) |
| Probably ER | 2 | Stray (c5522/c5523) |
| ER heritage v1 (this project) | 12 | Margit (c2010), Rennala (c2030/c2031), Astel (c2160), Godrick (c2190/c2191)... |

ER's `chr/` folder (unpacked from `Game/Data0.bdt`+`Data0.bhd`) has all of
these. SOTE chrs ship in the same folder if you have the DLC installed and
unpacked along with the base game.

See `heritage_chr_attribution.json` for the full per-c-prefix attribution.

## Caveat: ER → NR format compatibility

ER's chr files are loaded directly by NR's runtime — both games use the same
engine generation. No format conversion needed for the typical case.

If you're copying from older FromSoft games (DS3, Sekiro, BB, DeS), those
need format conversion. The heritage_pack mod ecosystem has tooling for that
— run the converter against your DS3/etc. install first, then point this
tool's `--source` at the converted output.

For seed 711300 specifically, all 43 missing chrs are ER-format, so a direct
copy from your unpacked ER `chr/` works.

## Sanity check after import

After copying, re-run the diagnostic to confirm zero gaps:

```bash
python dev/heritage_chr_import.py \
    --target /path/to/me3-profile/chr \
    --diagnose-spoiler /path/to/_spoilers.json
```

Should report `Missing from target: 0`. Then load the seed in NR — fort
approach should not CTD.

## Future: per-seed pre-flight check

Worth adding to the GUI: a "verify chr/ inventory" button that runs the
diagnostic against the current target dir + last-rolled spoiler before
the user launches NR. Catches gaps before the in-game CTD instead of after.
