"""chr_asset_resolver.py — shared dependency-resolution logic for chr
assets across NR / ER / MMV source installs.

Used by:
  - scripts/preflight_chr_assets.py (CLI validation)
  - dev/heritage_chr_import.py (roster-driven bulk copy)

The module is dependency-free (stdlib only) so both consumers can
import without circular trouble. All paths are passed in explicitly;
nothing here reads from the filesystem at import time.

Concept overview
----------------
Three concepts:

1. ROSTER. The set of c-prefixes the rando could place. Built from
   nr_enemy_tags.json minus the hard-exclude blocklist in
   nr_missing_chr_files.json. Each entry tagged with an
   expected_source ('nr' / 'er' / 'mmv') that determines its
   default-source install for asset resolution.

2. FILE_CLASSES. Per-c-prefix file-glob templates grouped by
   subdirectory (chr/, script/, sfx/). Each template has a severity
   ('REQUIRED', 'AI_REQUIRED', 'COMBAT_FFX', 'RECOMMENDED', 'OPTIONAL')
   that determines whether a miss is CTD-risk, freeze-risk, or
   cosmetic.

3. SHARED_DEPS. Non-per-chr deps (aicommon.luabnd.dcx, material/)
   checked once per run.

Resolution per file template per c-prefix produces a Finding:
  status='PRESENT'  — found in target or expected_source install
                       (engine reads it directly, no action needed)
  status='COPYABLE' — missing from satisfaction dirs, but found in
                       a fallback source dir (target+import would fix)
  status='MISSING'  — not found anywhere; if severity is hard
                       (REQUIRED / AI_REQUIRED / COMBAT_FFX), this
                       is a probable CTD class.
"""
import glob
import json
import os
import re

__all__ = [
    "FILE_CLASSES",
    "SHARED_DEPS",
    "build_roster",
    "build_carrier_map",
    "check_chr",
    "check_shared",
    "worse_status",
    # v0.24.86-patch1 exports for the preflight CLI's CTD-vs-freeze split
    "_HARD_SEVERITIES",
    "_CTD_SEVERITIES",
    "_AI_SEVERITIES",
]


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

# Per-chr file-class templates. Pattern uses {cp} substituted with the
# c-prefix (e.g. 'c4350') and {cp_num} substituted with the c-prefix
# stripped of its leading 'c' (e.g. '4350'). Severity classifies the
# failure mode of a missing file:
#
#   REQUIRED     — engine load-time dereference; missing -> CTD on chr
#                  instantiation (cell load).
#   AI_BATTLE    — battle-state AI scripts (chr's combat brain). NR
#   AI_LOGIC       splits AI into 'battle' and 'logic' lua bundles;
#                  some chrs have only one. Missing BOTH = freeze on
#                  encounter (no CTD; chr loads but stands idle).
#                  AI_REQUIRED kept as alias for back-compat with the
#                  original ER-shaped rubric.
#   COMBAT_FFX   — particle bundle referenced by attack/death TAE
#                  events; missing -> CTD on first action (this is the
#                  c5840/c5880/c6201 attribution profile).
#   RECOMMENDED  — graceful degradation (texbnd missing -> magenta
#                  checkerboard; not CTD).
#   OPTIONAL     — extra anim banks (_aNN, _divNN) that may or may not
#                  exist per chr; absence is fine.
#
# v0.24.86-patch1: rewrite of script/ and sfx/ patterns to match NR's
# actual file naming, verified against an UXM-unpacked NR install:
#   - Scripts: NR uses numeric chr-id + 2-digit variant, no 'c' prefix.
#     c4350 -> matches 4350??_battle.luabnd.dcx or 4350??_logic.luabnd.dcx
#     for any variant suffix XX. The original ER pattern
#     c{cp}_battle.luabnd.dcx finds zero matches in NR.
#   - SFX: NR uses sfxbnd_{cp}.ffxbnd.dcx as exact filename. The
#     original ER glob *{cp}*.ffxbnd.dcx happened to match c0000 by
#     substring coincidence but missed everything else.
FILE_CLASSES = {
    "chr/": [
        ("{cp}.chrbnd.dcx",      "REQUIRED"),
        ("{cp}.anibnd.dcx",      "REQUIRED"),
        ("{cp}.behbnd.dcx",      "REQUIRED"),
        ("{cp}_l.texbnd.dcx",    "RECOMMENDED"),
        ("{cp}_h.texbnd.dcx",    "RECOMMENDED"),
        ("{cp}_a*.anibnd.dcx",   "OPTIONAL"),
        ("{cp}_div*.anibnd.dcx", "OPTIONAL"),
    ],
    "script/": [
        # NR's per-chr AI scripts. Glob matches any 2-char variant.
        # Severity is AI_BATTLE / AI_LOGIC (not AI_REQUIRED) — the chr
        # is functional if EITHER exists, so check_chr applies a
        # special-case "any script file satisfies AI" rule rather than
        # requiring both. See _resolve_ai_findings below.
        ("{cp_num}??_battle.luabnd.dcx", "AI_BATTLE"),
        ("{cp_num}??_logic.luabnd.dcx",  "AI_LOGIC"),
    ],
    "sfx/": [
        # NR's sfx is sfxbnd-prefixed, exact filename.
        ("sfxbnd_{cp}.ffxbnd.dcx", "COMBAT_FFX"),
    ],
}

