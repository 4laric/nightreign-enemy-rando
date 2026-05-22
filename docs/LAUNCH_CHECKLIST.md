# Launch checklist — Nightreign Enemy Randomizer push

The streaming-centric launch sequence. The mod is already live on Nexus;
this is the plan to push it properly and turn streaming into the
ongoing content engine. Work top to bottom — each phase gates the next.

Items marked **[decide]** are judgment calls, not mechanical steps.

---

## Phase 1 — Finalize assets

The push copy is drafted. Before anything goes public, finish it:

- [ ] Fill the `[BRACKETED]` placeholders in `NEXUS_LISTING.txt`,
      `ANNOUNCEMENT_COPY.txt`, and `STREAMING_KIT.md` — exact Nightreign
      game patch number, Nexus link, Twitch link, Discord link.
- [ ] Read the refreshed `NEXUS_LISTING.txt` once more in your own
      voice; tweak anything that doesn't sound like you.
- [ ] **[decide]** Screenshots/video on the Nexus page. You need at
      least one image that sells the chaos — a marquee boss in an absurd
      spot, an Oops! All wall of one enemy, or a genuine cursed chimera.
      A short clip is better than a static shot.

## Phase 2 — Update the Nexus page

- [ ] Upload the `v0.26.9` build as the current file.
- [ ] Replace the description box with the refreshed `NEXUS_LISTING.txt`
      (BBCode pastes straight in).
- [ ] Add a Nexus changelog entry for v0.26.9 — short, user-facing;
      `PATCH_NOTES.md` is the source.
- [ ] Confirm the page version number reads v0.26.9.
- [ ] Update screenshots if Phase 1 produced new ones.

## Phase 3 — Stand up the support + stream surface

- [ ] Create a bug-report channel (Discord) and pin
      `BUG_REPORT_TEMPLATE.md`. Link it from the Nexus page's bug-report
      section.
- [ ] Set up Twitch panels from `STREAMING_KIT.md`.
- [ ] Add the chat commands (`!mod`, `!seed`, `!setup`, `!bug`) to your
      bot.
- [ ] **[decide]** Stream format for launch — blind runs or Oops! All
      (chat votes). Both are low-prep and high-reaction; save the
      Nightlord gauntlet for the recurring series.
- [ ] Dry-run the reroll loop: new seed → Randomize → relaunch through
      me3. Time it. If a misbehaving seed mid-stream costs more than a
      minute of dead air, smooth that out before going live.

## Phase 4 — Soft launch

- [ ] Do one low-key stream — small or no audience. Purpose: shake out
      fresh-eyes bugs and generate your first real launch clip.
- [ ] Fix anything embarrassing that surfaces (a Phase-2 re-upload is
      cheap; a bad first impression at full launch is not).
- [ ] Clip the best 30–60 seconds from that stream.

## Phase 5 — Launch

- [ ] Nexus page is live with the refreshed copy, v0.26.9 file, and the
      soft-launch clip as the page video.
- [ ] Post `ANNOUNCEMENT_COPY.txt` — FromSoft modding Discord
      `#releases`, the Nightreign randomizer Discord, and the relevant
      subreddit. Use the matching length variant for each.
- [ ] Go live on Twitch. Put the seed in the stream title so chat can
      race it.
- [ ] Pin / share the launch clip wherever the announcements landed.

## Phase 6 — Post-launch cadence

This is where streaming earns its keep — not the launch day, the loop.

- [ ] Recurring streams; the randomized Nightlord gauntlet as the
      episodic backbone.
- [ ] Every stream: clip the best moment → post it → it links back to
      the Nexus page. Streaming and discoverability feed each other.
- [ ] Triage incoming bug reports through `BUG_REPORT_TEMPLATE.md` +
      the `dev/ctd_lookup.py` / `PLAYTEST_SESSION_LOG.md` tooling.
- [ ] Ship the deferred variety features as named update beats — v0.27
      = Kaiden mount+rider comedy, etc. Each update is both content and
      Nexus-page activity, which the algorithm rewards. Pull the next
      one from `docs/TODO.md`.

---

## Open decision worth resolving early

**Seed visibility.** The mod has no in-game seed display — it's a file
mod. For launch, the `STREAMING_KIT.md` workaround (seed in the title /
panel) is fine. But seed-racing is the single best community mechanic
this mod has, and friction there caps it. If the push goes well, making
the seed visible somewhere a viewer can read it off-screen is the one
piece of actual feature work worth doing for the streaming strategy.
Not a launch blocker — a fast-follow.
