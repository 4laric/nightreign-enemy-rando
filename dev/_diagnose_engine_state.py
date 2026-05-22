"""Engine state diagnostic — writes a report to engine_state.txt.

Run from the nightreign-enemy-rando/ directory:
    python3 _diagnose_engine_state.py

Then paste the contents of engine_state.txt back to me.

The diagnostic answers four questions:
  1. WHICH oops_v3.py is loaded (path + mtime + .pyc state)?
  2. What does the engine self-report (fingerprint)?
  3. What's the actual ban state of c8500 / c1260 / etc?
  4. Does apply_run_overrides(multiplayer_safe=True) work?

If everything reports "expected" values and a real rando run still
leaks these c-prefixes, the issue is post-engine (dcx_batch, GUI
re-import, etc.) — not a stale-cache issue.
"""
import datetime as _dt
import io
import os
import sys
from contextlib import redirect_stdout

# Write everything to a string buffer first, then dump to file at the
# end so the report is atomic and viewable on screen at the same time.
report = []
def emit(line=''):
    report.append(line)
    print(line)

emit('=' * 70)
emit('ENGINE STATE DIAGNOSTIC')
emit(f'  generated: {_dt.datetime.now().isoformat(timespec="seconds")}')
emit(f'  cwd:       {os.getcwd()}')
emit(f'  python:    {sys.executable}')
emit(f'  pid:       {os.getpid()}')
emit('=' * 70)

# Q1: Which oops_v3.py is loaded?
try:
    import oops_v3
except ImportError as e:
    emit(f'\nFATAL: cannot import oops_v3: {e!r}')
    emit('Are you running this from the nightreign-enemy-rando/ folder?')
    sys.exit(1)

src = oops_v3.__file__
src_mtime = _dt.datetime.fromtimestamp(os.path.getmtime(src))
emit()
emit(f'oops_v3 source file: {src}')
emit(f'  source mtime:      {src_mtime}')

pycache_dir = os.path.join(os.path.dirname(src), '__pycache__')
if os.path.isdir(pycache_dir):
    pycs = sorted(f for f in os.listdir(pycache_dir) if f.startswith('oops_v3'))
    if pycs:
        emit(f'  __pycache__/ entries for oops_v3:')
        for p in pycs:
            full = os.path.join(pycache_dir, p)
            pyc_mtime = _dt.datetime.fromtimestamp(os.path.getmtime(full))
            stale = pyc_mtime < src_mtime
            tag = '  <-- STALE (older than source!)' if stale else ''
            emit(f'    {p}  mtime={pyc_mtime}{tag}')
    else:
        emit(f'  __pycache__/: no oops_v3 .pyc files (will compile on import)')
else:
    emit(f'  __pycache__/: not present')

# Q2: What does the engine self-report?
emit()
emit(f'V3_ENGINE_FINGERPRINT:   {oops_v3.V3_ENGINE_FINGERPRINT}')

# Capture load_data output so it doesn't clutter the report
load_buf = io.StringIO()
try:
    with redirect_stdout(load_buf):
        roster, tags = oops_v3.load_data()
except Exception as e:
    emit(f'\nFATAL: load_data() raised: {e!r}')
    sys.exit(2)

emit()
emit('Engine-set sizes (the values the picker reads):')
emit(f'  V3_MP_SAFE_BLOCKLIST:                {len(oops_v3.V3_MP_SAFE_BLOCKLIST):>4}  (expected 190 for v0.24.20+)')
emit(f'  V3_EXCLUDE_TARGET_PREFIXES:          {len(oops_v3.V3_EXCLUDE_TARGET_PREFIXES):>4}  (expected 122 for v0.24.23)')
emit(f'  V3_GHOST_EXCLUDE_TARGET_PREFIXES:    {len(oops_v3.V3_GHOST_EXCLUDE_TARGET_PREFIXES):>4}  (expected   7 pre-override)')
emit(f'  V3_EXCLUDE_PREFIXES:                 {len(oops_v3.V3_EXCLUDE_PREFIXES):>4}  (expected  35)')