# AI severities are hybrid: chr is functional if either AI_BATTLE OR
# AI_LOGIC is present. Tracked here so check_chr can apply the union
# rule and the preflight CLI can summarise correctly.
_AI_SEVERITIES = frozenset({"AI_BATTLE", "AI_LOGIC"})

# Shared (non-per-chr) deps. Each tuple: (subdir, filename_or_None,
# severity, doc). filename_or_None=None means "any file in subdir
# satisfies" (directory-level check, used for material/).
SHARED_DEPS = [
    ("script/", "aicommon.luabnd.dcx", "AI_REQUIRED",
     "Goal/Logic ID definitions. Vanilla NR is ~75KB; MMV-superset is "
     "~135KB. The MMV-superset is required for cross-game + DLC chrs."),
    ("script/", "aicommon_dlc01.luabnd.dcx", "AI_REQUIRED",
     "DLC-only goal-table manifest. ~5KB. Required for SOTE DLC chrs "
     "(Bayle, Mesmer, Romina, Putrescent Knight, etc.)."),
    ("material/", None, "DIR_DEPLOYED",
     "MMV's material/ dir is required for cross-game chrs whose models "
     "reference shaders/materials not in NR's base material registry. "
     "Checked at directory level — any file present satisfies."),
]

# v0.24.86-patch1: separate concepts for severity classification.
# _HARD_SEVERITIES drives worst_status — anything in this set bumps a
# chr from OK to COPYABLE/MISSING. _CTD_SEVERITIES is a strict subset
# used by the preflight CLI's summary to count probable-CRASH chrs
# separately from probable-FREEZE chrs (AI absence is freeze, not CTD,
# per the handoff's Engineering Decisions §1). _AI_SEVERITIES drives
# the union resolution in check_chr's post-loop pass (battle OR logic
# satisfies; both missing = freeze).
_HARD_SEVERITIES = frozenset({"REQUIRED", "AI_BATTLE", "AI_LOGIC",
                              "COMBAT_FFX", "CARRIER_ANIM"})
_CTD_SEVERITIES = frozenset({"REQUIRED", "COMBAT_FFX"})
_STATUS_ORDER = {"OK": 0, "COPYABLE": 1, "MISSING": 2}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _glob_in(dirpath, pattern):
    """Files in dirpath matching the glob pattern. Empty list if
    dirpath is None or doesn't exist."""
    if not dirpath or not os.path.isdir(dirpath):
        return []
    matches = glob.glob(os.path.join(dirpath, pattern))
    return sorted(os.path.basename(m) for m in matches if os.path.isfile(m))


def _subdir(install_root, subdir):
    """Return install_root/subdir if both exist, else None."""
    if not install_root:
        return None
    p = os.path.join(install_root, subdir)
    return p if os.path.isdir(p) else None


def worse_status(a, b):
    """Return the worse of two status strings (OK < COPYABLE < MISSING)."""
    return a if _STATUS_ORDER[a] >= _STATUS_ORDER[b] else b


# ---------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------

