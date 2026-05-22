# Known issues / wontfix

Behaviors that are visually rough or thematically odd but not crash-causing
or game-breaking. Tracked here so they don't get re-investigated as bugs
every time someone notices them. Listed in chronological order by when
they were spotted.

Criteria for "wontfix":
- Not a CTD or softlock
- Doesn't block progression
- Fixing it would require disproportionate effort (per-chr scripted-event
  patching, EMEVD authoring for one specific case, etc.)
- Or: the fix would over-restrict the rando in ways that hurt the variety
  the user wants more than the visual roughness hurts the experience

If a workaround is cheap (per-chr exclusion from a target set, narrow
slot blacklist, etc.) it should go in the engine instead of here.

---

## Heritage chrs idle-roaring at player

**Symptom:** Heritage chr (typically a `c58xx` SOTE creature like Great
Red Bear) spawns at a slot, but stands still and roars / idles instead
of engaging. Player can walk up, get within attack range, and the chr
just bellows menacingly without aggro-transitioning.

**First sighting:** v0.23.11, Great Red Bear (c5820) at what looks like
a Liurnia outskirts cell — bear standing on hind legs, roaring,
non-aggressive. (See `1778210248399_image.png`.)

**Suspected cause:** Heritage chrs imported from SOTE rely on EMEVD
trigger volumes or scripted aggro events that don't exist at the
randomized slot. The chr's behavior graph is loaded fine, the model
renders, idle anims play — but the aggro-state transition that the
chr's AI expects is gated behind a script that didn't get imported.
This is the same failure family as the c4490 Jar Warrior "arms-crossed"
NB-anchor issue (see `V3_NIGHT_BOSS_ANCHOR_BLACKLIST` in `oops_v3.py`),
just at non-NB slots and intermittent.

**Why wontfix:**
- Not a CTD; the chr just looks dramatic and harmless
- Doesn't block player progression (you can walk past or ignore)
- Fixing properly requires per-slot EMEVD authoring (define aggro
  trigger volumes for every randomized slot a heritage chr might land
  at) — combinatorial explosion across 1000+ slots × 47 heritage chrs
- Adding all `c58xx` to a "needs scripted intro" exclusion set would
  remove their main-pool participation entirely and gut the variety
  benefit of the heritage_pack import
- Empirically the failure rate seems low — most heritage chrs aggro
  fine when player approaches, this is occasional

**If it gets worse / more common:** revisit and consider per-chr
opt-out from non-arena slots, similar to how
`V3_NIGHT_BOSS_ANCHOR_BLACKLIST` keeps c4490 out of NB slots
specifically. Would need playtest data on which c-prefixes are
worst offenders.

**Aesthetic upside:** It's actually pretty cool to walk into a clearing
and have a giant bear standing on its hind legs roaring at the sky.
If you don't engage it, it's effectively a piece of dramatic scenery.
Leaving as wontfix in part because the failure mode is more
"atmospheric" than "broken."

---

## NB-tier chr idle at Crater/shifting-earth Cathedral slots

**Symptom:** A Night-Boss-tier chr (Bell Bearing Hunter, etc.) spawns at
a Crater Cathedral / Noklateo Cathedral entrance, HP bar shows correctly
on approach (registered as hostile), but the chr stands frozen in combat
pose (sword raised, shield up) and never aggro-transitions. Player can
walk circles around it, hit it, and only THEN it sometimes wakes up.

**First sighting:** v0.23.11, c3100 Bell Bearing Hunter at
m60_42_36_50.msb pi=100 (Crater Cathedral entrance). Source slot was
c4355 Mausoleum Knight (Noklateo). User screenshot:
`1778210532176_image.png`.

**Suspected cause:** This is the **inverse** of the c4490 Jar Warrior
issue. c4490 is an NPC-style chr that doesn't aggro at NB anchors
because it's expecting a quest dialogue trigger. The Bell Bearing
Hunter case is the opposite — c3100 IS a proper NB-tier chr whose
behavior graph EXPECTS an NB-anchor intro (fog wall, cinematic, aggro
trigger). The Crater shifting-earth Cathedral tile has the geometry of
a boss arena but doesn't fire the NB-anchor scripted intro because
shifting-earth tiles use their own event scripts, not the standard NB
anchor pattern. Result: chr loaded with NB-intro behavior, slot
provides no NB-intro trigger, chr sits in pre-aggro state forever (or
until directly damaged).

