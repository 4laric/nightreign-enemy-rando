"""me3_coherence.py - one source of truth for "what profile/package is active,
and is everything actually pointing at it".

Background / why this exists
----------------------------
The rando had three independent consumers of the me3 layout -- Randomize,
Launch via ME3, and Install bundled mod files -- and each re-derived the active
profile on its own:

  * Randomize  used me3_profile.find_profile_for_package()      (prefers the .me3
                                                                  whose stem
                                                                  matches the dir)
  * Launch     used install_discovery.find_me3_profile_for_package()  (returns the
                                                                  alphabetically-
                                                                  first .me3)
  * the output MSB dir was a *separately saved* path that was only ever
    auto-filled when EMPTY, so switching profiles (Create new / Add to existing)
    left it pointing at the PREVIOUS profile.

Net effect of the bug the user hit: you "Add to existing", Randomize writes the
shuffled MSBs into the *old* profile's map/mapstudio, then Launch boots the *new*
profile -> the new package has no shuffled MSBs -> the game loads vanilla. "I ran
Randomize but the run isn't randomized."

This module centralises the three things that have to agree:
  1. the active .me3 PROFILE,
  2. the active PACKAGE dir, and
  3. the OUTPUT paths (shuffled MSBs + EMEVD) -- which must sit at the canonical
     <package>/map/mapstudio and <package>/event so me3's overlay actually loads
     them.

It's pure (no Tk), so the GUI just reads its verdict and acts. The profile finder
is injectable for testing and defaults to me3_profile's careful one -- killing the
two-finders-disagree failure mode by giving every caller the same answer.
"""

import os

# me3 mounts a package as an overlay mirroring the game's Game/ dir, so shuffled
# MSBs must land at <package>/map/mapstudio and patched EMEVDs at <package>/event
# for the launched profile to pick them up. These are not preferences; they are
# where me3 looks.
OUTPUT_SUBPATH = ("map", "mapstudio")
EVENT_SUBPATH = ("event",)


# --------------------------------------------------------------------------- #
# path helpers
# --------------------------------------------------------------------------- #
def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def is_within(child, parent):
    """True iff child == parent or is a descendant (separator-anchored, not a
    substring test)."""
    if not child or not parent:
        return False
    try:
        c, p = _norm(child), _norm(parent)
    except Exception:
        return False
    return c == p or c.startswith(p + os.sep)


def paths_equal(a, b):
    if not a or not b:
        return False
    try:
        return _norm(a) == _norm(b)
    except Exception:
        return False


def package_paths(package_dir):
    """The canonical child paths for a package: where output MSBs, patched
    EMEVDs, and chr/ files MUST live for me3 to load them.

    Returns {'output': <pkg>/map/mapstudio, 'event': <pkg>/event,
             'chr': <pkg>}  (chr files go under <pkg>/chr; the importer appends
    'chr' itself, so the chr *target root* is the package root)."""
    if not package_dir:
        return {"output": "", "event": "", "chr": ""}
    pkg = os.path.abspath(package_dir)
    return {
        "output": os.path.join(pkg, *OUTPUT_SUBPATH),
        "event": os.path.join(pkg, *EVENT_SUBPATH),
        "chr": pkg,
    }


# --------------------------------------------------------------------------- #
# profile resolution (single answer for everyone)
# --------------------------------------------------------------------------- #
def _default_finder(package_dir):
    try:
        import me3_profile
        return me3_profile.find_profile_for_package(package_dir)
    except Exception:
        return None


def resolve_profile(profile_path, package_dir, *, finder=None):
    """Return the active .me3 path. Prefers an explicitly-tracked profile_path
    (the file the user picked via Create new / Add to existing) when it exists;
    otherwise discovers from package_dir via `finder` (default: me3_profile's
    stem-preferring finder). One finder for all callers -> no disagreement."""
    if profile_path and os.path.isfile(profile_path):
        return os.path.abspath(profile_path)
    finder = finder or _default_finder
    try:
        found = finder(package_dir) if package_dir else None
    except Exception:
        found = None
    return os.path.abspath(found) if found else None


