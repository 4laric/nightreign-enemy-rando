"""rewriter.py — Compute and apply healthbar nameId byte rewrites.

Pipeline shape::

    spoiler.json                    chr->nameId catalog       FMG strings
    (which chr at each entity_id)   (vanilla nameId reuse)    (text per nameId)
            \\                      /                          /
             v                     v                          v
            decide_rewrites() -> name_decisions
                                    v
            compute_byte_edits(decisions, binary_callsites) -> {offset: new_uint32}
                                    v
            apply_to_emevd(raw, edits) -> new raw bytes
                                    v
            dcx.compress(new_raw)  -> patched .emevd.dcx
                                    v
            FMG additions JSON     -> fed to FMG editor (witchy/etc) or
                                      directly patched in if we add an
                                      FMG-binary patcher

Naming policy (mirrors apply_healthbar_names.py):

  Solo bar:
    nameId = vanilla nameId of the swapped chr (from chr_to_nameid catalog)
             if it has one; else allocate fresh from fmg_id_base counter.

  Shared bar, all chrs identical:
    Same as solo.

  Shared bar, heterogeneous chrs:
    Allocate fresh nameId; FMG text is the composite "X + Y x2" style
    per the default policy. (Curator overrides via name_table.json
    if/when we add the tab/curation UI; for the auto-pipeline mode
    we just use defaults.)

The fmg_id_base default here is 970000000 (9-digit), NOT 9700000000
(10-digit) which is what apply_healthbar_names.py defaults to. The
10-digit value overflows uint32 and won't fit in the binary slot.
File a follow-up to fix that script too -- see SHIP_NOTES.md.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from typing import Optional


# Fresh-allocation base. nameIds are stored as uint32 in the compiled
# EMEVD, so the base must leave headroom for at least a few thousand
# allocations without overflowing 2^32 (4,294,967,295).
#
# IMPORTANT — design notes for picking this base:
#
# Vanilla NpcName.fmg has 109 groups, sorted ascending by first_id.
# 77 of them use the "wide-claim" convention where last_id ==
# next_group.first_id (each group's last_id touches the boundary of
# the next group). NR's FMG lookup is linear-scan with [first_id,
# last_id] inclusive on both ends, so any nameId that falls within
# a group's claimed range resolves to that group's clamped first slot
# — vanilla never references boundary IDs from EMEVD so the overlap
# is harmless in stock NR, but it shadows any new entry we add at a
# boundary or inside a wide-claim range.
#
# We pick base = 905_500_000, in the vanilla gap between groups #82
# (first_id=905_011_000) and #83 (first_id=905_810_000). The new
# splice_fmg_entries (post-investigation rewrite) shrinks the
# previous group's last_id to base-1 on insertion, carving a clean
# gap so the lookup for base actually reaches our new group.
#
# History of this constant across the loader investigation:
#   - 970_000_000: appended new group at end, IDs above g108's
#     claimed range → loader clamp within g108, bars showed
#     "Night-Swallowed Golden Hippopotamus" or `?NpcName?`.
#   - 911_100_000: appended new group, IDs below g108's wide-claim
#     last_id (912_000_000) → same clamp.
#   - 911_000_151: extended g108 in place at first_id + count → still
#     within g108's wide claim, never carved a gap.
#   - 905_500_000 (current): in a clean 800K-id vanilla gap, MMV
#     proves the 902M-909M band loads, and the splice now breaks
#     the previous group's boundary claim. Validated in-game with
#     "RANDO TEST BOSS" rendered on a force-patched callsite.
DEFAULT_FMG_ID_BASE = 905_500_000


@dataclass
class NameDecision:
    """One healthbar slot's decision after consulting the spoiler + catalog."""
    # Identity: matches a HealthbarCallsite via these fields
    file: str
    event_id: int
    handler_id: int
    chr_entity_ids_after_swap: list   # the chrs the rando actually placed
    name_group_index: int
    # Outcome:
    new_name_id: int                  # the nameId to write into the binary
    new_name_text: str                # what the FMG should display for it
    status: str                       # 'reuse_vanilla' | 'fresh_allocation'
                                      # | 'heterogeneous_squad' | 'unchanged'
    # Diagnostics:
    old_name_id: int
    rationale: str