**Why wontfix:**
- Not a CTD; chr is just docile until attacked
- Doesn't block progression (player can hit it to wake it up, or skip)
- Fixing properly requires either:
  - EMEVD authoring per shifting-earth Cathedral slot to fire NB intros
  - Per-chr identification of "needs NB scripted intro to function" and
    blocking those chrs from shifting-earth slots specifically
- The per-chr blacklist approach would need playtest data to identify
  which c-prefixes break this way; piecemeal blacklisting risks
  whack-a-mole as new heritage / vp_v1 chrs land at these slots
- Crater/Noklateo shifting-earth slots are a small fraction of total
  placements; failure rate is low

**Related:** `V3_NIGHT_BOSS_EXCLUDE_TARGETS` (currently `{c4490}`) is
the existing mechanism for the inverse problem (chrs that fail AT NB
anchors). A symmetric mechanism could exist —
`V3_NB_INTRO_DEPENDENT_TARGETS` that blocks chrs from shifting-earth
boss slots — but the cost (roster restriction) outweighs the benefit
of avoiding the rare frozen-pose case.

**Workaround for the player:** smack the chr once with anything; aggro
state usually transitions on damage taken even when the intro trigger
didn't fire. Slightly anticlimactic for an NB-tier chr but functional.

**If it gets worse:** revisit with playtest data on which c-prefixes
break specifically at m60_42_36_xx (Crater) and m60_42_37_xx (Noklateo)
boss-arena slots, and consider per-chr blacklist or shifting-earth
Cathedral source-slot exclusion from NB-tier targets.

## Multi-entity arena test_mode spawn (m48_50, m48_60, m48_80, m48_20, m49_25, m49_28)

The test_mode arena generator (`dev/generate_test_mode_arenas_v8.py`)
emits per-arena EMEVD overlays that hijack the boss-spawn lifecycle so
you can drop into N1 / N2 immediately, kill the boss, and proceed to
day-advance without playing through the full expedition. Works
reliably for 19 of the 24 NR boss arenas. **Does not work** for the
six arenas listed above; they fall back to vanilla `.emevd.dcx` (no
overlay shipped) and use vanilla's full expedition flow.

### What's different about the failing six

They use multi-entity boss-spawn common_funcs instead of the simple
90065910 family the working ones use. Quick reference:

  m48_50 (DTS), m48_60 (TS):      90065050
  m48_80 (Godskin Duo):           90065131
  m48_20 (two-phase boss):        90065090
  m49_25:                         90065121
  m49_28 (Twin Gargoyles):        90065110

Each of these orchestrates Disable → wait-for-flag → SpEffect-wakeup on
sub-bosses → ForceAnimationPlayback on a model proxy → EnableCharacter
on a "lead" entity plus helpers → DisplayBossHealthBar links per
entity. Tightly coupled to MapVariation 0/1/2 transitions and to the
per-arena helper events (e.g. `48602810` in m48_60) that get deleted
when our overlay replaces the `.emevd` file.

### What we tried

**v5.6 (inline manual spawn):** DisableCharacter at map-load,
WaitFor(PlayAreaCurrentTimeInRange + InArea), EnableCharacter, inline
death observer. Worked for single-entity arenas where chrEntityId ==
chrEntityId2 (XXXX0800). Failed for multi-entity — boss never appeared,
"no wave, no healthbar, circle closed."

**v6 (wrong-entity hypothesis):** swapped EnableCharacter target from
the healthbar-binding entity (XXXX0800) to the "lead" entity from
90065911's chrEntityId (XXXX5210 / XXXX5800). Same failure.

**v6.1 (missing-anim hypothesis):** added
`ForceAnimationPlayback(boss, 20026)` before EnableCharacter to provide
the wake-up cue that vanilla's spawn fns include. Same failure.

**v7 (vanilla-preservation):** preserved vanilla's entire Event 0
machinery (all the `$InitializeCommonEvent` calls for 90065050,
90065911, helpers, asset linkages), stripped only the
`IsMapVariation(0/1)` lobby branches and the `90015442` arena-entry
trigger, added an Event 50 that fires the arena-active flag on our
InArea trigger. Hypothesis: by setting the flag, vanilla's preserved
spawn machinery would run its proper sequence. Same failure.

