# `title_pool.json` — guide

Stub-shipped in v0.24.14 for future use. **Not yet wired into the
runtime path** — the rewriter has a `compose_name()` helper that
reads this file and is fully tested, but no caller invokes it yet
because per-boss FMG splicing isn't reliable yet. When splice is
unblocked, `decide_rewrites` will flip over to call `compose_name()`
and these titles will start appearing on shuffled healthbars.

## Format

```json
{
  "_doc": "...",
  "_pool_source_credits": { ... },
  "titles": [
    "the Nightlord",
    "Beast of Night",
    "The Dread Pirate {r}",
    "{o} 'The Rock' {r}",
    "and more"
  ]
}
```

Only the `titles` key is functional — everything starting with `_`
is documentation for human readers. The runtime ignores them.

## Title styles

Two styles, distinguished by whether the string contains placeholders:

### Epithet (no placeholders)

Plain string. Appended after the name with a comma:

```
"Beast of Night"  →  "Tibia Mariner, Beast of Night"
"and more"        →  "Tree Sentinel → Banished Knight, and more"
```

For vanilla→vanilla swaps the original-name appears before an arrow.
For heritage / same-c-prefix cases the arrow is dropped:

```
heritage:     None / Mohg + "Lord of Blood"        →  "Mohg, Lord of Blood"
same-prefix:  Banished Knight / Banished Knight + "the Grafted"
                                                   →  "Banished Knight, the Grafted"
```

### Template (contains `{r}` and/or `{o}`)

The template **replaces** the whole name. Placeholders:

- `{r}` — replacement name (what's actually fighting now)
- `{o}` — original name (vanilla slot's display name)

```
"The Dread Pirate {r}"  →  "The Dread Pirate Tibia Mariner"
"'Stone Cold' {r}"      →  "'Stone Cold' Banished Knight"
"{o} 'The Rock' {r}"    →  "Tree Sentinel 'The Rock' Tibia Mariner"
```

Heritage / no-original case: `{o}` falls back to the replacement
name so the output doesn't have a stray leading space. So
`"{o} 'The Rock' {r}"` for a Mohg heritage import becomes
`"Mohg 'The Rock' Mohg"` — repetitive but parseable.

Templates do **not** get the `<name>,` prefix that epithets get.
The template is the whole name.

## Editing

- **Add an entry**: just append to the `titles` array. No version bump
  needed; the loader doesn't validate the list shape beyond "must
  be a non-empty array of strings."
- **Remove an entry**: delete the line. Be aware that if the title
  was already attached to a (original_c, replacement_c) pair in a
  previously-generated seed, regenerating that seed will pick a
  different title from the new shorter pool — your "Tibia Mariner,
  Beast of Night" might become "Tibia Mariner, the Grafted." Same
  seed, different output. That's fine for variety but unexpected
  if you're trying to reproduce a friend's exact run.
- **Weight an entry heavier**: list it multiple times. The default
  pool ships with `"and more"` three times so it shows up in roughly
  3/25 ≈ 12% of healthbars. Tune to taste.

## Selection logic

For each (original_c_prefix, replacement_c_prefix) pair in a run,
`compose_name` hashes `(original_c, replacement_c, run_seed)` and
indexes into the titles array modulo its length. Same pair in the
same run always gets the same title; different runs may pick
differently because the seed differs.

This means:
- Per-pair stability within a run — once you see "Tree Sentinel →
  Tibia Mariner, Naturalborn of the Void" you'll see it again at
  every other Tree-Sentinel-slot→Tibia-Mariner instance in the run.
- Different (original, replacement) combos roll independently — the
  Tree-Sentinel-slot Tibia Mariners get one title, but Banished-
  Knight-slot Tibia Mariners get a different one.
- Reseed for variety — same seed gives same titles.

## Format of the composed name

`compose_name` produces:

- **Vanilla → vanilla** (most common, ~108/158 healthbars in a typical
  run):
  `<original_name> → <replacement_name>, <title>`
  e.g. `Tree Sentinel → Tibia Mariner, Naturalborn of the Void`
- **Heritage / no-vanilla-original** (~50/158, cross-game imports
  like ER chrs and MMV):
  `<replacement_name>, <title>`
  e.g. `Mohg, Lord of Blood`
- **Same c-prefix on both sides** (rare — when a Banished Knight
  shuffles to a Banished Knight, which happens by chance):
  `<replacement_name>, <title>`
  No arrow because there's no actual swap.

The healthbar text widget in NR clips around 40-45 characters
depending on font kerning, so long compositions will get cut.
Default policy: let them clip. If chaos isn't desired later, we can
add length-aware title selection (long pair → pick short title).

## Source credits

The default pool draws from three buckets:

1. **Vanilla NR comma-tails** — epithets that appear after a comma
   in the stock NpcName.fmg. Game-flavor-coherent and instantly
   recognizable to NR players.
2. **ER classics** — iconic Souls epithets borrowed because they're
   already in players' heads.
3. **Meta / inside jokes** — `"and more"` is the legendary vanilla
   spreadsheet typo (entry `902130014` is literally "Crucible Knight
   and more"). Used as a title, it converts every fight into a
   gentle riff on the original mistake.

Feel free to add your own. They don't need to be epithets — anything
that fits grammatically after a comma works. Some ideas if you want
to riff:

- Made-up but Soulslike: `"the Forgotten Bell"`, `"Devourer of Lesser
  Things"`, `"of the Quiet Light"`
- Anti-epic: `"Probably"`, `"or so they say"`, `"allegedly"`
- Roguelike-style: `"the Lucky"`, `"the Unfortunate"`,
  `"of the Bad Roll"`
- Self-aware: `"as randomized"`, `"don't ask"`,
  `"the Spreadsheet's Choice"`