def decide_rewrites(
    *,
    binary_callsites: list,           # list of HealthbarCallsite from emevd.extract
    spoiler_entity_to_chr: dict,      # {entity_id: {'c_prefix': 'c4470', 'name': 'Abductor Virgin', ...}}
    chr_to_vanilla_name_id: dict,     # {'c4470': [902500300, ...]} from prep_demo BUILD-CATALOG
    file_id: str,                     # which file these callsites came from (the .emevd basename)
    fmg_id_allocator,                 # callable: text -> uint32 (idempotent on identical text)
    title_pool: list = None,          # v0.24.107: list[str] of titles for fun-rename feature
    seed: int = None,                 # v0.24.107: run seed for deterministic compose
    compose_probability: float = 0.5, # v0.24.107: per-bar probability of fun rename
    compose_show_arrow: bool = False, # v0.24.x: prepend "{original} → {replacement}, "
                                       # to composed names (debug mode). Default off.
) -> list:
    """Decide per-callsite what new nameId + FMG text to use. Pure;
    no side effects on the binary.

    v0.24.107 — fun-rename feature: when `title_pool` and `seed` are both
    provided, each unified-prefix callsite rolls a deterministic
    (file/event/handler/entity-hash-based) `compose_probability` gate. If
    the gate fires, the bar gets a composed mashup string from
    `compose_name(...)` instead of the plain replacement name, and a
    fresh nameId is allocated for the composed text (overriding the
    `reuse_vanilla` shortcut that would otherwise apply). Heterogeneous-
    squad callsites are not eligible — their composite "X + Y x2" name is
    already creative enough."""
    decisions = []
    for cs in binary_callsites:
        # What chrs are at each tracked entity in this seed?
        swapped_chrs = []
        for eid in cs.chr_entity_ids:
            info = spoiler_entity_to_chr.get(eid)
            if info is None:
                # Entity not in spoiler. Either it's an EMEVD-direct-
                # spawn (no MSB Part to randomize) or it's unaffected
                # by this seed. Leave the nameId alone.
                swapped_chrs.append(None)
            else:
                swapped_chrs.append(info)

        if all(s is None for s in swapped_chrs):
            decisions.append(NameDecision(
                file=file_id, event_id=cs.event_id, handler_id=cs.handler_id,
                chr_entity_ids_after_swap=cs.chr_entity_ids,
                name_group_index=cs.name_group_index,
                new_name_id=cs.name_id, new_name_text="",
                status='unchanged',
                old_name_id=cs.name_id,
                rationale='entities not in spoiler (EMEVD-direct-spawn or untouched)',
            ))
            continue

        # Project to display names + c-prefixes
        names = [s['name'] if s else None for s in swapped_chrs]
        prefixes = [s['c_prefix'] if s else None for s in swapped_chrs]

        # Filter out None slots (for shared bars where only some are swapped)
        present = [(p, n) for p, n in zip(prefixes, names) if p is not None]

        # Are all present chrs the same c-prefix?
        if len(set(p for p, _ in present)) == 1:
            unified_prefix, unified_name = present[0]

            # v0.24.107: fun-rename gate. Deterministic per-callsite, per-seed.
            # Pulls original c_prefix/name from the spoiler so the composed
            # text can include the vanilla slot's identity (e.g.,
            # "Tree Sentinel → Tibia Mariner, Naturalborn of the Void").
            composed_text = None
            if title_pool and seed is not None:
                callsite_key = (
                    f"{file_id}|{cs.event_id}|{cs.handler_id}|"
                    f"{','.join(str(e) for e in cs.chr_entity_ids)}"
                )
                roll_key = f"compose|{callsite_key}|{seed}".encode('utf-8')
                roll = int(hashlib.md5(roll_key).hexdigest()[:8], 16) % 10000
                if roll < int(compose_probability * 10000):
                    # Pull "original" identity from first present-chr's spoiler info
                    swap_info = next(s for s in swapped_chrs if s is not None)
                    original_name = swap_info.get('old_name') or None
                    original_c = swap_info.get('old_c_prefix')
                    composed_text = compose_name(
                        original_name=original_name,
                        replacement_name=unified_name,
                        original_c=original_c,
                        replacement_c=unified_prefix,
                        title_pool=title_pool,
                        seed=seed,
                        show_arrow_prefix=compose_show_arrow,
                    )

            if composed_text is not None:
                # Gate fired — always fresh-allocate the composed text,
                # overriding any reuse_vanilla shortcut.
                new_id = fmg_id_allocator(composed_text)
                decisions.append(NameDecision(
                    file=file_id, event_id=cs.event_id, handler_id=cs.handler_id,
                    chr_entity_ids_after_swap=cs.chr_entity_ids,
                    name_group_index=cs.name_group_index,
                    new_name_id=new_id, new_name_text=composed_text,
                    status='fresh_allocation',
                    old_name_id=cs.name_id,
                    rationale=f'composed (fun-rename gate): {composed_text!r}',
                ))
                continue

            # Try vanilla reuse
            vanilla_ids = chr_to_vanilla_name_id.get(unified_prefix, [])
            if vanilla_ids:
                new_id = vanilla_ids[0]
                decisions.append(NameDecision(
                    file=file_id, event_id=cs.event_id, handler_id=cs.handler_id,
                    chr_entity_ids_after_swap=cs.chr_entity_ids,
                    name_group_index=cs.name_group_index,
                    new_name_id=new_id, new_name_text=unified_name,
                    status='reuse_vanilla',
                    old_name_id=cs.name_id,
                    rationale=f'all swapped chrs are {unified_prefix}; reusing vanilla nameId',
                ))
            else:
                new_id = fmg_id_allocator(unified_name)
                decisions.append(NameDecision(
                    file=file_id, event_id=cs.event_id, handler_id=cs.handler_id,
                    chr_entity_ids_after_swap=cs.chr_entity_ids,
                    name_group_index=cs.name_group_index,
                    new_name_id=new_id, new_name_text=unified_name,
                    status='fresh_allocation',
                    old_name_id=cs.name_id,
                    rationale=f'{unified_prefix} has no catalog nameId; allocated fresh',
                ))
        else:
            # Heterogeneous squad → composite name
            counts = Counter(p for p, _ in present)
            display_names = {p: n for p, n in present}
            parts = []
            for p, n in counts.most_common():
                label = display_names[p]
                parts.append(f"{label} ×{n}" if n > 1 else label)
            composite = " + ".join(parts)
            new_id = fmg_id_allocator(composite)
            decisions.append(NameDecision(
                file=file_id, event_id=cs.event_id, handler_id=cs.handler_id,
                chr_entity_ids_after_swap=cs.chr_entity_ids,
                name_group_index=cs.name_group_index,
                new_name_id=new_id, new_name_text=composite,
                status='heterogeneous_squad',
                old_name_id=cs.name_id,
                rationale=f'heterogeneous swap: {dict(counts)}',
            ))
    return decisions