def build_roster(nr_enemy_tags_path, mmv_imports_path, heritage_pack_path,
                 missing_chr_files_path):
    """Build {c_prefix: expected_source} from the four manifest JSONs.

    expected_source is one of:
      'nr'   — chr is shipped with Nightreign (or its DLC).
      'er'   — chr is a heritage import from Elden Ring / SOTE.
      'mmv'  — chr is a cross-game (DS1/BB/DS3) port shipped by MMV.
      'skip' — chr is hard-excluded by nr_missing_chr_files; don't
               bother checking deps.

    Resolution priority:
      1. nr_missing_chr_files blocklist (wins, marks 'skip')
      2. mmv_imports.tags (when _meta.enabled)
      3. heritage_pack.tags
      4. nr_enemy_tags by _source field (heritage -> er, others -> nr)
    """
    roster = {}

    # 1. Hard-exclude list wins
    skip = set()
    if missing_chr_files_path and os.path.exists(missing_chr_files_path):
        with open(missing_chr_files_path, encoding="utf-8") as f:
            mc = json.load(f)
        for category in ("missing_chrs", "broken_runtime_chrs"):
            entries = mc.get(category, [])
            if isinstance(entries, dict):
                skip |= set(entries.keys())
            elif isinstance(entries, list):
                for e in entries:
                    if isinstance(e, str):
                        skip.add(e)
                    elif isinstance(e, dict) and "c_prefix" in e:
                        skip.add(e["c_prefix"])
    for cp in skip:
        roster[cp] = "skip"

    # 2. MMV imports
    if mmv_imports_path and os.path.exists(mmv_imports_path):
        with open(mmv_imports_path, encoding="utf-8") as f:
            mmv = json.load(f)
        if mmv.get("_meta", {}).get("enabled", False):
            for cp in mmv.get("tags", {}):
                if cp in skip:
                    continue
                roster.setdefault(cp, "mmv")

    # 3. Heritage pack
    if heritage_pack_path and os.path.exists(heritage_pack_path):
        with open(heritage_pack_path, encoding="utf-8") as f:
            hp = json.load(f)
        for cp in hp.get("tags", {}):
            if cp in skip:
                continue
            roster.setdefault(cp, "er")

    # 4. Catalog fallback
    if nr_enemy_tags_path and os.path.exists(nr_enemy_tags_path):
        with open(nr_enemy_tags_path, encoding="utf-8") as f:
            tags = json.load(f)
        for cp, entry in tags.items():
            if cp.startswith("_") or cp in skip or cp in roster:
                continue
            src = (entry.get("_source", "")
                   if isinstance(entry, dict) else "")
            if src == "heritage":
                roster[cp] = "er"
            else:
                roster[cp] = "nr"

    return roster


# ---------------------------------------------------------------------
# Anim-carrier resolution
# ---------------------------------------------------------------------

_CHR_FILE_RE = re.compile(r'^(c\d{4,5})((?:_[a-z0-9]+)*)\.([a-z]+)\.dcx$')


def build_carrier_map(*install_roots):
    """Scan the chr/ subdir of each install root; return
    {dependent_c_prefix: {"carrier": cXXXX, "files": [filenames]}}.

    An anim CARRIER ships .anibnd.dcx but neither .chrbnd.dcx nor
    .behbnd.dcx — ER ships shared-animation bundles this way, and the
    carrier's numbered family siblings reference it (e.g. c5661 Shadow
    Militia references c5660). A dependent's family is its c-prefix
    minus the last digit; if that family contains a carrier, the
    dependent must also receive the carrier's anibnd-class files or it
    T-poses.

    Filename-only — no chr-file parsing. Conservative by design: every
    spawnable family member of a carrier is treated as a dependent,
    even one that ships a complete anibnd of its own. The cost of that
    false positive is a few unreferenced anibnd files copied into chr/
    (the engine never loads them); the cost of a miss is a T-pose.
    Over-copy is the correct side to err on.
    """
    chrs = {}
    for root in install_roots:
        if not root:
            continue
        # accept either an install root (.../Game) or a chr/ dir directly
        d = os.path.join(root, "chr")
        if not os.path.isdir(d):
            d = root
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = _CHR_FILE_RE.match(fn)
            if m:
                chrs.setdefault(m.group(1), set()).add(
                    f"{m.group(2)}.{m.group(3)}.dcx")

    carriers = {c: s for c, s in chrs.items()
                if ".anibnd.dcx" in s
                and ".chrbnd.dcx" not in s and ".behbnd.dcx" not in s}
    fam_carrier = {}
    for c in sorted(carriers):
        fam_carrier.setdefault(c[:-1], c)  # first carrier in a family wins

    out = {}
    for c, s in chrs.items():
        carrier = fam_carrier.get(c[:-1])
        # a dependent is a spawnable sibling (ships its own chrbnd) that
        # is not itself the carrier
        if carrier and c != carrier and ".chrbnd.dcx" in s:
            files = sorted(f"{carrier}{suf}" for suf in carriers[carrier]
                           if suf.endswith(".anibnd.dcx"))
            out[c] = {"carrier": carrier, "files": files}
    return out


