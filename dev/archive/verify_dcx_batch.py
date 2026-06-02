"""
verify_dcx_batch.py — run this to confirm your dcx_batch.py has every patch.

Usage:
    cd /path/to/4laric-nightreign-enemy-rando-v0.23.71
    python verify_dcx_batch.py
"""
import inspect
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dcx_batch
import oops_v3

src = inspect.getsource(dcx_batch.rando_pipeline)
size = os.path.getsize(dcx_batch.__file__)

print(f"dcx_batch.py at:     {dcx_batch.__file__}")
print(f"file size:           {size} bytes")
print(f"oops_v3 fingerprint: {oops_v3.V3_ENGINE_FINGERPRINT}")
print()

checks = [
    ('Step 1a/3 (rewires) present',
        'Step 1a/3' in src or 'rewires_applied' in src),
    ('Step 2a/3 (walk_route rewrite) present',
        'Step 2a/3' in src or 'walk_route_rewrite' in src),
    ('cmd_shuffle_v3 call does NOT pass mode positionally',
        'cmd_shuffle_v3(vanilla_dir, shuffled_dir, seed, mode' not in src),
    ('compress_dir gets skip_identity_files',
        'skip_identity_files' in src),
    ('REWIRES_DIR constant defined',
        hasattr(dcx_batch, 'REWIRES_DIR')),
]
fail = 0
for label, ok in checks:
    mark = '✓' if ok else '✗'
    if not ok:
        fail += 1
    print(f"  [{mark}] {label}")

print()
if fail == 0:
    print("ALL CHECKS PASS — your dcx_batch.py has all patches.")
    print("If walk_route_rewrite metadata is still missing from spoilers,")
    print("there's a deeper bug to investigate.")
else:
    print(f"{fail} check(s) FAILED — replace dcx_batch.py with the latest version.")