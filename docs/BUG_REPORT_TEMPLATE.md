# Bug report — Nightreign Enemy Randomizer

Found a cursed encounter that crashes or hangs? Copy this, fill it in,
and post it. Fill what you can — the **seed** and the **spoiler files**
matter most; with those, most bugs are reproducible on the first try.

## The essentials

- **Seed:**
- **Engine version:** _(the top line of `_spoilers.md` — e.g. `v0.26.9`.
  If it shows something older, you're on a stale install: reinstall and
  see if the bug survives before reporting.)_
- **What happened:** _(one line — "boss didn't wake", "CTD on cell
  load", "enemy frozen in a T-pose", "no rune drop on kill", etc.)_

## Where it happened

- **Map:** _(search `_spoilers.md` for the broken spot — map names look
  like `m38_00_00_00`)_
- **Offending enemy:** _(the c-prefix / entity on that spoiler line)_
- **Context:** _(Night 1 / Night 2 boss arena? overworld field? a camp
  or fort? a multi-enemy cluster?)_

## Attach

- **`_spoilers.json` and `_spoilers.md`** from the roll — drag them in.
- **A screenshot or clip** if you have one. Caught it on a stream VOD?
  Just give the channel + timestamp — that's a perfect, recorded repro.

## Optional but helpful

- Did it happen **every time** on this seed, or just once?
- **me3 profile contents:** do you have MMV or other content packs
  installed, and is the MMV toggle on in the GUI?
- **If the GUI itself errored** (not the game): relaunch it with
  `python oops_rando_gui.py` from a terminal and paste the `[gui]`
  diagnostic output.

---

**Fastest workaround while you wait:** open `_spoilers.md`, find the
c-prefix at the broken spot, add it to the **Excluded Enemies** tab in
the GUI, and re-roll. A fresh seed almost always dodges a one-off.
