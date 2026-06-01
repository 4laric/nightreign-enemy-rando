"""engine/cap_groups.py — shared-cap grouping for V3_UNIQUE_TARGET_CAPS.

When two or more c-prefixes represent the same chr identity (ER's c3251
Tree Sentinel + SoTE's c6251 Tree Sentinel), the placement engine
should treat them as ONE accounting unit when enforcing cap=N. Without
this layer, both prefixes place independently and the rarity contract
(cap=2 → "max 2 Tree Sentinels per run") becomes (cap=2 per prefix →
"max 4 Tree Sentinels per run").

DESIGN: pure key-rewrite layer
==============================
The engine's cap accounting lives in dicts/sets keyed by c-prefix:
  _V3_UNIQUE_PLACED_COUNTS : dict[cp] -> count
  msb_blocked_cps          : set[cp]
  reservation slot map     : (msb, pi) -> cp

This module provides ONE function — resolve_cap_key(cp) — that maps a
cp to its accounting key. For ungrouped cps the function returns cp
unchanged (no behavior change). For grouped cps it returns the group
name string. All cap-related reads/writes in oops_v3.py go through
this function.

Side effect: the keys in _V3_UNIQUE_PLACED_COUNTS for grouped cps
become group-name strings (e.g. "tree_sentinel_iconic") instead of cp
strings. Diagnostic code that iterates the counts dict and assumes
keys are cps needs the inverse lookup (group_members(group_name)) to
explain the count. The audit/spoiler helpers below provide that.

LOADING
=======
load_cap_groups() reads data/cap_groups.json once at module init.
Subsequent calls return the cached config. To reload during a hot
session (rare), call _reload_cap_groups(). Tests can pass a config
dict to use_cap_groups_for_test().

AUDIT
=====
audit_cap_groups(tags, caps) raises ValueError if any group is
malformed: member missing from tags, members with mismatched cap
values, cp listed in multiple groups. Called once at startup; cheap
enough to also call from tests.

THREAD/RECURSION SAFETY
=======================
The config is read-only after load. resolve_cap_key is a pure dict
lookup. No locks needed.
"""
from __future__ import annotations
import json
import os
from typing import Dict, FrozenSet, Optional, Set, Tuple

# Module-level cache. None = not loaded yet.
_CONFIG: Optional[dict] = None
# Indices built on load — both directions for O(1) lookup.
_CP_TO_GROUP: Dict[str, str] = {}        # cp -> group_name
_GROUP_TO_MEMBERS: Dict[str, FrozenSet[str]] = {}  # group_name -> frozenset of cps


def _default_config_path() -> str:
    """Path to data/cap_groups.json relative to this file."""
    # engine/ is sibling of data/ — go up one level then into data/.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', 'data', 'cap_groups.json'))


def load_cap_groups(path: Optional[str] = None) -> dict:
    """Load and return the cap-groups config. Idempotent — repeated calls
    return the cached config without re-reading the file.

    Raises FileNotFoundError if the file is missing (intentional: a missing
    file is a deployment bug, not a "fall back to no groups" condition —
    the caller should fix the deployment).
    """
    global _CONFIG, _CP_TO_GROUP, _GROUP_TO_MEMBERS
    if _CONFIG is not None:
        return _CONFIG
    p = path or _default_config_path()
    with open(p, encoding='utf-8') as f:
        _CONFIG = json.load(f)
    # Build indices
    _CP_TO_GROUP = {}
    _GROUP_TO_MEMBERS = {}
    for group_name, group_def in _CONFIG.get('groups', {}).items():
        members = frozenset(group_def.get('members', []))
        _GROUP_TO_MEMBERS[group_name] = members
        for cp in members:
            _CP_TO_GROUP[cp] = group_name
    return _CONFIG


def _reload_cap_groups(path: Optional[str] = None) -> dict:
    """Force a reload. Mostly for tests / dev workflows."""
    global _CONFIG
    _CONFIG = None
    return load_cap_groups(path)