# ---------------------------------------------------------------------
# Per-chr resolution
# ---------------------------------------------------------------------

def _satisfaction_priority(expected_source, target_dirs, source_dirs_by_label):
    """For a c-prefix with expected_source, return the priority lists
    of (label, dirpath) pairs for each subdir.

    The 'satisfactions' list contains dirs where presence is sufficient
    (no copy action needed). 'copyables' is the fallback list.

    Logic:
      nr-source chrs: NR install/<sub> is sufficient via me3 base-game
        fallthrough. Target is also sufficient.
      er/mmv-source chrs: must be in target (engine doesn't fall through
        to a non-Nightreign install).
    """
    nr_chr   = source_dirs_by_label.get("nr_chr")
    er_chr   = source_dirs_by_label.get("er_chr")
    mmv_chr  = source_dirs_by_label.get("mmv_chr")
    nr_scr   = source_dirs_by_label.get("nr_script")
    er_scr   = source_dirs_by_label.get("er_script")
    mmv_scr  = source_dirs_by_label.get("mmv_script")
    nr_sfx   = source_dirs_by_label.get("nr_sfx")
    er_sfx   = source_dirs_by_label.get("er_sfx")
    mmv_sfx  = source_dirs_by_label.get("mmv_sfx")

    if expected_source == "nr":
        return {
            "chr/":    ([("target", target_dirs["chr"]),
                          ("nr", nr_chr)],
                         [("er", er_chr), ("mmv", mmv_chr)]),
            "script/": ([("target", target_dirs["script"]),
                          ("nr", nr_scr)],
                         [("er", er_scr), ("mmv", mmv_scr)]),
            "sfx/":    ([("target", target_dirs["sfx"]),
                          ("nr", nr_sfx)],
                         [("mmv", mmv_sfx), ("er", er_sfx)]),
        }
    elif expected_source == "er":
        return {
            "chr/":    ([("target", target_dirs["chr"])],
                         [("er", er_chr), ("mmv", mmv_chr), ("nr", nr_chr)]),
            "script/": ([("target", target_dirs["script"])],
                         [("er", er_scr), ("mmv", mmv_scr), ("nr", nr_scr)]),
            "sfx/":    ([("target", target_dirs["sfx"])],
                         [("er", er_sfx), ("mmv", mmv_sfx), ("nr", nr_sfx)]),
        }
    else:  # mmv
        return {
            "chr/":    ([("target", target_dirs["chr"])],
                         [("mmv", mmv_chr), ("er", er_chr), ("nr", nr_chr)]),
            "script/": ([("target", target_dirs["script"])],
                         [("mmv", mmv_scr), ("er", er_scr), ("nr", nr_scr)]),
            "sfx/":    ([("target", target_dirs["sfx"])],
                         [("mmv", mmv_sfx), ("er", er_sfx), ("nr", nr_sfx)]),
        }


