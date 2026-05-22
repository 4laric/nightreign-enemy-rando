#!/usr/bin/env python3
"""check_setup.py — Verify your environment is ready to run the rando.

Runs a series of checks and prints a clear ✓/✗ for each:
  1. Python version (need 3.10+)
  2. Tk available (the GUI uses tkinter)
  3. Oodle DLL present and loadable (decompresses NR's .dcx files)
  4. Engine + GUI files importable (catches missing-file / data-file errors)
  5. Optional: vanilla MSBs found in vanilla_msbs/ (skips if not present)

Run from this folder:
    python check_setup.py

If everything is ✓, you're ready to run `python oops_rando_gui.py`.
If anything is ✗, the message below it tells you what to do.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS = "✓"
FAIL = "✗"

n_pass = 0
n_fail = 0


def report(label, ok, hint=None):
    global n_pass, n_fail
    mark = PASS if ok else FAIL
    print(f"  {mark} {label}")
    if not ok:
        n_fail += 1
        if hint:
            for line in hint.splitlines():
                print(f"      {line}")
    else:
        n_pass += 1


print("=" * 60)
print("Setup check for 4laric's Nightreign Enemy Randomizer")
print("=" * 60)

# 1. Python version
print("\n[1/5] Python version")
ok = sys.version_info >= (3, 10)
report(
    f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    ok,
    "Need Python 3.10 or newer. Download from python.org.\n"
    "If you have multiple Pythons installed, try `py -3.12 check_setup.py`."
    if not ok else None,
)

# 2. Tk
print("\n[2/5] Tkinter (for the GUI)")
try:
    import tkinter
    report("tkinter available", True)
except ImportError:
    report(
        "tkinter NOT available", False,
        "tkinter ships with the python.org installer but some Linux distros\n"
        "split it out. On Ubuntu/Debian: `sudo apt install python3-tk`.\n"
        "On Windows the official installer should include it — re-install\n"
        "Python from python.org and check the 'tcl/tk' option."
    )

# 3. Oodle DLL
print("\n[3/5] Oodle DLL (Nightreign uses Oodle compression for .dcx)")
# Try install_discovery for full search-order reporting (env var,
# local cache, Steam-installed source games). Falls back to a
# simple-local-only check if install_discovery isn't available.
try:
    sys.path.insert(0, os.path.join(HERE, 'dev'))
    import install_discovery
    discovered_dll = install_discovery.find_oodle_dll()
    nr_install = install_discovery.find_nightreign_install()
    er_install = install_discovery.find_elden_ring_install()
except Exception:
    discovered_dll = None
    nr_install = None
    er_install = None
    # Fallback to plain local check
    oodle_local = [f for f in os.listdir(HERE)
                   if f.lower().startswith("oo2core_") and f.lower().endswith(".dll")]
    if oodle_local:
        discovered_dll = os.path.join(HERE, oodle_local[0])

if discovered_dll:
    report(f"Found {os.path.basename(discovered_dll)}", True)
    if os.path.dirname(os.path.abspath(discovered_dll)) != HERE:
        # The DLL lives in NR/ER's install dir, not our repo. Offer the
        # copy-locally suggestion so subsequent runs don't re-scan.
        print(f"      Source: {discovered_dll}")
        print(f"      Tip: copy it next to this script so the rando doesn't")
        print(f"           re-scan Steam every launch:")
        print(f"           python3 -c \"import sys; sys.path.insert(0, 'dev'); "
              f"import install_discovery; print(install_discovery.copy_oodle_dll_local())\"")
    # Try actually loading it
    try:
        from dcx import _Oodle
        oodle = _Oodle.get()
        report(f"Loadable: {os.path.basename(oodle.dll_path)}", True)
    except Exception as e:
        report(
            "Oodle DLL present but failed to load", False,
            f"Error: {e}\n"
            "Most common cause: 32-bit Python with a 64-bit DLL or vice versa.\n"
            "Use the same bitness as your NR install (always 64-bit on Steam)."
        )
else:
    # Couldn't find one. Build a context-aware hint based on what
    # install_discovery told us about the user's machine.
    if nr_install:
        hint = ("Auto-detected NR install — copy its bundled Oodle:\n"
                f"  Source: {nr_install}/oo2core_*_win64.dll\n"
                f"  Dest:   {HERE}\n"
                "Or auto-copy:\n"
                "  python3 -c \"import sys; sys.path.insert(0, 'dev'); "
                "import install_discovery; print(install_discovery.copy_oodle_dll_local())\"")
    elif er_install:
        hint = ("Auto-detected ER install — copy its bundled Oodle:\n"
                f"  Source: {er_install}/oo2core_*_win64.dll\n"
                f"  Dest:   {HERE}\n"
                "(NR isn't installed on this machine, but the ER Oodle is\n"
                "ABI-compatible — same DLL works.)")
    else:
        hint = ("Couldn't auto-detect a NR or ER Steam install on this machine.\n"
                "Manual steps:\n"
                "  1. On a machine that has NR or ER installed, locate:\n"
                "     <Steam>/steamapps/common/ELDEN RING NIGHTREIGN/Game/oo2core_*_win64.dll\n"
                "  2. Copy it next to this script. Filename version doesn't matter.\n"
                "  3. Alternatively, set the OODLE_DLL env var to point at it.")
    report("No oo2core_*.dll found", False, hint)

# 4. Engine + GUI importable
print("\n[4/5] Engine + GUI importable")
try:
    import oops_v3
    report(f"oops_v3 imports (engine {oops_v3.V3_ENGINE_FINGERPRINT})", True)
except Exception as e:
    report(
        "oops_v3 import failed", False,
        f"Error: {e}\n"
        "Most common causes:\n"
        "  - Missing data files (check nr_enemy_roster.json,\n"
        "    nr_enemy_tags.json, slot_terrain.json are present)\n"
        "  - Damaged JSON (open them in a text editor, look for trailing\n"
        "    commas or mismatched braces if you've edited)"
    )

try:
    import oops_rando_gui  # imports tkinter, but that's already checked above
    report("oops_rando_gui imports", True)
except Exception as e:
    report(
        "oops_rando_gui import failed", False,
        f"Error: {e}"
    )

# 5. vanilla_msbs presence (optional but recommended for first-time setup)
print("\n[5/5] vanilla_msbs/ folder (optional)")
vanilla_dir = os.path.join(HERE, "vanilla_msbs")
if os.path.isdir(vanilla_dir):
    msbs = [f for f in os.listdir(vanilla_dir) if f.endswith(".msb.dcx")]
    if msbs:
        report(f"vanilla_msbs/ has {len(msbs)} .msb.dcx files", True)
    else:
        report(
            "vanilla_msbs/ exists but is empty", False,
            "Bundled vanilla MSB snapshot is missing. The GUI can also point\n"
            "directly at your NR install's mapstudio folder, so this isn't\n"
            "fatal. But filling vanilla_msbs/ with a .msb.dcx snapshot\n"
            "(copy them from <NR install>/Game/map/mapstudio) makes the\n"
            "default GUI flow work without picking a path each time."
        )
else:
    report(
        "vanilla_msbs/ folder not found", False,
        "Not strictly required — the GUI will let you pick any folder of\n"
        ".msb.dcx files as input. But if you copy NR's mapstudio folder\n"
        "into a `vanilla_msbs/` directory next to this script, the GUI\n"
        "will default to it."
    )

# Summary
print()
print("=" * 60)
if n_fail == 0:
    print(f"All {n_pass} checks passed.")
    print()
    print("Next: run `python oops_rando_gui.py`.")
else:
    print(f"{n_pass} passed, {n_fail} failed.")
    print()
    print("Fix the ✗ items above, then re-run this script.")
    sys.exit(1)