def use_cap_groups_for_test(config: dict) -> None:
    """Inject a config dict directly (no file read). Tests only."""
    global _CONFIG, _CP_TO_GROUP, _GROUP_TO_MEMBERS
    _CONFIG = config
    _CP_TO_GROUP = {}
    _GROUP_TO_MEMBERS = {}
    for group_name, group_def in config.get('groups', {}).items():
        members = frozenset(group_def.get('members', []))
        _GROUP_TO_MEMBERS[group_name] = members
        for cp in members:
            _CP_TO_GROUP[cp] = group_name


def resolve_cap_key(cp: str) -> str:
    """Resolve a c-prefix to its cap-accounting key.

    Returns the group name if cp is in a group, else cp unchanged.
    Ensures load_cap_groups() has been called (lazy init).
    """
    if _CONFIG is None:
        load_cap_groups()
    return _CP_TO_GROUP.get(cp, cp)


def is_group_key(key: str) -> bool:
    """True if `key` is a group name (not a c-prefix)."""
    if _CONFIG is None:
        load_cap_groups()
    return key in _GROUP_TO_MEMBERS


def group_members(group_name: str) -> FrozenSet[str]:
    """Return the c-prefixes in a group. Empty frozenset if not a group."""
    if _CONFIG is None:
        load_cap_groups()
    return _GROUP_TO_MEMBERS.get(group_name, frozenset())


def all_groups() -> Dict[str, FrozenSet[str]]:
    """Return the full group_name -> members mapping. Read-only."""
    if _CONFIG is None:
        load_cap_groups()
    return dict(_GROUP_TO_MEMBERS)


def explain_key(key: str) -> str:
    """Human-readable description of a cap key for logs/spoilers.

    Examples:
      explain_key('c3251')                    -> 'c3251'
      explain_key('tree_sentinel_iconic')     -> 'tree_sentinel_iconic={c3251, c6251}'
    """
    if is_group_key(key):
        members = sorted(group_members(key))
        return f"{key}={{{', '.join(members)}}}"
    return key


def audit_cap_groups(tags: dict, caps: dict) -> None:
    """Validate the cap-groups config against the live tag+cap data.

    Raises ValueError with all findings collated if any of:
      - A group member is not in tags
      - Group members have mismatched cap values in `caps`
      - A cp appears in more than one group
      - A group has fewer than 2 members

    Call once at engine startup, after V3_UNIQUE_TARGET_CAPS and
    nr_enemy_tags are loaded. Cheap (linear in members).
    """
    if _CONFIG is None:
        load_cap_groups()

    findings = []
    seen_cps = {}  # cp -> first group it appeared in

    for group_name, members in _GROUP_TO_MEMBERS.items():
        if len(members) < 2:
            findings.append(
                f"group {group_name!r}: needs at least 2 members; has {len(members)}")
        # Membership validity
        for cp in members:
            if cp not in tags:
                findings.append(
                    f"group {group_name!r}: member {cp!r} not in nr_enemy_tags.json")
            if cp in seen_cps and seen_cps[cp] != group_name:
                findings.append(
                    f"cp {cp!r}: listed in multiple groups "
                    f"({seen_cps[cp]!r} and {group_name!r})")
            seen_cps[cp] = group_name
        # Cap-value consistency
        member_caps = {}
        for cp in members:
            if cp in caps:
                member_caps.setdefault(caps[cp], []).append(cp)
        if len(member_caps) > 1:
            cap_summary = '; '.join(
                f"cap={c}: {sorted(cps)}" for c, cps in sorted(member_caps.items()))
            findings.append(
                f"group {group_name!r}: members have mismatched caps — {cap_summary}. "
                f"All members must share the same V3_UNIQUE_TARGET_CAPS value.")
        # All-or-nothing: either every member has a cap entry, or none should
        # (group with mixed cap/no-cap is suspicious)
        with_cap = [cp for cp in members if cp in caps]
        if with_cap and len(with_cap) != len(members):
            without = [cp for cp in members if cp not in caps]
            findings.append(
                f"group {group_name!r}: partial cap coverage. "
                f"With cap: {sorted(with_cap)}; without cap: {sorted(without)}. "
                f"Either cap all members or none.")

    if findings:
        raise ValueError(
            "cap_groups audit failed with {n} finding(s):\n  - {body}".format(
                n=len(findings), body='\n  - '.join(findings)))