def check_chr(cp, expected_source, sources, target, carrier_dep=None):
    """Resolve dependency status for one c-prefix.

    Args:
        cp: c-prefix string ('c5840')
        expected_source: one of 'nr', 'er', 'mmv'
        sources: dict mapping label -> install root path
                 ({"nr": "...", "er": "...", "mmv": "..."}; missing
                 entries treated as not set).
        target: me3 mod package root (str)
        carrier_dep: optional {"carrier": cXXXX, "files": [...]} from
                 build_carrier_map — when cp's family has an anim
                 carrier, its anibnd files are resolved as extra
                 CARRIER_ANIM findings on top of cp's own.

    Returns:
        dict with keys c_prefix, expected_source, worst_status, findings.
        findings is a list of file-level dicts. The 'files' field on
        PRESENT/COPYABLE findings contains the actual matched filenames
        — useful for the import flow to enumerate what to copy.
    """
    # Pre-resolve all 9 source subdirs once
    source_dirs_by_label = {
        "nr_chr":     _subdir(sources.get("nr"),  "chr"),
        "er_chr":     _subdir(sources.get("er"),  "chr"),
        "mmv_chr":    _subdir(sources.get("mmv"), "chr"),
        "nr_script":  _subdir(sources.get("nr"),  "script"),
        "er_script":  _subdir(sources.get("er"),  "script"),
        "mmv_script": _subdir(sources.get("mmv"), "script"),
        "nr_sfx":     _subdir(sources.get("nr"),  "sfx"),
        "er_sfx":     _subdir(sources.get("er"),  "sfx"),
        "mmv_sfx":    _subdir(sources.get("mmv"), "sfx"),
    }
    target_dirs = {
        "chr":      _subdir(target, "chr")      or os.path.join(target, "chr"),
        "script":   _subdir(target, "script")   or os.path.join(target, "script"),
        "sfx":      _subdir(target, "sfx")      or os.path.join(target, "sfx"),
        "material": _subdir(target, "material") or os.path.join(target, "material"),
    }
    dir_lookups = _satisfaction_priority(
        expected_source, target_dirs, source_dirs_by_label)

    findings = []
    worst_status = "OK"
    # v0.24.86-patch1: track AI battle/logic findings separately so we
    # can apply the "either satisfies" union rule after the per-file
    # loop. cp.lstrip('c') derives the NR-convention numeric portion
    # (c4350 -> '4350'); used for the {cp_num} template substitution.
    cp_num = cp[1:] if cp.startswith("c") else cp
    ai_findings_buffer = []

    for subdir, patterns in FILE_CLASSES.items():
        sat_dirs, copyable_dirs = dir_lookups[subdir]
        for pattern_tmpl, severity in patterns:
            pattern = pattern_tmpl.replace("{cp}", cp)
            pattern = pattern.replace("{cp_num}", cp_num)

            # Check satisfaction dirs
            sat_label, sat_files, sat_path = None, [], None
            for label, d in sat_dirs:
                files = _glob_in(d, pattern)
                if files:
                    sat_label, sat_files, sat_path = label, files, d
                    break
            if sat_label:
                findings.append({
                    "subdir": subdir,
                    "pattern": pattern,
                    "severity": severity,
                    "status": "PRESENT",
                    "location": sat_label,
                    "src_dir": sat_path,
                    "files": sat_files,
                })
                continue

            # Check copyable dirs
            cp_label, cp_files, cp_path = None, [], None
            for label, d in copyable_dirs:
                files = _glob_in(d, pattern)
                if files:
                    cp_label, cp_files, cp_path = label, files, d
                    break
            if cp_label:
                # Use the chr-subdir's target path as the destination
                tgt_path = target_dirs[subdir.rstrip("/")]
                findings.append({
                    "subdir": subdir,
                    "pattern": pattern,
                    "severity": severity,
                    "status": "COPYABLE",
                    "from": cp_label,
                    "src_dir": cp_path,
                    "dst_dir": tgt_path,
                    "files": cp_files,
                })
                continue

            # Missing everywhere
            if severity == "OPTIONAL":
                continue
            findings.append({
                "subdir": subdir,
                "pattern": pattern,
                "severity": severity,
                "status": "MISSING",
            })

    # Carrier-anim resolution. A dependent chr whose family has an
    # anim carrier must also receive the carrier's anibnd-class files
    # or it T-poses. Resolved against the chr/ satisfaction+copyable
    # dirs by exact filename (no globs that could spuriously MISS).
    # Severity CARRIER_ANIM is hard (bumps worst_status) but is NOT an
    # AI severity, so the battle/logic union rule below cannot mask a
    # missing carrier.
    if carrier_dep:
        sat_dirs, copyable_dirs = dir_lookups["chr/"]
        for fname in carrier_dep["files"]:
            note = f"anim carrier {carrier_dep['carrier']} for {cp}"
            sat = next(((lbl, d) for lbl, d in sat_dirs
                        if _glob_in(d, fname)), None)
            if sat:
                findings.append({
                    "subdir": "chr/", "pattern": fname,
                    "severity": "CARRIER_ANIM", "status": "PRESENT",
                    "location": sat[0], "src_dir": sat[1],
                    "files": [fname], "note": note,
                })
                continue
            cpy = next(((lbl, d) for lbl, d in copyable_dirs
                        if _glob_in(d, fname)), None)
            if cpy:
                findings.append({
                    "subdir": "chr/", "pattern": fname,
                    "severity": "CARRIER_ANIM", "status": "COPYABLE",
                    "from": cpy[0], "src_dir": cpy[1],
                    "dst_dir": target_dirs["chr"],
                    "files": [fname], "note": note,
                })
                continue
            findings.append({
                "subdir": "chr/", "pattern": fname,
                "severity": "CARRIER_ANIM", "status": "MISSING",
                "note": note + " — missing from all sources; import "
                               "incomplete, dependent will T-pose",
            })

    # v0.24.86-patch1: post-loop resolution. Two passes.
    #
    # Pass 1: AI union rule. NR splits AI into _battle.luabnd.dcx and
    # _logic.luabnd.dcx, but many chrs ship with only one of the pair
    # (e.g. c0100 has 010000_logic but no 010000_battle). The chr is
    # functional if EITHER is present — having both is the exception
    # rather than the rule. Downgrade MISSING AI findings to NOT_NEEDED
    # when at least one sibling is PRESENT/COPYABLE, so worst_status
    # doesn't get bumped by a benign "missing battle script for a
    # logic-only chr" finding.
    ai_findings = [f for f in findings
                   if f["severity"] in _AI_SEVERITIES]
    ai_satisfied = any(f["status"] in ("PRESENT", "COPYABLE")
                       for f in ai_findings)
    if ai_satisfied:
        for f in ai_findings:
            if f["status"] == "MISSING":
                f["status"] = "NOT_NEEDED"
                f["note"] = "satisfied by sibling AI file"

    # Pass 2: derive worst_status from the final findings.
    worst_status = "OK"
    for f in findings:
        if f["severity"] not in _HARD_SEVERITIES:
            continue
        if f["status"] in ("MISSING", "COPYABLE"):
            worst_status = worse_status(worst_status, f["status"])

    return {
        "c_prefix": cp,
        "expected_source": expected_source,
        "worst_status": worst_status,
        "findings": findings,
    }