def make_fmg_allocator(base=DEFAULT_FMG_ID_BASE, fallback_id=None):
    """Return (allocator, get_table).

    Default behavior (`fallback_id=None`): allocate fresh u32 IDs
    starting at `base` for each unique text. Idempotent on identical
    text within an instance. Caller must splice the returned table
    into NpcName.fmg before the game runs.

    v0.24.13: when `fallback_id` is an int, the allocator IGNORES the
    text and returns `fallback_id` for every call. The table stays
    empty, so `get_table()` returns `{}` and the splice step
    auto-skips. This is the unblock path when the user can't get
    msgbnd unpacking working — every cross-game / composite healthbar
    shows the vanilla string at `fallback_id` (default 902130014 =
    "Crucible Knight and more", which is "literally correct" since
    every fight has at least one Crucible Knight's worth of enemies).
    Vanilla-to-vanilla rewrites (~108/158 in a typical run) are
    unaffected — those go through `reuse_vanilla` in `decide_rewrites`
    and never touch the allocator.
    """
    cache = {}
    counter = [base]
    table = {}
    def allocate(text):
        if fallback_id is not None:
            # No allocation, no table entry — splice becomes a no-op.
            return fallback_id
        if text in cache:
            return cache[text]
        nid = counter[0]
        counter[0] += 1
        if nid >= (1 << 32):
            raise OverflowError(
                f"FMG nameId allocation exceeded uint32 range "
                f"(base={base}, allocated={nid}). Use a lower fmg_id_base."
            )
        cache[text] = nid
        table[nid] = text
        return nid
    def get_table():
        return dict(table)
    return allocate, get_table


