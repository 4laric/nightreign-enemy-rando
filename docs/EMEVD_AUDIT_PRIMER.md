# EMEVD cluster-anim audit — primer

You're being asked to help with a structured audit of decompiled Nightreign
EMEVD scripts. This primer catches you up on the project, the specific bug
class we're hunting, what infrastructure already exists, and what output
shape the audit needs to produce.

## Who I am

Alaric — I maintain `nightreign-enemy-rando`, a Python toolchain that
swaps enemy NPCs in From Software's *Elden Ring: Nightreign* by modifying
MSB (map static-bin) Parts. Currently on **v0.23.72-late**. I edit on the
go from a bus on mobile sometimes; assume technical depth and skip
hand-holding. I prefer decisive recommendations over options-paralysis,
and prose-minimal answers. Annotate code changes with a v-version tag +
rationale + provenance. When in doubt, paraphrase what I said back to me
before executing.

## The project in one paragraph

The randomizer modifies MSB Parts to swap which c-prefix (NPC archetype)
occupies each slot in a map, while preserving entity IDs and positions.
Most encounter event handlers in NR's EMEVD reference entities by
entity_id, so they survive the swap unchanged. The bugs we have to fix
are handlers that reference *what kind of NPC* is at that entity rather
than just the entity itself.

## The specific bug class — cluster-anim CTDs

Some EMEVD scripts call:

```
ForceAnimationPlayback(entity_id, animation_id, false, false, false);
```

where `animation_id` is a number from one specific c-prefix's animation
bank. When the randomizer swaps a different chr in at that entity_id, the
new occupant's anim bank may not have that animation ID → game crashes
when the script fires.

The canonical empirical case: **m38_00 cathedral**, seed 940574, my
playtest. Four c3620 Oracle Envoy (Large) slots at part indices 11-14
got swapped to c3010/c4352/c3460/c4355 (all sane M-humanoid picks
individually). The cathedral cluster-dance encounter event invokes
`ForceAnimationPlayback` against c3620's anim bank on those four entity
IDs. With four different chrs at those entities, the anim IDs don't
resolve → CTD.

This is a *type-coupled* EMEVD call: the script is hard-bound to a
specific chr's anim catalog. Compare type-AGNOSTIC calls like
`SpawnNPC(c4481_at_position)` — those work great under randomization,
they just spawn whatever c4481 became. The Miranda Blossom death-spawn,
Tibia Mariner skeleton summons, Evergaol-style mass spawns all use
type-agnostic patterns and produce satisfying chaotic randomized mobs.

## The design call

