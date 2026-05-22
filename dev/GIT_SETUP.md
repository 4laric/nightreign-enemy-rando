# Git setup — nightreign-enemy-rando

One-time steps to get the project into git, then the everyday workflow.
Run these from inside the project root (the folder containing
`oops_v3.py` and `.gitignore`).

================================================================
0. Install git (Windows)
================================================================

PowerShell, the closest thing to `yum install git`:

    winget install --id Git.Git -e --source winget

Then CLOSE and REOPEN the terminal so `git` lands on PATH. Confirm:

    git --version

If `winget` isn't available (older Windows): installer at
git-scm.com/download/win, or `choco install git` if you have Chocolatey.

================================================================
1. One-time identity setup (skip if already done on this machine)
================================================================

    git config --global user.name  "Your Name"
    git config --global user.email "you@example.com"

================================================================
2. Initialize the repo
================================================================

    git init
    git branch -m main

The `.gitignore` is already in place — it excludes Python caches, user
output, AND the bundled game assets (vanilla_msbs/, patched_emevd/,
bundled_aicommon/*.dcx, data/*.msgbnd). Those ship in release zips, not
in git.

Sanity-check what git WOULD commit before committing — make sure no
game assets slipped through:

    git add -A
    git status --short | Select-String "vanilla_msbs|patched_emevd|\.dcx|\.msgbnd"

That command should print NOTHING. If it lists files, stop and fix
`.gitignore` before the first commit — once game assets are in history,
removing them cleanly is a pain.

================================================================
3. The initial commit
================================================================

This is a fresh start, NOT reconstructed history. The 26 versions of
real history live in CHANGELOG.md and stay there as the system of
record. One honest initial commit:

    git commit -m "Initial commit: v0.26.10"

Tag it so the version is a real git reference:

    git tag v0.26.10

================================================================
4. Push to GitHub
================================================================

Create an EMPTY repo on GitHub first (no README, no .gitignore, no
license — the repo already has all three). Then:

    git remote add origin https://github.com/<you>/nightreign-enemy-rando.git
    git push -u origin main
    git push origin v0.26.10

PUBLIC vs PRIVATE: if public, the game-asset exclusion in `.gitignore`
is mandatory, not optional — double-check step 2's sanity command came
back empty. If unsure, start private; you can flip to public later.

================================================================
Everyday workflow from here
================================================================

    git add -A
    git commit -m "describe the change"
    git push

Each release: bump V3_ENGINE_FINGERPRINT in oops_v3.py, add the
CHANGELOG.md entry, commit, then:

    git tag v0.26.11
    git push origin main --tags

Commits and CHANGELOG.md move together — the changelog stays the
human-readable history, git tags mark the shippable points.

================================================================
Note: repo vs release bundle are two different file lists
================================================================

- The REPO = code, docs, data catalogs, your authored content.
- The RELEASE ZIP = all of that PLUS the bundled game assets
  (vanilla_msbs/ etc.) that `.gitignore` keeps out of the repo.

So the build/release step is: `git archive` (or a clean checkout) +
copy the game-asset folders back in + zip. Worth scripting later as
`dev/build_release.py` so the two lists never drift.