def compute_byte_edits(decisions, binary_callsites):
    """Match decisions to callsites positionally — decide_rewrites
    emits exactly one NameDecision per binary callsite in iteration
    order, so decision[i] corresponds to callsite[i]. v0.24.4: switched
    from content-key (event_id, handler_id, name_group, chr_ids) to
    positional after the byte-scan extractor (which doesn't recover
    event_id) caused collisions on grunt mob inits that share
    handler_id + chr_entity_ids across map-variation events."""
    if len(decisions) != len(binary_callsites):
        raise ValueError(
            f"decisions ({len(decisions)}) != callsites ({len(binary_callsites)}); "
            f"join would be ambiguous"
        )
    edits = {}
    for d, cs in zip(decisions, binary_callsites):
        if d.status == 'unchanged':
            continue
        if d.new_name_id == d.old_name_id:
            continue
        edits[cs.name_id_file_offset] = d.new_name_id
    return edits


# ────────────────────────────────────────────────────────────────────
# Spoiler unpacker — bridges the rando's spoilers.json shape to the
# {entity_id: {c_prefix, name}} shape decide_rewrites wants.
# ────────────────────────────────────────────────────────────────────

def _spoiler_entry_to_info(e):
    """Project one spoilers.json entry to the {c_prefix, name, npc_param_id,
    old_c_prefix, old_name} info dict decide_rewrites consumes. Returns
    None when the entry has no usable post-swap c_prefix.

    v0.24.107: captures pre-swap (original) c_prefix and name too, so
    `compose_name` in decide_rewrites can build "<original> → <new>,
    <title>" mashup strings. Original may be absent on some entries
    (EMEVD-direct-spawn dummies, etc.) — falls back to None / ''."""
    new = e.get('new') or {}
    if 'c_prefix' not in new:
        return None
    original = e.get('original') or {}
    return {
        'c_prefix': new.get('c_prefix'),
        'name': new.get('name', ''),
        'npc_param_id': new.get('npc_param_id'),
        'old_c_prefix': original.get('c_prefix'),
        'old_name': original.get('name', ''),
    }


def _mapcode(map_field):
    """Strip a spoiler entry's `map` value (e.g. 'm60_42_36_00.msb') to the
    bare map code ('m60_42_36_00'), which matches the basename of the
    corresponding '.emevd' file. Tolerates a missing/None value."""
    import os as _os
    return _os.path.splitext(map_field or '')[0]


def load_spoiler_entity_map(spoilers_json_path):
    """Read a spoilers.json and return {entity_id: {c_prefix, name, npc_param_id}}
    for every entry with a non-zero entity_id. Entries with entity_id=0
    are name-marker-bound (the rando renames the Part in the MSB; they
    don't reach the EMEVD healthbar path) — skip them.

    The dict is keyed by the AFTER-swap entity_id (which is the same as
    the BEFORE-swap entity_id in the rando — swaps preserve entity
    bindings; that's the whole design).

    WARNING — this FLATTENS across maps. NR's overworld is built from map
    variations (m60_XX_YY_00/_10/_20, evergaol m20_* variants, ...) that
    REUSE the same entity_id for DIFFERENT placements; collapsing them to a
    single global dict means the last-written variation wins for all of
    them. For the per-file healthbar pass use load_spoiler_entity_map_by_map
    so each .emevd resolves entities against ITS OWN map. This flat form is
    kept for backward compatibility and non-file-scoped callers/tests."""
    with open(spoilers_json_path) as f:
        data = json.load(f)
    out = {}
    for e in data.get('entries', []):
        eid = e.get('entity_id') or 0
        if eid == 0:
            continue
        info = _spoiler_entry_to_info(e)
        if info is None:
            continue
        out[eid] = info
    return out


