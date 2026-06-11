# Contributing / Dev Setup

## Environment

Python 3.10+ is required. The randomizer itself is pure stdlib; the optional
extras and the test suite need a few packages:

```
pip install -r requirements.txt
```

`cryptography` and `zstandard` power the regulation.bin (shop/drop)
randomization. If they're missing, the rando still runs — it falls back to
copying the bundled regulation unchanged, and the affected tests skip.

## Running the tests

```
pytest
```

`pytest.ini` points at `tests/` plus the self-contained
`healthbar_inplace/tests/` suite. A fresh clone can run the whole suite with
**no game data**: tests that need the bundled `regulation.bin`, the crypto
deps, or MMV/heritage data skip cleanly rather than fail (grep for
`skipif` markers to see the gates).

Useful subsets:

```
pytest tests/test_pick_target_*.py      # engine picker + determinism locks
pytest tests/test_regulation_io.py      # regulation crypto/DCX/BND4 stack
pytest healthbar_inplace/tests          # healthbar rewriter suite
```

## Layout, briefly

- `oops_v3.py` — engine orchestrator; `engine/` — extracted engine modules.
- `oops_rando_gui.py` — tkinter GUI (worker threads call the engine in-process).
- `dcx_batch.py` — the 4-step decompress → shuffle → recompress → healthbar
  pipeline.
- `regulation_io.py` / `regulation_rando.py` — regulation.bin stack and the
  per-seed shop/drop passes. `Regulation.save()` is atomic
  (temp file + `os.replace`) because the GUI patches the deployed regulation
  in place — keep it that way.
- `dev/` — audit + data-builder scripts; `scripts/build_release.py` — release
  zip builder; `docs/` — design notes, `docs/TODO.md` + `docs/OPEN_ISSUES.md`
  for open work.

## Conventions

- Determinism is a contract: anything seed-dependent must derive from the run
  seed (per-slot hashing, sorted pools — see `tests/test_decision_determinism.py`
  and the sim baselines in `sims/`). If you change placement behavior, regen
  fixtures deliberately, never incidentally.
- User-file safety: never leave a user's file truncated on failure — build in
  a temp location and rename/copy on success (see `Regulation.save`,
  `dcx_batch.rando_pipeline`).
- Tests that need game data must skip, not fail, when it's absent.