**v8 (engine-sync via 90015442):** restored the v5.3 pattern that
worked for Tree Sentinel pre-regression: `$InitializeCommonEvent(0,
90015442, area, flag)` then `WaitFor(EventFlag(flag))`, on the theory
that 90015442 fires the flag at engine-determined night-onset and
synchronizes our overlay to a state where EnableCharacter would
actually manifest the boss. Same failure for m48_80; never tested
m48_60 specifically in v8.

**v9 (MMV pattern):** vanilla NR uses `90015000` for 102 open-world
field bosses — a much simpler pattern that frames the encounter
(healthbar + BGM on proximity) without any Disable/Enable. MMV
adopted this for their custom arenas. Tried it: assumed the boss is
already MSB-Default-Enabled in MapVariation 2, used only 90015000 +
90015030 + 90015002 with no entity lifecycle calls. Boss didn't appear,
confirming the MSBs have these bosses Default-Disabled in the active
variation.

### Why we believe it's unsolvable from EMEVD alone

The v9 result is the diagnostic. Vanilla NR's MSBs for these arenas
have the boss Default-Disabled in MapVariation 2 (otherwise v9 would
have spawned them). That means `EnableCharacter` from an overlay is
necessary. But `EnableCharacter` from an overlay doesn't fully manifest
these bosses — likely because the MSB-Part coupling with sub-bosses /
helpers / wake-anim targets requires the full
`90065050/090/110/121/131` orchestration to run in its intended order,
including SpEffect 13748 wake-ups on sub-bosses, helper invincibility
toggles, ForceAnimationPlayback on a specific proxy entity, and
per-arena helper events (48xx2810 etc.) we delete when we overlay the
`.emevd`.

We could in principle preserve those per-arena helpers, but they're
parameterized events initialized by callers we never identified (not
found in any `.emevd.js` we have; likely initialized from cutscene
scripts or a runtime path outside the EMEVD dump). Without knowing
their init params we can't re-init them.

The path that would crack this is MSB-level: modify the vanilla MSB
parts for these arenas to set them Default-Enabled (like MMV does),
then use the simple 90015000 pattern. That's outside the scope of the
EMEVD-only test_mode generator.

### Why this is fine

Rando still applies to these six arenas via the NpcParam swap at the
standard boss entity slots — independent of test_mode. The expedition
plays normally, vanilla's spawn machinery runs, the engine spawns
whatever chr the rando assigned to slot XXXX0800. The only thing lost
is the test_mode "skip to boss" shortcut for these specific arenas;
testing rando outcomes on them requires playing the expedition.

The other 19 arenas continue to use test_mode overlays normally.

### Reopen path: MSB modification + v9 EMEVD overlay

The investigation above ruled out EMEVD-only solutions. The path that
would actually crack multi-entity test_mode spawn is MSB modification.
This section documents the concrete recipe so next-session-us doesn't
have to re-derive it.

**The MMV reference pattern (verified by inspecting m49_53 MSB Parts):**

Every enemy Part in an MMV arena has the same shape:

  EntityID:           0   (no event-flag binding on individual chrs)
  EntityGroupIDs[0]:  AAAA5200  (shared across all enemies in the arena)
  MapStudioLayer:     0xFFFFFFFF  (Default-Enabled in every layer)
  GameEditionDisable: NeverDisable

The only Part with a real EntityID is the grace-handler chr c8300
(EntityID=AAAA0800, EntityGroupIDs[0]=AAAA5210). MMV's EMEVD references
the enemy EntityGroupID as `chrEntityId` to `90015000` (proximity
framing) and `90015002` (death observer). The framework treats the
group as a unit; `CharacterDead(group)` returns true when the last
member dies. No per-entity EnableCharacter machinery anywhere.

**What vanilla NR has by contrast:**

Multi-entity arena bosses at EntityID=XXXX0800 with MapStudioLayer
gated to a specific variation bit (Default-Disabled in lobby/preview,
Default-Enabled only in the active arena variation). The
`90065910/050/131` machinery does the variation transitions and per-
entity EnableCharacter handshakes. v9 hit the wall here: it proximity-
triggered correctly, but the MSB had nothing visible to trigger on
because the active variation isn't entered through the test_mode flow.

**The fix per arena (m48_50, m48_60, m48_80, m48_20, m49_25, m49_28):**

1. Find the boss Part at EntityID=XXXX0800. Don't delete it — the
   rando NpcParam swap is keyed on this entity slot. Flip flags only.