def load_spoiler_entity_map_by_map(spoilers_json_path):
    """Like load_spoiler_entity_map but keyed by map first:
    {mapcode: {entity_id: info}}.

    mapcode is the entry's `map` field with the `.msb` suffix stripped
    (e.g. 'm60_42_36_00'), which equals the basename of the matching
    '.emevd' file — so the pipeline can scope each file's entity lookups
    to that file's own map.

    WHY THIS EXISTS (v0.27.43): NR builds the overworld from map
    variations that reuse entity_ids across variations for different
    enemies. A single global {eid: chr} map (load_spoiler_entity_map)
    collapses them to whichever entry is written last, so a healthbar
    callsite in one variation resolves to a DIFFERENT variation's enemy
    and the bar shows the wrong boss name (e.g. a Gaping Dragon labeled
    "Centipede Demon"). Entity_ids are unique within a single map, so the
    inner per-map dict has no such collisions."""
    with open(spoilers_json_path) as f:
        data = json.load(f)
    out = {}
    for e in data.get('entries', []):
        eid = e.get('entity_id') or 0
        if eid == 0:
            continue
        info = _spoiler_entry_to_info(e)
        if info is None:
            continue
        out.setdefault(_mapcode(e.get('map')), {})[eid] = info
    return out


def decisions_to_summary(decisions):
    """Friendly summary of what's about to change. Used for the GUI's
    'before you click APPLY' preview pane."""
    by_status = defaultdict(int)
    rewrites = []
    for d in decisions:
        by_status[d.status] += 1
        if d.status != 'unchanged' and d.old_name_id != d.new_name_id:
            rewrites.append({
                'file': d.file,
                'event_id': d.event_id,
                'handler_id': d.handler_id,
                'old_name_id': d.old_name_id,
                'new_name_id': d.new_name_id,
                'new_name_text': d.new_name_text,
                'status': d.status,
            })
    return {
        'total_callsites': len(decisions),
        'by_status': dict(by_status),
        'rewrites': rewrites,
    }


# ============================================================================
# v0.24.14: name composition (mashup with random title)
# ============================================================================
#
# Stub-shipped. Defines `compose_name` + `load_title_pool` but no caller in
# `decide_rewrites` invokes them yet — wired in next iteration once the FMG
# splice path is reliable. See `data/title_pool_README.md` for the design
# discussion and pool-editing guidance.
#
# Format produced:
#   vanilla→vanilla:  '<original> → <replacement>, <title>'
#   heritage / no-original-name:  '<replacement>, <title>'
#   same-c-prefix on both sides:  '<replacement>, <title>'
#
# Determinism: title is selected by hashing (original_c, replacement_c, seed),
# so the same pair within a run always gets the same title. Different runs
# (different seeds) may pick differently.

import hashlib
import json as _json
import os as _os


def load_title_pool(path: str = None) -> list:
    """Load the title list from `data/title_pool.json`. If `path` is None,
    resolves relative to this file's parent dir (the project root).

    Returns a list of strings. Raises FileNotFoundError if the file is
    missing — callers should treat absence as 'don't use composition.'
    """
    if path is None:
        here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        path = _os.path.join(here, 'data', 'title_pool.json')
    with open(path) as f:
        data = _json.load(f)
    titles = data.get('titles', [])
    if not isinstance(titles, list) or not titles:
        raise ValueError(
            f"title_pool.json at {path!r} has no usable 'titles' list"
        )
    if not all(isinstance(t, str) and t for t in titles):
        raise ValueError(
            f"title_pool.json 'titles' must be a list of non-empty strings"
        )
    return titles


