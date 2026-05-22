"""End-to-end GUI smoke test.

Runs the actual GUI under Xvfb (Linux virtual display), simulating
the click-path a real user takes:

  1. Start from fresh-install state (no .4laric_paths.json).
  2. Wizard appears → click Skip.
  3. Main GUI loads.
  4. Toggle MMV checkbox (exercises the line 6058 encoding code
     path that broke on Windows in v0.26.1).
  5. Click Randomize (exercises the line 6690 _hide_post_run_summary
     call site that broke in v0.26.2/v0.26.3).
  6. Capture every Tk callback exception. Modal dialogs (which would
     block in a real run) are mocked.

This test catches the class of GUI bugs the engine pytest suite can't:
AttributeError on a click handler, codec error on file read,
geometric-rendering hangs, etc. Skipped if Xvfb / python3-tk aren't
available (so dev machines without GUI deps still get a green suite).

Should be run before every release. To exercise from CLI:
    DISPLAY=:99 python3 tests/test_gui_smoke.py

To skip (e.g. on a CI without Xvfb): set NIGHTREIGN_SKIP_GUI_SMOKE=1.
"""
import os
import shutil
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Skip conditions ---------------------------------------------------------

def _have_xvfb():
    return shutil.which('Xvfb') is not None and shutil.which('xvfb-run') is not None


def _have_tk():
    try:
        import tkinter  # noqa
        return True
    except ImportError:
        return False


pytestmark = [
    pytest.mark.skipif(
        os.environ.get('NIGHTREIGN_SKIP_GUI_SMOKE') == '1',
        reason='NIGHTREIGN_SKIP_GUI_SMOKE=1'),
    pytest.mark.skipif(
        not _have_tk(),
        reason='python3-tk not installed (apt install python3-tk)'),
    pytest.mark.skipif(
        not _have_xvfb() and not os.environ.get('DISPLAY'),
        reason='Xvfb not installed and no DISPLAY set'),
]


# Smoke harness -----------------------------------------------------------

@contextmanager
def xvfb_display():
    """Start Xvfb if no DISPLAY, yield the display string, clean up.
    If DISPLAY is already set (interactive dev session), just use it."""
    if os.environ.get('DISPLAY'):
        yield os.environ['DISPLAY']
        return
    proc = subprocess.Popen(
        ['Xvfb', ':99', '-screen', '0', '1024x768x24'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    try:
        os.environ['DISPLAY'] = ':99'
        yield ':99'
    finally:
        proc.terminate()
        proc.wait(timeout=2)
        os.environ.pop('DISPLAY', None)


def _run_smoke_in_subprocess(repo_root):
    """Spawn a subprocess that does the actual GUI dance and reports
    JSON results. Subprocess isolation prevents Tk state from
    polluting other tests in the same pytest run."""
    script = os.path.join(os.path.dirname(__file__), 'gui_smoke_harness.py')
    result = subprocess.run(
        [sys.executable, '-u', script, repo_root],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':99')})
    return result


# The actual test ---------------------------------------------------------

def test_gui_smoke_no_unexpected_exceptions():
    """Full GUI click-path runs without AttributeError, codec errors,
    or other Tk callback exceptions. Modal dialogs mocked so the test
    completes even with empty/invalid paths."""
    # Ensure fresh-install state. Restore the file afterward if it
    # existed (don't clobber a dev machine's saved paths).
    paths_file = os.path.join(REPO_ROOT, '.4laric_paths.json')
    saved_content = None
    if os.path.exists(paths_file):
        with open(paths_file, 'rb') as f:
            saved_content = f.read()
        os.remove(paths_file)
    try:
        with xvfb_display():
            result = _run_smoke_in_subprocess(REPO_ROOT)
    finally:
        # Restore any pre-existing paths file
        if saved_content is not None:
            with open(paths_file, 'wb') as f:
                f.write(saved_content)

    assert result.returncode == 0, (
        f"GUI smoke harness exited {result.returncode}. "
        f"Last 2KB of stdout:\n{result.stdout[-2000:]}\n\n"
        f"Stderr:\n{result.stderr[-2000:]}")


if __name__ == '__main__':
    # CLI runner — does the same thing as the pytest test but with
    # more verbose output for interactive debugging.
    test_gui_smoke_no_unexpected_exceptions()
    print("✓ GUI smoke PASSED")
