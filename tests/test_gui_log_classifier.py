"""
test_gui_log_classifier.py — locks in _classify_log_line behavior so the
"every Done: line paints red" regression can't come back.

Background: the old auto-classifier in oops_rando_gui.RandoGUI._log was
substring-based — 'failed' anywhere meant 'error'. A successful run
ending "Done: 293 OK, 0 failed" routed RED, desensitizing the eye to
real errors. v0.27.13 tightened the classifier to match anchored
prefixes and counted-nonzero forms ("5 failed" -> error, "0 failed" ->
not error). See dev/GUI_LOG_COLOR_ROUTING.md for the design.
"""
import os, sys
import pytest

# The classifier is module-level so it can be imported without spinning
# up tkinter widgets (importing tkinter itself is fine — no display).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from oops_rando_gui import _classify_log_line  # noqa: E402


# ---------------------------------------------------------------------------
# The exact lines that drove the v0.27.13 ticket: a healthy run's status
# output that the old classifier wrongly painted red because the lines
# happened to contain the substring "failed".
# ---------------------------------------------------------------------------

HEALTHY_RUN_LINES_NOT_ERROR = [
    "Done: 293 OK, 7 passthrough (no decompress), 0 failed, 0.1s",
    "Done: 197 OK, 0 failed, 0.1s",
    "Done: 170 OK, 0 failed, 0.2s",
    "83 files patched, 25 unchanged ..., 0 parse failures",
    "Hub passthrough: 0, Parse failures: 0",
]


@pytest.mark.parametrize("line", HEALTHY_RUN_LINES_NOT_ERROR)
def test_healthy_run_status_is_not_error(line):
    """The whole point of the ticket: zero-failed status reports must
    not paint red."""
    assert _classify_log_line(line) != 'error', (
        f"Healthy-run status line classified as error: {line!r}. "
        "This is the v0.27.13 regression — the classifier is matching "
        "'failed' as a substring instead of counting a nonzero failed "
        "value.")


# ---------------------------------------------------------------------------
# Real errors: must classify as 'error'.
# ---------------------------------------------------------------------------

ERROR_LINES = [
    "Traceback (most recent call last):",
    "Error: bad NPCParam id 0xffff",
    "ERROR: cannot open input file",
    "FAILED to write output MSB",
    "FATAL: regulation.bin not found",
    # Nonzero failure / error counts (the form the regex catches):
    "5 failed",
    "Done: 200 OK, 3 failed, 0.4s",
    "Done: 10 OK, 1 failed",
    "7 errors during shuffle",
    "3 parse failures",
    "Hub passthrough: 0, Parse failures: 4",
]


@pytest.mark.parametrize("line", ERROR_LINES)
def test_real_errors_classify_as_error(line):
    assert _classify_log_line(line) == 'error', (
        f"Real error line did not classify as error: {line!r}")


# ---------------------------------------------------------------------------
# False-positive guards: things that LOOK error-y but aren't.
# ---------------------------------------------------------------------------

NON_ERROR_EDGE_CASES = [
    # Zero counts in every form we expect to see:
    "0 failed",
    "Done: 100 OK, 0 failed",
    "Parse failures: 0",
    "0 parse failures",
    "0 errors",
    # "failures" as part of a noun, not a count:
    "checking for parse failures regression",
    "failures-in-name-only text",
    # The literal word "error" embedded in narration is NOT an error
    # marker — only the anchored prefix or the counted form is. (This
    # is the point of the tightening.)
    "no error counter reset needed",
]


@pytest.mark.parametrize("line", NON_ERROR_EDGE_CASES)
def test_non_error_edge_cases_are_not_error(line):
    assert _classify_log_line(line) != 'error', (
        f"Non-error edge case wrongly classified as error: {line!r}")


# ---------------------------------------------------------------------------
# Positive coverage for the other tags.
# ---------------------------------------------------------------------------

def test_phase_headers_classify_as_accent():
    assert _classify_log_line("=== Phase 1: building roster ===") == 'accent'
    assert _classify_log_line("--- per-MSB stats ---") == 'accent'