def registers_package(profile_path, package_dir):
    """Tri-valued: True/False whether the .me3 has a [[packages]] entry
    resolving to package_dir; None if it can't be determined."""
    if not profile_path or not os.path.isfile(profile_path) or not package_dir:
        return None
    try:
        import me3_profile
        profile_dir = os.path.dirname(os.path.abspath(profile_path))
        pkg_abs = os.path.abspath(package_dir)
        parsed = me3_profile._load_toml(profile_path)
        if parsed is not None:
            return me3_profile._is_registered_toml(parsed, profile_dir, pkg_abs)
        return me3_profile._is_registered_text(profile_path, profile_dir, pkg_abs)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# the verdict
# --------------------------------------------------------------------------- #
class Problem:
    """A single coherence defect. `fixable` means _bind_paths_to_package /
    ensure_package_registered can repair it automatically."""
    __slots__ = ("code", "message", "fixable")

    def __init__(self, code, message, fixable):
        self.code = code
        self.message = message
        self.fixable = fixable

    def __repr__(self):
        return f"Problem({self.code!r}, fixable={self.fixable})"


class Diagnosis:
    __slots__ = ("profile", "package", "expected_output", "expected_event",
                 "problems")

    def __init__(self, profile, package, expected_output, expected_event, problems):
        self.profile = profile
        self.package = package
        self.expected_output = expected_output
        self.expected_event = expected_event
        self.problems = problems

    @property
    def coherent(self):
        return not self.problems

    @property
    def blocking(self):
        """Problems that mean a run/launch would silently produce a vanilla
        (un-randomized) result -- the failure the user reported. These are the
        ones worth gating on; supports/registration warnings are advisory."""
        return [p for p in self.problems
                if p.code in ("NO_PACKAGE", "NO_PROFILE",
                              "OUTPUT_NOT_CANONICAL", "EVENT_NOT_CANONICAL")]

    @property
    def fixable(self):
        return [p for p in self.problems if p.fixable]


def diagnose(*, profile_path, package_dir, output_dir, event_dir=None,
             finder=None):
    """Cross-check the tracked profile / package / output paths and return a
    Diagnosis. This is the gate Randomize, Launch, and Install all consult so
    they act on one coherent picture instead of three private guesses."""
    profile = resolve_profile(profile_path, package_dir, finder=finder)
    want = package_paths(package_dir)
    problems = []

    if not package_dir or not os.path.isdir(package_dir):
        problems.append(Problem(
            "NO_PACKAGE",
            "me3 package path isn't set (or doesn't exist). Pick or create a "
            "profile so the rando knows where to write.",
            fixable=False))
        # Without a package nothing else can be judged.
        return Diagnosis(profile, package_dir, want["output"], want["event"],
                         problems)

    if not profile:
        problems.append(Problem(
            "NO_PROFILE",
            f"No .me3 profile is tracked or discoverable at/above:\n  {package_dir}\n"
            "Use 'Create new...' or 'Add to existing...' on the Paths tab.",
            fixable=False))

    # The big one: shuffled MSBs must be at <package>/map/mapstudio, patched
    # EMEVDs at <package>/event, or the launched profile loads vanilla.
    if not paths_equal(output_dir, want["output"]):
        if is_within(output_dir, package_dir):
            detail = (f"Output is inside the package but not at map/mapstudio, "
                      f"so me3 won't load it.")
        else:
            detail = ("Output points OUTSIDE the active package, so the launched "
                      "profile won't see the shuffled MSBs (you'll get a vanilla "
                      "run).")
        problems.append(Problem(
            "OUTPUT_NOT_CANONICAL",
            f"Shuffled-MSB output is\n  {output_dir or '(unset)'}\nbut should be\n"
            f"  {want['output']}\n{detail}",
            fixable=True))

    if event_dir is not None and not paths_equal(event_dir, want["event"]):
        problems.append(Problem(
            "EVENT_NOT_CANONICAL",
            f"Patched-EMEVD output is\n  {event_dir or '(unset)'}\nbut should be\n"
            f"  {want['event']}\nPut it at <package>/event so me3 loads it.",
            fixable=True))

    if profile:
        reg = registers_package(profile, package_dir)
        if reg is False:
            problems.append(Problem(
                "PROFILE_MISSING_PACKAGE",
                f"The profile\n  {os.path.basename(profile)}\ndoesn't list this "
                f"package, so me3 ignores its contents at launch. It can be "
                f"registered automatically (append-only).",
                fixable=True))

    return Diagnosis(profile, package_dir, want["output"], want["event"], problems)