2. Set `MapStudioLayer` = 0xFFFFFFFF (or at minimum the active arena
   variation bit; conservatively keep vanilla bits too).
3. Set `GameEditionDisable` = NeverDisable.
4. Repeat for each helper Part (XXXX5210, XXXX5800, etc.). All
   helpers need to be Default-Enabled or they won't spawn alongside
   the lead.
5. Optionally bind boss + helpers to a shared EntityGroupID so the
   `90015002` death observer can track "all dead" via the group.
   Probably not required for single-fightable-boss arenas; useful for
   Tree Sentinel + knights and Godskin Duo where you want the arena-
   cleared signal to wait for everyone.

The v9 EMEVD overlay (`dev/generate_test_mode_arenas_v9.py`) is then
the right template — already written, sitting in the repo,
empirically failed only because the MSB side wasn't there. With the
MSB modifications in place, it should manifest the boss via 90015000
proximity framing.

**Two tooling routes:**

*(a) Extend in-place binary patcher.* The project already has
`oops_all_anyone.py` with reverse-engineered Part offsets
(`PART_OFF_MODEL_INDEX/NAME/ENTITY_ID/THINK_PARAM/NPC_PARAM/POSITION`,
PART_STRUCT_SIZE=0x3e0). Add three new offsets:
`PART_OFF_MAP_STUDIO_LAYER`, `PART_OFF_GAME_EDITION_DISABLE`,
`PART_OFF_ENTITY_GROUP_IDS` (the last is an array of 8 u32s based on
the XML inspection). Find offsets by hex-diffing a known-Default-
Disabled vanilla Part against MMV's Default-Enabled Part at the same
model class. Write a `make_boss_default_enabled(msb_data, boss_eid)`
function. Hook into the deploy pipeline. Estimated half-day.

*(b) Witchy XML round-trip.* WitchyBND decompiles vanilla MSBs to
XML, supports edits, recompiles to binary. The MMV team uses this
flow — that's how we have m49_53's XML to read from. WitchyBND
explicitly warns against using it for MSB editing (the XML round-
trip isn't byte-perfect in all cases, and corrupting an MSB can
crash maps in non-obvious ways). For our use case the warning is
known and accepted — we're flipping three well-understood fields on
specific Parts, not touching geometry or section tables, and we have
playtest validation for each of the 6 affected arenas as the safety
net. Witchy gives us a real authoring environment that unlocks future
MSB work without per-edit offset-hunting. Estimated 2 days for first-
time witchy integration (subprocess invocation in deploy, per-arena
XML edit scripts, round-trip validation that vanilla-equivalent
output is byte-identical except for the targeted Parts).

If we ever do this, route (b) is the right one — the half-day saved
on the first attempt with route (a) is paid back many times over the
next time anyone wants to touch an MSB.

**Known risks even with MSB modifications in place:**

  - External `DisableCharacter(XXXX0800)` calls from `common.emevd` or
    cutscene scripts that fire at map-load based on EntityID, before
    our overlay's flow takes over. Symptom would be boss visible
    briefly then hidden. Mitigation: identify those calls and
    neutralize them (the `common.emevd.js` is in our dump; grep
    `DisableCharacter` for entity IDs in 48xx0800 range).
  - Per-arena helper events (48xx2810 etc.) still deleted by our
    overlay's `.emevd` replacement. If they do anything beyond
    cosmetic, helpers might be visually present but mechanically
    broken. Mitigation: preserve them in the v9 overlay generator by
    copying vanilla's non-Event-0 events verbatim into the output
    (the v7 approach, but combined with v9 instead of v8 in Event 0).
  - 90015000 only displays a healthbar for the single chrEntityId
    passed. Godskin Duo's linked-healthbar semantics don't come for
    free — they'd need a per-arena healthbar event or accept the
    visual regression of one healthbar for the lead entity only.

**Other reopen triggers:**

  - We identify where vanilla NR initializes the per-arena helper
    events (48xx2810 etc.) — they're parameterized events with init
    callers we haven't found. If we discover the init source and
    params, we could re-init them from our overlay and unblock the
    multi-entity orchestration without MSB work.
  - DarkScript3 or a successor exposes MSB-level state inspection
    (Part Default-Enabled flag visible at the script level), making
    diagnosis-driven iteration faster.
