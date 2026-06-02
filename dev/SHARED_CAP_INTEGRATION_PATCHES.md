# Integration patches for shared-cap mechanism (v0.28.x)

Apply alongside `engine/cap_groups.py` and `data/cap_groups.json`. Three
oops_v3.py call sites need the key-rewrite layer; one new line at module
import time; one optional audit invocation at startup.

## 1) Module import — top of oops_v3.py (near other engine imports)

After the existing imports of engine modules (search for
`from engine.pack_loaders` and add near it):

```python
from engine.cap_groups import (
    resolve_cap_key,
    is_group_key,
    group_members,
    audit_cap_groups,
    all_groups,
)
```

## 2) Reservation pre-pass — line ~13129 (n_to_reserve calculation)

`already_placed_counts` is the dict of vanilla-source-preserved counts
keyed by cp. For a grouped chr we need the SUM of preserves across all
group members.

**Replace:**
```python
        # Adjust cap by already-placed-from-source-preservation
        already = already_placed_counts.get(target_cp, 0)
        n_to_reserve = cap - already
```

**With:**
```python
        # Adjust cap by already-placed-from-source-preservation.
        # v0.28.x shared-cap: when target_cp is in a cap group, sum the
        # preserves across every member of the group. The group's cap is
        # shared, so preserves anywhere in the group consume it.
        _group_key = resolve_cap_key(target_cp)
        if is_group_key(_group_key):
            already = sum(already_placed_counts.get(m, 0)
                          for m in group_members(_group_key))
        else:
            already = already_placed_counts.get(target_cp, 0)
        n_to_reserve = cap - already
```

## 3) Reservation pre-pass — lines 13134, 13201, 13247 (placed_counts writes)

The reservation pass writes counts back into `_placed_counts`. Each write
needs to use the resolved key so all member preserves and all reservations
land in the same bucket.

**Pattern — for each of the three sites:**

Replace `_placed_counts[target_cp]` with the resolved key:

```python
        # Line 13134 context:
        _placed_counts[target_cp] = already
```

**Becomes:**
```python
        _placed_counts[resolve_cap_key(target_cp)] = already
```

Same transform on lines 13201 and 13247 (the `+ 1` increments after each
reservation commit). Three identical changes.

## 4) Per-slot cap gate — lines ~13549-13554 (msb_blocked_cps consumer)

This is where a candidate cp gets blocked because its cap is exhausted.
The `_blocked` set must contain ALL members of a capped group, not just
the cp the group was indexed by.

**Replace:**
```python
        _blocked = getattr(run_ctx, 'msb_blocked_cps', None)
        if _blocked is None and _placed_counts:
            _blocked = {cp for cp, n in _placed_counts.items()
                        if n >= V3_UNIQUE_TARGET_CAPS.get(cp, 0)}
        if _blocked:
            pool = pool - _blocked
```

**With:**
```python
        _blocked = getattr(run_ctx, 'msb_blocked_cps', None)
        if _blocked is None and _placed_counts:
            # v0.28.x shared-cap: build the blocked-cp set by walking
            # _placed_counts (which is now keyed by group-name OR by
            # ungrouped cp). For each exhausted key, if it's a group,
            # add every member; if it's a single cp, add the cp.
            _blocked = set()
            for key, n in _placed_counts.items():
                if is_group_key(key):
                    # Group's cap: any member's V3_UNIQUE_TARGET_CAPS
                    # value works (audit enforces they're all equal).
                    members = group_members(key)
                    member_cap = next(
                        (V3_UNIQUE_TARGET_CAPS.get(m, 0) for m in members
                         if m in V3_UNIQUE_TARGET_CAPS), 0)
                    if n >= member_cap:
                        _blocked |= members
                else:
                    if n >= V3_UNIQUE_TARGET_CAPS.get(key, 0):
                        _blocked.add(key)
        if _blocked:
            pool = pool - _blocked
```

## 5) Organic-pick cap bump — line ~14286

Where a non-reserved placement increments the counter.

**Replace:**
```python
    # v0.23.07: bump unique-cap counter for organic picks. Reserved picks
    # already pre-bumped during the reservation pre-pass; this catches
    # picks that landed on a capped cp via normal pool selection.
    if result in V3_UNIQUE_TARGET_CAPS:
        _placed_counts[result] = _placed_counts.get(result, 0) + 1
    return result
```

