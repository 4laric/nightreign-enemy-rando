# Ancillary documentation

These docs supplement `README.md` / `CHANGELOG.md` / `PATCH_NOTES.md` (which
stay at the project root). Moved here in v0.23.06 to reduce root clutter.

| File | Purpose |
|------|---------|
| `TODO.md` | The live backlog — open work and deferred features. |
| `OPEN_ISSUES.md` | Investigation threads carried across sessions. **Stale** (last maintained ~v0.27) — verify before acting on any thread. |
| `ARCHITECTURE.md` | Pointer stub — the real architecture orientation lives at `dev/ARCHITECTURE.md`. |
| `SESSION_NOTES.md` | Frozen session history (ends at v0.24.x). Active session notes are `dev/SESSION_NOTES_*.md`. |
| `WORKFLOW.md` | How to set up the rando from scratch, install pre-patched EMEVDs, troubleshoot common errors. Most useful for first-time installers. |
| `LAUNCH_CHECKLIST.md` | The streaming-centric launch/push checklist — Nexus page, announcements, demo prep. |
| `EMEVD_PATCHES.md` | Detailed catalog of every EMEVD patch the rando applies and why. Reference for anyone diagnosing event-script issues. |
| `EMEVD_AUDIT_PRIMER.md` | Primer for running a structured audit of decompiled Nightreign EMEVDs (cluster-anim audit). |
| `BOSS_REWARD_EMEVD_README.md` | Specific deep-dive on the `boss_reward_inject` patch — how the reward picker is hooked into kill events. |
| `HEALTHBAR_NPCNAME_INVESTIGATION.md` | Post-mortem of the multi-session healthbar/NpcName investigation (v0.24.96–v0.24.111+ era). |
| `MMV_INTEGRATION.md` | The optional More Map Variations cross-game import integration — setup, asset packs, known issues. |
| `MOUNTED_BOSS_ARCHITECTURE.md` | Architecture audit of horse-and-rider (mounted) boss randomization. |
| `nb_rando_compat_sweep.md` | v0.28.x empirical sweep of all 28 Night Boss arenas — which tolerate randomization, which need the test-mode template. |
| `UNROSTERED_ENEMIES.md` | Catalog of 32 c-prefixes that ship as MSB Model entries in vanilla NR but have no roster variants (no `npc_param` data). Candidates for ER NPC_PARAM import — would unlock these as placement targets. Includes ER identifications, family fits, and an implementation plan. |
| `ER_HERITAGE_IMPORTS.md` | The first batch of authored ER heritage imports (`er_heritage_imports.json`, source-tag `er_heritage_v1`) — 12 c2xxx ER NB-tier bosses (Margit, Rennala, Radagon, Mohg, Maliketh, Malenia, Morgott, Astel, Godrick, Godfrey, etc.) whose chr files ship in NR. Documents the source-tag convention and exclude-at-will mechanisms. |
| `DEMO_PREP.md` | Workflow for producing a randomized demo run with per-seed boss healthbar names. |
| `V0_23_07_TEST_PLAN.md` | The v0.23.07-era playtest plan — historical, kept for methodology. |
| `BUG_REPORT_TEMPLATE.md` | Copy-paste template for filing a useful bug report. |
| `STREAMING_KIT.md` | Twitch panels, chat commands, and stream-setup text blocks. |
| `ANNOUNCEMENT_COPY.txt` | Release announcement template (Nexus / Discord) — boilerplate the maintainer uses when shipping a new version. |
| `NEXUS_LISTING.txt` | Nexus Mods page description — kept in repo so versions stay synchronized. |
| `archive/` | Retired docs and research notes (CROSS_ENGINE_RESEARCH, KAIDEN_EXPERIMENT_PRIMER, etc.). |