# ---------------------------------------------------------------------
# Shared deps
# ---------------------------------------------------------------------

def check_shared(sources, target):
    """Check non-per-chr deps (aicommon files, material/ dir)."""
    out = []
    tgt_material = os.path.join(target, "material")

    for subdir, fname, severity, doc in SHARED_DEPS:
        if subdir == "material/" and fname is None:
            # Directory-level check
            present = (os.path.isdir(tgt_material)
                       and any(os.scandir(tgt_material)))
            sources_with_dir = []
            for label in ("mmv", "er", "nr"):
                d = _subdir(sources.get(label), "material")
                if d and any(os.scandir(d)):
                    sources_with_dir.append({"label": label, "src_dir": d})
            out.append({
                "kind": "directory",
                "subdir": subdir,
                "severity": severity,
                "status": "PRESENT" if present else (
                    "COPYABLE" if sources_with_dir else "MISSING"),
                "sources_with_files": [s["label"] for s in sources_with_dir],
                "copyable_from": sources_with_dir,
                "dst_dir": tgt_material,
                "doc": doc,
            })
            continue

        target_path = os.path.join(target, subdir, fname)
        present_in_target = os.path.isfile(target_path)
        target_size = (os.path.getsize(target_path)
                       if present_in_target else None)
        copyable_from = []
        for label, root in sources.items():
            if not root:
                continue
            p = os.path.join(root, subdir, fname)
            if os.path.isfile(p):
                copyable_from.append({
                    "label": label,
                    "src_path": p,
                    "size": os.path.getsize(p),
                })
        out.append({
            "kind": "file",
            "subdir": subdir,
            "filename": fname,
            "severity": severity,
            "status": "PRESENT" if present_in_target else (
                "COPYABLE" if copyable_from else "MISSING"),
            "target_size": target_size,
            "target_path": target_path,
            "copyable_from": copyable_from,
            "doc": doc,
        })
    return out