**With:**
```python
    # v0.23.07: bump unique-cap counter for organic picks. Reserved picks
    # already pre-bumped during the reservation pre-pass; this catches
    # picks that landed on a capped cp via normal pool selection.
    # v0.28.x shared-cap: bump under the resolved cap key (group name
    # for grouped cps, cp itself for ungrouped). The cap check uses the
    # same resolved key.
    if result in V3_UNIQUE_TARGET_CAPS:
        _key = resolve_cap_key(result)
        _placed_counts[_key] = _placed_counts.get(_key, 0) + 1
    return result
```

## 6) MSB freeze — engine/runctx.py begin_msb

The `msb_blocked_cps` freeze computes which cps are over-cap at MSB
entry. Same group-aware transformation as patch #4.

**Replace (in runctx.py begin_msb):**
```python
        if caps is None:
            self.msb_blocked_cps = None  # no freeze -> picker uses live caps
        else:
            self.msb_blocked_cps = {
                cp for cp, n in self.unique_placed_counts.items()
                if n >= caps.get(cp, 1 << 30)}
```

**With:**
```python
        if caps is None:
            self.msb_blocked_cps = None  # no freeze -> picker uses live caps
        else:
            # v0.28.x shared-cap: counts are keyed by group-name for
            # grouped cps. Convert to a set of blocked c-prefixes
            # (the picker subtracts from the candidate pool, which is
            # cp-keyed) by expanding exhausted groups to all members.
            from engine.cap_groups import is_group_key, group_members
            blocked = set()
            for key, n in self.unique_placed_counts.items():
                if is_group_key(key):
                    members = group_members(key)
                    member_cap = next(
                        (caps.get(m, 1 << 30) for m in members
                         if m in caps), 1 << 30)
                    if n >= member_cap:
                        blocked |= members
                else:
                    if n >= caps.get(key, 1 << 30):
                        blocked.add(key)
            self.msb_blocked_cps = blocked
```

## 7) Startup audit — wherever caps are first finalized in oops_v3.py

After V3_UNIQUE_TARGET_CAPS is fully populated (including the v0.24.x
auto-cap pushes at lines 3997/4020/4068), call the audit once:

```python
    # v0.28.x: validate cap-groups config against the live cap dict.
    # Surfaces malformed groups (cap mismatch, missing members) before
    # any reservation work happens.
    audit_cap_groups(tags, V3_UNIQUE_TARGET_CAPS)
```

A natural insertion point is just before
`_compute_unique_reservations(...)` is first called, after the
`V3_UNIQUE_TARGET_CAPS[_cp] = _cap` push loops finish.

---

## Counts dict key contamination

After these patches `_V3_UNIQUE_PLACED_COUNTS` (and `unique_placed_counts`
on RunContext) contain a mix of c-prefix keys and group-name keys. Any
existing diagnostic code that does `for cp, n in _placed_counts.items()`
and assumes `cp` is always a c-prefix needs an `is_group_key()` check.

Two known consumers in the codebase to audit (grep for `_placed_counts`
or `unique_placed_counts`):

1. `oops_v3.py` line 16712 — spoiler dict population. If the spoiler
   writer iterates the counts to render "Caps utilization: cp X = 2/2",
   it needs to call `explain_key(key)` to turn group keys into
   `tree_sentinel_iconic={c3251, c6251}` for display.

2. `dev/audit_placement_budget_consistency.py` — if this iterates
   `_placed_counts` for the consistency check, it needs the same
   treatment.

A grep at integration time will catch the rest.

## Tests to add

`tests/test_cap_groups.py` (new file). Test cases worth covering:

- `resolve_cap_key('c3251') == 'tree_sentinel_iconic'`
- `resolve_cap_key('c1234') == 'c1234'` (ungrouped passthrough)
- `audit_cap_groups()` raises on: cap mismatch, missing member,
  singleton group, dup cp
- end-to-end: with c3251 cap=2 grouped with c6251 cap=2, after 1
  c3251 placement + 1 c6251 placement, both cps are in `_blocked`
  (group exhausted)

## Backward compatibility

Without `data/cap_groups.json` populated with any groups, the file
loads (the empty `groups: {}` config is valid), `resolve_cap_key` is
identity, and ALL behavior is identical to pre-patch. Safe rollout:
deploy the engine code first with an empty groups dict, observe no
behavior change, then add the first group entry (c3251 + c6251) and
test.

## Estimated effort

- File adds: 2 (engine/cap_groups.py, data/cap_groups.json)
- oops_v3.py changes: 5 sites, ~20 net new lines
- runctx.py changes: 1 site, ~12 net new lines
- Tests: ~80 lines for the new test_cap_groups.py
- Total: small. 1-2 hour implementation, 30 min audit of diagnostic
  callsites for key-contamination, 30 min testing.