I want to keep the chaos-mob aesthetic that type-agnostic spawns produce
and eliminate the type-coupled cluster-anim CTDs by patching them at the
source (the EMEVD), not by working around them in the engine. Once those
calls are patched out (removed or no-op'd), the cluster-protection
machinery in the engine (cluster_aware mode, `_cluster_only` tags, per-
map source/target excludes for c5110/c4181/c3610/c3620) becomes
unnecessary and gets swept away in a follow-up engine cleanup.

The end state I'm aiming for: every Part rolls independently. If a four-
chr cluster slot gets swapped to four different chrs, that's fine; they
fight independently with whatever AI each one has. No choreographed
cluster-dance, just chaos. The cluster-dance was a vanilla flourish, not
load-bearing for the encounter to be playable.

## Existing infrastructure

### `emevd_patch.py`

I already have a sophisticated EMEVD patcher. It operates on DarkScript3-
decompiled `.emevd.dcx.js` files and ships 68 substitutions across 5
patch families:

- `death_timeout` — adds 5-second timeout to `CharacterDead(eid)` waits
  (handlers 90005860, 90005861)
- `permissive_boss_wake` — boss healthbar / BGM activation accepts
  Recognition / Alert / damage-taken instead of just Combat AI state
  (handlers 90015000, 90015030)
- `permissive_spawn_emerge` — **most relevant to our audit** — inserts
  `EnableCharacterAI(eid)` after every `ForceAnimationPlayback` in spawn-
  handler contexts so the AI loop activates even when the swapped chr
  can't play the expected emerge anim. Covers 90085002 (272 call sites),
  90015310 (11), 90015160/163/164 (27 each), 90015300, 90015401,
  90085012/101/201, 90035202/204/213/220-232/244/247/250/262/263/286,
  90065009, 90075820/401, 90005200/201/211/221, 90005705/706/720/725/726/760
- `nb_speffect_wait_timeout` (v0.24.74) — 10s fallback on
  WaitFor(CharacterHasSpEffect(...)) in NB-arena scripts

Patches gate on `filename.startswith('common_func')` to avoid touching
per-map EMEVDs. There's also an `audit` subcommand:

```
python emevd_patch.py audit <input_js_dir>
```

That enumerates `ForceAnimationPlayback` call sites with surrounding
context. Use this.

### `patched_emevd/`

Pre-patched per-map files for inline events that can't be reached by
`common_func` patches:

| Map | What it patches |
|-----|-----------------|
| `m30_30_00_00.emevd.dcx` | Guardian Golem (Fort) stand-up cinematic + arena collision proxies |
| `m38_10_00_00.emevd.dcx` | **Cathedral interior 2 inline encounter / cutscene scripts** — use this as the reference patch shape! |
| `m60_43_37_00/10/20.emevd.dcx` | Three time variants of the same overworld cell |

The `.js` source for each is in the same directory. **`m38_10` is your
single best reference** — it's the same kind of cathedral inline event
scripts as the m38_00 case we need to patch, just for a different tile.
Read its `.js` file to see what the cluster-dance call sites look like
before patching.

## The audit task

### Output I need

For every `ForceAnimationPlayback` call site you find in the uploaded
`.emevd.dcx.js` corpus, produce a row in a catalog:

```
map           = source file (e.g. "m38_00_00_00")
event_id      = the $Event(N, ...) block this is inside
instruction   = line number or local instruction index
animation_id  = the literal anim ID or variable name passed
target_entity = entity_id arg
expected_cprefix_for_anim = which c-prefix this animation belongs to
                            (inferred from existing per-map context
                            or known cathedral/Maris/Alabaster mapping)
classification = (a) cluster-dance / (b) spawn-emerge / (c) other
```

### Classification scheme

**(a) Cluster-dance** — what we're hunting. Type-coupled anim calls in
coordinated multi-entity encounters. Signal: the same event block calls
`ForceAnimationPlayback` on 2-8 different entity IDs in sequence,
typically with anim IDs from the same c-prefix's bank. The event also
usually has `SetCharacterAIState` or similar coordinated-behavior calls.
Examples we expect to find:
- cathedral m38_00 (4-chr Oracle Envoy dance)
- m49_20 Twin Alabaster Lords duo (per oops_v3.py comment at line 408)
- m60_xx Maris cluster (c5110/c4181/c3610/c3620 — may be cluster-dance
  OR may be pure event-chain coupling; the audit will tell us)

**(b) Spawn-emerge** — already handled by `permissive_spawn_emerge` in
`emevd_patch.py`. Signal: the event is a spawn handler that calls
`EnableCharacter` → `ForceAnimationPlayback` → (no `EnableCharacterAI`).
The existing patch inserts the missing `EnableCharacterAI` after the
anim call. **Don't add new patches for these — they're covered.** Note
them in the catalog so we have the full picture.

**(c) Other** — single-entity scripted intros, boss-arena cutscenes,
ambient anims. May need separate patches; may already work; flag for
case-by-case review.

### What I expect the output to look like

A markdown table or JSON list with the columns above. If the corpus is
large (it will be — NR has ~200 .emevd files), it's OK to summarize at
the per-map level after we have the raw catalog. Bucket counts by
classification, then drill into class (a) entries individually.

### How to start

1. Read `emevd_patch.py`'s `audit` subcommand source to see what format
   it already produces, then either use it as-is or extend it.
2. Read `m38_10_00_00.emevd.dcx.js` (the already-patched cathedral
   reference) to learn the shape of a cluster-dance call site.
3. Sweep the uploaded corpus, classify, build the catalog.
4. Surface anything unexpected — surprise non-anim instructions that
   look type-coupled (`SetCharacterTransformation`, `WarpCharacter` with
   literal coords, `ForceAttack` with chr-specific moveset IDs, etc.) are
   worth flagging too.

## What's out of scope

### Mount/rider pair handling

c4050+c4060 Kaiden Sellsword + Horse, c3150+c3160 Funeral Steed,
c4061+c4363 Lordsworn Knight + Horse. These cluster sites also fail
under randomization but the mechanism is different — *riderless mount
has no AI*, *mountless rider has no mount*, not anim-bank-mismatch.
They stay handled by the engine's pair excludes; the EMEVD audit doesn't
help them. There's a separate TODO for "Kaiden chaos comedy" that I'll
work on after the audit.

### Phase 2 — actual patching

Once we have the catalog, the next session ships DarkScript3 patches.
That needs my Windows box for the `.NET` tool. The audit phase you're
helping with is fully doable in a Linux/macOS Python environment.

### Phase 3 — engine cleanup

After patches ship and test, I'll do a separate session to delete the
cluster-protection scaffolding from `oops_v3.py` (~200-400 lines).
Already filed in the TODO.

## Anchor cases for the audit

Sanity-check the audit hits these expected cases:

1. **m38_00 cathedral cluster-dance** (seed 940574 reference). Should
   surface 4+ `ForceAnimationPlayback` calls in a single event block on
   entity IDs that mapped to vanilla c3620 part indices 11-14.

2. **m49_20 Twin Alabaster Lords**. Same pattern. The exclude comment in
   `oops_v3.py:408` describes it: "same failure mode as the cathedral
   c3620 cluster fix above."

3. **m38_10 cathedral interior 2** — already patched, so the audit
   should either show clean (patches applied) or show the original
   call sites for reference comparison depending on whether you're
   auditing the patched or vanilla version. Verify which corpus you got.

4. **m60_xx Maris procedural tiles** — c5110/c4181/c3610/c3620. The
   audit will tell us whether this is cluster-dance (type-coupled anim
   calls) or pure event-chain coupling (one chr triggers another's
   spawn event). Different remediation if it's the latter.

## Coding/output norms

- Write short Python where useful for parsing/summarizing the catalog.
- If you produce a JSON catalog, give it a self-documenting top-level
  schema (`version`, `generated_at`, `n_files`, `entries`, etc.) so
  Phase 2 has structured input.
- Markdown summary on top, with the full structured catalog either
  embedded or saved to a file and presented via the standard file-share
  flow.
- When you find something interesting (a class (a) site that doesn't
  match a known cluster, an `animation_id` that's variable-bound rather
  than literal so the binding is implementation-defined, etc.), flag it
  inline — don't bury it in the catalog.

## TL;DR

Find every `ForceAnimationPlayback` in the uploaded `.emevd.dcx.js`
corpus. Classify each as (a) cluster-dance / (b) spawn-emerge /
(c) other. Output a catalog. Confirm the known anchor cases (m38_00
cathedral, m49_20 Alabasters, m60_xx Maris). Flag the surprises. Don't
write patches yet — just the catalog.

That's the audit.