# Q3: Specific c-prefix ban state.
emit()
emit('Specific c-prefix ban state (these should all show TRUE in EXCLUDE_TARGET_PREFIXES except c6260):')
checks = [
    ('c8500', 'Manus, Father of the Abyss (DS1 mmv blacklist)'),
    ('c1260', 'Hollow Manserving Servant (BB mmv blacklist)'),
    ('c4511', 'Lichdragon Fortissax (mmv blacklist + v0.24.24 flier)'),
    ('c6260', 'Death Rite Bird (v0.24.24 source-anim gate only)'),
]
for cp, desc in checks:
    src_label = tags.get(cp, {}).get('_source', '?')
    in_excl = cp in oops_v3.V3_EXCLUDE_PREFIXES
    in_etp = cp in oops_v3.V3_EXCLUDE_TARGET_PREFIXES
    in_ghost = cp in oops_v3.V3_GHOST_EXCLUDE_TARGET_PREFIXES
    in_mpsb = cp in oops_v3.V3_MP_SAFE_BLOCKLIST
    emit(f'  {cp} ({src_label}) - {desc}:')
    emit(f'    in V3_EXCLUDE_PREFIXES:        {in_excl}')
    emit(f'    in V3_EXCLUDE_TARGET_PREFIXES: {in_etp}')
    emit(f'    in V3_GHOST_EXCLUDE:           {in_ghost}')
    emit(f'    in V3_MP_SAFE_BLOCKLIST:       {in_mpsb}')

# v0.24.24 anim_class backfill check
emit()
emit('v0.24.24 anim_class backfill (these should report flying_dragon):')
for cp in ('c4502', 'c4504', 'c4511', 'c6260'):
    ac = tags.get(cp, {}).get('anim_class', '<missing>')
    name = tags.get(cp, {}).get('name', '<not in tags>')
    tag = '' if ac == 'flying_dragon' else '  <-- BACKFILL MISSING'
    emit(f'  {cp} ({name}): anim_class={ac}{tag}')

# v0.24.24 source-anim guard check
emit()
emit('v0.24.24 V3_FORBIDDEN_BY_SOURCE_ANIM entries:')
fbsa = getattr(oops_v3, 'V3_FORBIDDEN_BY_SOURCE_ANIM', {})
for src_anim in sorted(fbsa.keys()):
    forbidden = fbsa[src_anim]
    emit(f"  {src_anim!r}: {len(forbidden)} forbidden targets")
    emit(f'    {sorted(forbidden)}')

# Q4: Does apply_run_overrides actually mutate?
emit()
emit('apply_run_overrides(multiplayer_safe=True) effect:')
try:
    from engine.runtime import apply_run_overrides
except ImportError as e:
    emit(f'  FATAL: cannot import apply_run_overrides: {e!r}')
    emit(f'  engine/ package may be missing - re-extract the release zip')
    sys.exit(3)

pre_ghost = len(oops_v3.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
override_buf = io.StringIO()
with redirect_stdout(override_buf):
    with apply_run_overrides(multiplayer_safe=True) as gates:
        inside_ghost = len(oops_v3.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        gates_ghost = len(gates.ghost_exclude_target_prefixes)
post_ghost = len(oops_v3.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
emit(f'  Before override:   {pre_ghost}')
emit(f'  Inside override:   {inside_ghost}  (expected 197)')
emit(f'  gates.ghost size:  {gates_ghost}  (expected 197)')
emit(f'  After override:    {post_ghost}  (expected back to {pre_ghost})')

emit()
emit('=' * 70)
ok_fingerprint = oops_v3.V3_ENGINE_FINGERPRINT.startswith('v0.24.2')
ok_blocklist = len(oops_v3.V3_MP_SAFE_BLOCKLIST) >= 190
ok_etp = 'c8500' in oops_v3.V3_EXCLUDE_TARGET_PREFIXES
ok_override = inside_ghost >= 190
all_ok = ok_fingerprint and ok_blocklist and ok_etp and ok_override
if all_ok:
    emit('  RESULT: ENGINE STATE LOOKS CORRECT')
    emit()
    emit('  If a rando run still leaks c8500/c1260/heritage cps with this')
    emit('  state, then the leak is happening downstream of the engine -')
    emit('  most likely the GUI imported oops_v3 once at startup before')
    emit('  this diagnostic ran. Restart the GUI BEFORE the next run.')
else:
    emit('  RESULT: ENGINE STATE IS WRONG')
    emit()
    if not ok_fingerprint:
        emit(f'    - fingerprint {oops_v3.V3_ENGINE_FINGERPRINT!r} is pre-v0.24.20')
    if not ok_blocklist:
        emit(f'    - V3_MP_SAFE_BLOCKLIST size {len(oops_v3.V3_MP_SAFE_BLOCKLIST)} (expected 190)')
    if not ok_etp:
        emit(f'    - c8500 not in V3_EXCLUDE_TARGET_PREFIXES')
    if not ok_override:
        emit(f'    - multiplayer_safe override produced {inside_ghost} ghost cps (expected 197)')
emit('=' * 70)

# Write to file
out_path = os.path.join(os.getcwd(), 'engine_state.txt')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report) + '\n')
emit()
emit(f'Report written to: {out_path}')
emit('Paste the contents back to me.')
