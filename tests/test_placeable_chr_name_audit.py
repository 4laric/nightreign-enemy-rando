"""test_placeable_chr_name_audit.py — every boss-slot-placeable enemy must
resolve to a real healthbar name.

When the randomizer puts enemy `cp` on a slot with a boss healthbar
callsite, healthbar_inplace/rewriter.py picks the displayed name one of
two ways (see decide_rewrites):

  * reuse_vanilla    — `cp` has a vanilla nameId in data/chr_to_nameid.json;
                       the bar shows that vanilla FMG string (always real).
  * fresh_allocation — no vanilla nameId; the bar shows
                       data/nr_enemy_tags.json[cp]["name"], spliced into
                       NpcName.fmg.

The spoiler builds that name via `tags.get(cp, {}).get("name", cp)`
(engine/spoilers.py) — so if a cp has neither a vanilla nameId nor a real
tags name, the healthbar renders the raw c-prefix (e.g. "c7521"). This is
the same class of defect as the c2110 "Beast Clergyman labeled Night's
Cavalry" investigation (c2110 was fine only because it had a real tags
name).

This audit enumerates the curated boss-slot target set
(roster["canonical_targets"]) and asserts every one resolves to a real
name. A small allowlist documents the currently-known gaps so the set
can be tracked and can never silently grow.
"""
import json
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO_ROOT, "data")

# Known unresolved boss-capable targets (no vanilla nameId AND only a
# placeholder name == raw c-prefix). Documented so the audit stays green
# while preventing NEW gaps. These would render their raw c-prefix on a
# boss healthbar if placed there.
#   c7521 / c7541 — nightlord-tier bosses ("Animus - Ascendant Light",
#       "Maris - Fathom of Night"); real names exist in the roster's
#       variant_name/default_name but were never copied into
#       nr_enemy_tags.json["name"]. SHOULD be fixed (copy the roster name).
#   c4386 / c8911 — unnamed grunt / non-combat asset; cosmetic only.
KNOWN_UNRESOLVED = {"c4386", "c8911", "c7521", "c7541"}

_CPREFIX_RE = re.compile(r"c\d{3,4}\Z")


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def _has_vanilla_nameid(c2n, cp):
    v = c2n.get(cp)
    if v is None:
        return False
    if isinstance(v, list):
        return any(isinstance(x, int) and x > 0 for x in v)
    return isinstance(v, int) and v > 0


def _has_real_name(tags, cp):
    n = (tags.get(cp, {}) or {}).get("name", "") or ""
    # A name equal to (or shaped like) a raw c-prefix is the placeholder
    # the spoiler falls back to — not a real display name.
    return bool(n) and not _CPREFIX_RE.match(n)


def _resolves(c2n, tags, cp):
    return _has_vanilla_nameid(c2n, cp) or _has_real_name(tags, cp)


def _placeable_targets():
    roster = _load("nr_enemy_roster.json")
    return [t["c_prefix"] for t in roster["canonical_targets"]]


def test_every_placeable_target_resolves_to_a_real_name():
    c2n = _load("chr_to_nameid.json")
    tags = _load("nr_enemy_tags.json")
    unresolved = sorted(
        cp for cp in _placeable_targets() if not _resolves(c2n, tags, cp))
    new_gaps = set(unresolved) - KNOWN_UNRESOLVED
    assert not new_gaps, (
        "Placeable boss target(s) would render a raw c-prefix on the "
        f"healthbar: {sorted(new_gaps)}. Add a vanilla nameId to "
        "data/chr_to_nameid.json or a real 'name' to data/nr_enemy_tags.json."
    )


def test_known_unresolved_allowlist_is_not_stale():
    """If a previously-broken cp gets fixed, drop it from the allowlist so
    the audit keeps tightening."""
    c2n = _load("chr_to_nameid.json")
    tags = _load("nr_enemy_tags.json")
    targets = set(_placeable_targets())
    still_unresolved = {
        cp for cp in KNOWN_UNRESOLVED
        if cp in targets and not _resolves(c2n, tags, cp)}
    stale = KNOWN_UNRESOLVED - still_unresolved
    assert not stale, (
        f"Allowlisted cp(s) now resolve (or left the target set): "
        f"{sorted(stale)}. Remove them from KNOWN_UNRESOLVED.")


def test_canonical_targets_present_and_well_formed():
    roster = _load("nr_enemy_roster.json")
    targets = roster["canonical_targets"]
    assert len(targets) > 100, "canonical_targets unexpectedly small"
    for t in targets:
        assert _CPREFIX_RE.match(t["c_prefix"]), f"bad c_prefix: {t!r}"


def test_tags_name_present_for_every_target_even_if_placeholder():
    """The spoiler's fallback chain must never raise — every target has a
    tags entry (placeholder or real)."""
    tags = _load("nr_enemy_tags.json")
    for cp in _placeable_targets():
        assert cp in tags, f"{cp} is a placeable target but missing from tags"
