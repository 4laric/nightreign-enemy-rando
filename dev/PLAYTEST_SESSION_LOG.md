# Playtest session log

Fill the **Session header** at expedition start. If a CTD happens, fill
a **CTD incident** block in the moment — before you reboot. Sections
8-10 are filled after reboot during investigation, by which point
`dev/ctd_lookup.py` has pre-filled most of section 5.

The goal of this template is to capture observational data while it's
still fresh, in a structure that the post-CTD tools can consume.

---

## Session header

- **Date:** YYYY-MM-DD
- **Enemy rando seed:** *(from rando GUI title "Expeditions (XXXXX-YYYYY)" — second field)*
- **Enemy rando spoiler:** *(path to the .json the rando emitted)*
- **Derand seed:** *(value you set in derandomizer)*
- **Nightlord:** *(adel / gladius / ...)*
- **Expected pattern ID:** *(from derand GUI, e.g. 067)*
- **Shifting Earth:** *(none / mountaintop / crater / rotted_woods / noklateo / great_hollow)*
- **Goal of this session:** *(e.g. "Tier 1 axis-extension test: c3100 at m34_30:13"
  or "general stability soak — first CTD wins")*

---

## CTD incidents

> Fill one block per crash. If the session ends clean, skip to "Session
> outcome" at the bottom.

### Incident 1

**Time since expedition start:** *(approx — "5 min in" / "Day 2 boss" / etc)*

**Where I was — best guess:**
- *(region: e.g. "Crater Cathedral interior, second floor")*
- *(prior site of grace / chest / landmark you remember)*
- *(distance from spawn or last camp — "near the m43_50 tunnel entrance")*

**What I was doing:**
- *(e.g. "walking into a fog wall" / "first hit on the boss" / "approaching
  a chr at distance" / "just loaded into a tile")*

**Last enemy seen, observable signal:**
- *(rough description — armored knight / kneeling stone golem / etc)*
- *(if you got close enough to see name plate, write it down — even partial)*
- *(did it aggro? freeze? trigger a cinematic?)*

**Crash signature:**
- Game window: closed silently / froze first / "Application Error" dialog?
- me3 log tail — paste the last 50 lines from
  `C:\Users\<user>\AppData\Local\garyttierney\me3\data\logs\nightreign-randomizer\`
  (or `onlyrando` if that's the active profile):
  ```
  (paste here — most recent .log file, last ~50 lines)
  ```

**Initial hypothesis:** *(your best guess for which (chr, slot) this was —
might be unknown, that's fine)*

---

## Triage candidates *(filled after reboot)*

Once you've rebooted, the candidate set comes from intersecting:

1. The validator manifest's SUSPICIOUS / WOULD_REJECT placements for
   this enemy seed
2. The MSBs that the derand pattern's layout includes (cross-ref
   `dev/derand_observations.json` if recorded, or thefifthmatt's
   per-pattern image if not)
3. Your best-guess region from the incident block

Quick filter by hand:
```bash
# All SUSPICIOUS placements for this seed
python3 -c "
import json
m = json.load(open('<your-manifest>.json'))
for r in m:
    if r['seed'] != <SEED>: continue
    if r['status'] != 'SUSPICIOUS': continue
    print(f'  {r[\"msb\"]:<22} pi={r[\"pi\"]:<3} {r[\"target_cp\"]}({r[\"target_name\"]})')
    print(f'    {r[\"suspicious_tags\"]}')
"
```

**Top candidates after filter:**

| Rank | MSB | PI | Target chr | Suspicion tags | Reachable from spawn? |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

---

## Reproduction attempt

Boot back up with **same enemy seed + same derand seed**. Navigate to
each candidate from rank 1 down.

For each candidate, record:

- **Did the same crash happen?** *(yes / no / different crash)*
- **Did the chr behave abnormally before crashing?** *(frozen pose,
  partial-render, audio cutout, etc — the in-game signal the validator
  axes are looking for)*
- **If no crash, did the chr fight normally?** *(rules out the
  candidate; remove from list)*

When a candidate reproduces: that's the confirmed (chr, slot). Run
`dev/ctd_lookup.py` to start the formal CTD report:

```bash
python3 dev/ctd_lookup.py \
    --spoiler <enemy-spoiler.json> \
    --msb <confirmed-msb> --pi <confirmed-pi> \
    --slug <short-name-for-this-ctd>
```

That writes `dev/ctd_reports/YYYY-MM-DD_<slug>.md` with section 5
pre-filled from the axis classifiers. Move sections 6-9 of *that*
report from this session log (the "Where I was" / "What I was doing"
/ "Last enemy seen" blocks above are the raw material).

---

## Session outcome

- **CTDs observed:** *(count)*
- **Confirmed (chr, slot) pairs:** *(from reproduction step)*
- **Unreproducible CTDs:** *(stays in this session log; may resurface
  next session)*
- **CTD reports filed:** *(filenames in `dev/ctd_reports/`)*
- **Tier-N tests resolved this session:** *(reference back to the test
  plan)*
- **Validator changes warranted:** *(if any — e.g. "add c5750 to
  scripted_intro_chrs.json after confirmation at m34_10:7")*

---

## Notes / leftover signal

*(Anything that didn't fit above — partial observations, weird
behavior that didn't crash, surprises about the map layout, etc.
This is where the next axis hypothesis often comes from.)*