def test_done_lines_classify_as_success():
    """Done: lines that pass the error check (i.e. clean) are success."""
    assert _classify_log_line("Done: 3 OK") == 'success'
    assert _classify_log_line("Done: 293 OK, 0 failed, 0.1s") == 'success'


def test_checkmark_glyph_classifies_as_success():
    assert _classify_log_line("\u2713 healthbar rewrite complete") == 'success'


def test_indented_lines_classify_as_info():
    assert _classify_log_line("  reading vanilla MSBs") == 'info'
    assert _classify_log_line("  m45_01 / 27 swaps") == 'info'


def test_warn_prefixes_classify_as_warn():
    assert _classify_log_line("Warning: clobbering existing output") == 'warn'
    assert _classify_log_line("WARN: stale cache") == 'warn'
    assert _classify_log_line("[WARN] no me3 profile") == 'warn'


def test_warn_phrases_classify_as_warn():
    assert _classify_log_line("cancelled by user") == 'warn'
    assert _classify_log_line("falling back to default heuristic") == 'warn'


# ---------------------------------------------------------------------------
# v0.27.13 open-question decision: routine "Skipped: N" lines fall
# through to dim (None), not warn. Locking that in so the choice
# doesn't drift.
# ---------------------------------------------------------------------------

def test_skipped_lines_fall_through_to_default():
    """v0.27.13 ticket decision: routine skip counters are not a
    warning. They fall through to the caller's default ('dim') —
    classifier returns None for them."""
    assert _classify_log_line("Skipped (no compat targets found): 19") is None
    assert _classify_log_line("Skipped: 5") is None


def test_unclassified_lines_return_none():
    """The classifier returns None for lines that don't match any
    specific tag — the caller (RandoGUI._log) supplies the 'dim'
    default."""
    assert _classify_log_line("roster: 247 chrs loaded") is None
    assert _classify_log_line("seed=12345") is None
    assert _classify_log_line("") is None


# ---------------------------------------------------------------------------
# v0.27.43: CTD-risk checker output must be impossible to miss. The engine
# prints "*** CTD RISK CHECK: N finding(s) ... ***" + indented "[ctd]" /
# "[warn]" lines. Pre-v0.27.43 the header ('***') routed to dim and the
# findings (leading spaces) routed to 'info' — a riderless-mount freeze
# warning blended into the wall of status text. These lock in red/amber.
# ---------------------------------------------------------------------------

CTD_ERROR_LINES = [
    "*** CTD RISK CHECK: 20 finding(s) (20 ctd-severity) — see C:\\x\\_ctd_risk.json ***",
    "      [ctd] m34_00_00_00.msb pi=10 eid=0: mount-role chr c5890 "
    "(Black Knight Horse) placed at non-mount source c3080 (Imp); "
    "riderless mount has no AI — freeze/float risk",
    "[ctd] m60_45_36_00.msb pi=24 eid=0: riderless mount freeze risk",
]

CTD_WARN_LINES = [
    "      [warn] mount_target_at_non_mount_source: check raised KeyError: 'x'",
    "[warn] some non-fatal seed finding",
]


@pytest.mark.parametrize("line", CTD_ERROR_LINES)
def test_ctd_findings_route_error(line):
    assert _classify_log_line(line) == 'error', (
        f"CTD-severity output must be red, got {_classify_log_line(line)!r} "
        f"for: {line[:60]}")


@pytest.mark.parametrize("line", CTD_WARN_LINES)
def test_ctd_warn_findings_route_warn(line):
    assert _classify_log_line(line) == 'warn', (
        f"warn-severity CTD output must be amber, got "
        f"{_classify_log_line(line)!r} for: {line[:60]}")


def test_ctd_clean_line_is_not_error():
    """The all-clear line carries no [ctd]/[warn] marker and must NOT be
    painted red (that would cry wolf on a healthy seed)."""
    assert _classify_log_line("CTD risk check: clean (_ctd_risk.json)") != 'error'
