# Ancillary documentation

These docs supplement `README.md` / `CHANGELOG.md` / `TODO.md` (which stay at
the project root). Moved here in v0.23.06 to reduce root clutter.

| File | Purpose |
|------|---------|
| `WORKFLOW.md` | How to set up the rando from scratch, install pre-patched EMEVDs, troubleshoot common errors. Most useful for first-time installers. |
| `EMEVD_PATCHES.md` | Detailed catalog of every EMEVD patch the rando applies and why. Reference for anyone diagnosing event-script issues. |
| `BOSS_REWARD_EMEVD_README.md` | Specific deep-dive on the `boss_reward_inject` patch — how the reward picker is hooked into kill events. |
| `UNROSTERED_ENEMIES.md` | Catalog of 32 c-prefixes that ship as MSB Model entries in vanilla NR but have no roster variants (no `npc_param` data). Candidates for ER NPC_PARAM import — would unlock these as placement targets. Includes ER identifications, family fits, and an implementation plan. |
| `ER_HERITAGE_IMPORTS.md` | The first batch of authored ER heritage imports (`er_heritage_imports.json`, source-tag `er_heritage_v1`) — 12 c2xxx ER NB-tier bosses (Margit, Rennala, Radagon, Mohg, Maliketh, Malenia, Morgott, Astel, Godrick, Godfrey, etc.) whose chr files ship in NR. Documents the source-tag convention and exclude-at-will mechanisms. |
| `ANNOUNCEMENT_COPY.txt` | Release announcement template (Nexus / Discord) — boilerplate the maintainer uses when shipping a new version. |
| `NEXUS_LISTING.txt` | Nexus Mods page description — kept in repo so versions stay synchronized. |
