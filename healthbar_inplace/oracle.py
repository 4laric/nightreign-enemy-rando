"""
oracle.py — Extract ground-truth healthbar callsite data from DSAS3-decompiled
.emevd.dcx.js files.

Used as a verification oracle: when we parse the binary .emevd and claim
"this nameId is 902500300 at byte offset X inside event Y, instruction Z,"
we can cross-check by parsing the matching .emevd.dcx.js file (with its
$InitializeCommonEvent text representation of the same call) and
confirming the (event_id, instruction_index, handler_id, nameId,
chr_entity_ids) tuple matches.

Two oracle modes:

  - by_position: walks events and instructions in source order,
    aligns to the binary parse by (event_id, instruction_index_in_event)
  - by_value: matches on (handler_id, nameId, chr_entity_ids) — useful
    when ordering may differ between formats but content should match

The first mode is the stricter / faster check; the second is a
defense-in-depth fallback if event/instruction ordering in the binary
turns out to differ from the .js (it shouldn't, but Sekiro+ formats
have surprised us before).

Re-uses the regex + schema constants from
healthbar_tools/audit_healthbar_callsites.py to stay consistent with
the existing demo workflow.
"""

import json
import re
import sys
from dataclasses import dataclass, asdict

# Mirror of HEALTHBAR_EVENT_SCHEMAS in audit_healthbar_callsites.py.
# Kept here for self-containment.
SCHEMAS = {
    90015000: [(2, [1])],
    90015007: [(4, [1])],
    90015021: [(2, [1])],
    90015023: [(5, [3, 4]), (7, [6]), (9, [8])],
    90015026: [(5, [3, 4])],
    90015406: [(5, [1, 2])],
}

# $InitializeCommonEvent(slot, event_id, ...args)
_INIT_RE = re.compile(
    r'\$InitializeCommonEvent\s*\(\s*'
    r'(\d+)\s*,\s*'
    r'(\d+)\s*'
    r'((?:,[^)]*)?)'
    r'\)\s*;?',
    re.DOTALL
)

# $Event(event_id, RestBehavior, ... { ... })
# We need to know which event we're inside so we can produce
# (event_id, instruction_index_in_event) keys.
_EVENT_RE = re.compile(
    r'\$Event\s*\(\s*(\d+)\s*,\s*(\w+)\s*,\s*function\s*\([^)]*\)\s*\{',
    re.DOTALL
)


@dataclass
class OracleCallsite:
    """One healthbar slot extracted from .js. Maps to one
    HealthbarCallsite in the binary parser's output."""
    file: str
    event_id: int
    instruction_index_in_event: int  # 0-based, only counts instructions inside the $Event body
    handler_id: int
    name_id: int
    chr_entity_ids: list
    name_group_index: int            # for 90015023; 0 otherwise
    is_shared_bar: bool
    source_line: int                 # 1-based; informational


def _split_args(args_blob):
    """Permissive arg splitter — handles trailing commas, comments."""
    out = []
    for tok in args_blob.split(','):
        tok = tok.strip()
        # Strip line comments
        if '//' in tok:
            tok = tok[:tok.index('//')].strip()
        if not tok:
            continue
        try:
            if tok.startswith('0x') or tok.startswith('-0x'):
                out.append(int(tok, 16))
            else:
                out.append(int(tok))
        except ValueError:
            out.append(tok)  # symbol — won't match schemas
    return out


def extract_from_js(file_path):
    """Parse one .emevd.dcx.js file, return list of OracleCallsite.

    Robust to:
      - Multiple events per file
      - Variable whitespace, line wrapping
      - Comments between args
      - Non-healthbar instructions interspersed
    """
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    # Walk events. For each event body, count $InitializeCommonEvent
    # calls (and only those — they're the instructions we care about
    # in terms of mapping to binary instruction_index_in_event)?
    #
    # IMPORTANT DESIGN NOTE: the binary parser's
    # `instruction_index` is the position in the event's ENTIRE
    # instruction list — including non-Initialize ones (IfPlayerInRadius,
    # WaitFor, etc.). The .js source has those too, but we can't
    # reliably count them by regex (their syntax varies).
    #
    # So we don't use instruction_index_in_event as the join key. We
    # use (event_id, handler_id, chr_entity_ids[0]) — the chrEntityId
    # is essentially unique per (event, handler) in vanilla NR. Verify
    # this assumption holds when the binary lands.

    events = list(_EVENT_RE.finditer(text))
    out = []
    for ev_idx, ev_match in enumerate(events):
        event_id = int(ev_match.group(1))
        body_start = ev_match.end()
        # Body ends at the matching `})` — we approximate by either
        # next $Event start or end-of-file. Good enough for our use
        # since $Event blocks don't nest in DSAS3 output.
        if ev_idx + 1 < len(events):
            body_end = events[ev_idx + 1].start()
        else:
            body_end = len(text)
        body = text[body_start:body_end]

        # Find all InitializeCommonEvent calls in this body.
        # Index them in-event order.
        for in_event_idx, init_match in enumerate(_INIT_RE.finditer(body)):
            slot = int(init_match.group(1))
            handler_id = int(init_match.group(2))
            if handler_id not in SCHEMAS:
                continue
            rest = init_match.group(3) or ''
            # Strip leading comma if present
            rest = rest.lstrip(',').strip()
            params = _split_args(rest)
            # Compute source line for diagnostics
            abs_pos = body_start + init_match.start()
            source_line = text.count('\n', 0, abs_pos) + 1

            for group_idx, (name_pos, chr_positions) in enumerate(SCHEMAS[handler_id]):
                if name_pos >= len(params):
                    continue
                if any(p >= len(params) for p in chr_positions):
                    continue
                name_id = params[name_pos]
                chr_ids = [params[p] for p in chr_positions]
                if not isinstance(name_id, int):
                    continue  # symbol, not a numeric nameId
                if not all(isinstance(c, int) for c in chr_ids):
                    continue
                out.append(OracleCallsite(
                    file=file_path,
                    event_id=event_id,
                    instruction_index_in_event=in_event_idx,
                    handler_id=handler_id,
                    name_id=name_id,
                    chr_entity_ids=chr_ids,
                    name_group_index=group_idx,
                    is_shared_bar=len(chr_ids) > 1,
                    source_line=source_line,
                ))
    return out


def to_join_key(handler_id, event_id, chr_entity_ids, name_group_index):
    """Stable key for joining binary callsites against .js oracle.
    Tuple of all the fields that should match exactly between the
    two extractions."""
    return (handler_id, event_id, tuple(chr_entity_ids), name_group_index)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python oracle.py <file.emevd.dcx.js>", file=sys.stderr)
        sys.exit(2)
    cs = extract_from_js(sys.argv[1])
    print(json.dumps([asdict(c) for c in cs], indent=2))
    print(f"\n{len(cs)} healthbar callsites", file=sys.stderr)