def compose_name(
    original_name,         # str | None — vanilla slot's display name
    replacement_name,      # str        — what's actually fighting now
    original_c,            # str | None — c-prefix of the vanilla slot
    replacement_c,         # str        — c-prefix of the replacement
    title_pool,            # list[str]  — non-empty list of titles
    seed,                  # int        — run seed for deterministic pick
    show_arrow_prefix=False,  # bool — when True, prepend "{original} → "
                              # before the composed text in EPITHET /
                              # OBJECT-EPITHET styles (debug mode: shows
                              # which vanilla slot was replaced). False
                              # by default for max comedic effect — bars
                              # render just the composed name.
):
    """Build a healthbar mashup string. Returns None when the selected
    title can't be rendered for this input (heritage case with an
    {o}-referencing template — see below). Caller should fall through
    to non-composed output in that case.

    Three title styles supported:

      EPITHET (string has no `{r}` / `{o}` placeholders) — appended
      after a comma:
        compose_name('Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
                     ['Naturalborn of the Void'], 42)
          → 'Tree Sentinel → Tibia Mariner, Naturalborn of the Void'

      OBJECT-EPITHET (string contains `{o}` but not `{r}`) — `{o}` gets
      substituted to the original name, full result appended after comma.
      v0.24.108 — enables titles like "of {o} fame":
        compose_name('Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
                     ['of {o} fame'], 42)
          → 'Tree Sentinel → Tibia Mariner, of Tree Sentinel fame'

      TEMPLATE (string contains `{r}`, optionally with `{o}`) — replaces
      the whole name. `{r}` substitutes replacement_name; `{o}`
      substitutes original_name:
        compose_name('Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
                     ["The Dread Pirate {r}"], 42)
          → 'The Dread Pirate Tibia Mariner'
        compose_name('Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
                     ["{r} née {o}"], 42)
          → "Tibia Mariner née Tree Sentinel"

    Heritage cases (original_name=None):
      - Plain EPITHETs still work: "Mohg, Lord of Blood" reads fine
      - OBJECT-EPITHETs and TEMPLATEs that reference `{o}` return None,
        signaling caller to fall through. "Mohg née Mohg" would be
        nonsensical; "Mohg, of Mohg fame" works but feels lazy. Cleaner
        to just skip — gate hit gets wasted on this callsite, ~one out
        of N pool slots, low cost.

    Same c-prefix on both sides (not actually a swap) drops the arrow:
        compose_name('Banished Knight', 'Banished Knight', 'c4170', 'c4170',
                     ['the Grafted'], 42)
          → 'Banished Knight, the Grafted'

    Selection: MD5(f"{original_c}|{replacement_c}|{seed}") interpreted as an
    int mod len(title_pool). Speed-chosen hash, no crypto needs.
    """
    if not title_pool:
        raise ValueError("title_pool must be non-empty")
    key = f"{original_c or ''}|{replacement_c}|{seed}".encode('utf-8')
    digest = hashlib.md5(key).hexdigest()
    idx = int(digest[:8], 16) % len(title_pool)
    title = title_pool[idx]

    has_r = '{r}' in title
    has_o = '{o}' in title

    # v0.24.108: skip {o}-referencing titles in the heritage case (no
    # original name). See module docstring.
    if has_o and not original_name:
        return None

    # TEMPLATE path: {r} (with optional {o}) replaces the whole name
    if has_r:
        # Note: original_name may be None and {o} not referenced — the
        # replace(...) is a no-op in that case.
        rendered = title.replace('{r}', replacement_name)
        if has_o:
            rendered = rendered.replace('{o}', original_name)
        return rendered

    # OBJECT-EPITHET path: {o} only, treat as epithet with substitution
    if has_o:
        epithet = title.replace('{o}', original_name)
        show_arrow = show_arrow_prefix and (
            original_name
            and original_name != replacement_name
            and original_c != replacement_c
        )
        if show_arrow:
            return f"{original_name} → {replacement_name}, {epithet}"
        return f"{replacement_name}, {epithet}"

    # Plain EPITHET path: "<name>, <title>" with optional arrow
    show_arrow = show_arrow_prefix and (
        original_name
        and original_name != replacement_name
        and original_c != replacement_c
    )
    if show_arrow:
        return f"{original_name} → {replacement_name}, {title}"
    return f"{replacement_name}, {title}"