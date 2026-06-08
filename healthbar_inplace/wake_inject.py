"""wake_inject.py — append proximity-wake registrations to compiled EMEVD,
without DarkScript3.

v0.31 — Alaric. The maximal stamp test (stamp_test.py) gives every EID-0
Enemy Part a reserved entity id; those ids only DO anything if something
issues an EnableCharacterAI for them. proximity_wake's event body
($Event(99055500): wait for player-in-radius -> EnableCharacterAI) already
exists, compiled, in the shipped common_func.emevd. So waking the stamped
parts needs only one thing per part: a registration

    $InitializeCommonEvent(0, 99055500, <eid>, <radius>);

appended to the map's constructor event ($Event(0)). That is a single
InitializeCommonEvent instruction (class 2000, index 0) — exactly the
append-only operation serialize.EmevdEditor supports. So this runs as a
pure-Python pass over the decompressed per-map EMEVD at rando time: no
DSAS3, no Windows dependency, no patched_emevd/ rebuild, and it can't trip
a source-level compile ceiling because there is no compile.

What it does NOT touch
----------------------
common_func.emevd (the 99055500 BODY already ships there — we only add
registrations to per-map files), and any event other than the
constructor. Existing instructions are never edited, only relocated by the
append serializer; see serialize.py.

Idempotent: re-running skips any (99055500, eid) registration already in
the constructor, so the pass is safe to run on its own output.
"""

import os

try:
    from . import emevd as _emevd
    from . import serialize as _serialize
except ImportError:                       # run as a loose script
    import emevd as _emevd
    import serialize as _serialize

WAKE_EVENT_ID = 99055500                  # proximity_wake body in common_func
DEFAULT_RADIUS = 15
_INIT_COMMON_EVENT = (2000, 0)            # InitializeCommonEvent class/index
_CONSTRUCTOR_EVENT_ID = 0                 # $Event(0) — the per-map constructor


def _existing_wake_eids(event, wake_event_id):
    """Entity ids already registered against wake_event_id in this event,
    so a re-run doesn't double-append. Reads each InitializeCommonEvent's
    args = [slot, common_event_id, eid, ...]."""
    import struct
    out = set()
    for instr in event.instructions:
        if (instr.instruction_class, instr.instruction_index) != _INIT_COMMON_EVENT:
            continue
        if instr.args_size < 12:           # need slot + event + at least eid
            continue
        n = instr.args_size // 4
        vals = struct.unpack_from("<%dI" % n, instr.args_raw, 0)
        if vals[1] == wake_event_id:
            out.add(vals[2])
    return out


def inject_wakes(raw, eids, radius=DEFAULT_RADIUS,
                 wake_event_id=WAKE_EVENT_ID):
    """Append a proximity-wake registration for each eid to the map's
    constructor event. Returns (new_bytes, n_appended). Idempotent;
    returns (raw, 0) unchanged if there's nothing to add or no
    constructor event in the file.
    """
    parsed = _emevd.EMEVD.parse(raw)
    ctor_index = next((i for i, e in enumerate(parsed.events)
                       if e.event_id == _CONSTRUCTOR_EVENT_ID), None)
    if ctor_index is None:
        return raw, 0
    already = _existing_wake_eids(parsed.events[ctor_index], wake_event_id)
    pending = [int(e) for e in eids if int(e) not in already]
    if not pending:
        return raw, 0
    editor = _serialize.EmevdEditor(raw)
    editor.append_instructions_to_event(ctor_index, [
        _serialize.NewInstruction(
            _INIT_COMMON_EVENT[0], _INIT_COMMON_EVENT[1],
            [0, wake_event_id, eid, radius])
        for eid in pending
    ])
    return editor.to_bytes(), len(pending)


def inject_wakes_dir(emevd_dir, catalog, radius=DEFAULT_RADIUS,
                     wake_event_id=WAKE_EVENT_ID, log=None):
    """Inject wakes into every decompressed .emevd in emevd_dir named by
    `catalog` ({map_stem: [eid, ...]}). Edits files in place.

    Returns (n_files, n_wakes). Per-file failures are caught and logged
    (never abort the whole pass for one bad/odd file); a file that can't
    be parsed or whose record sizes the append serializer doesn't support
    is skipped, leaving its bytes untouched.
    """
    n_files = n_wakes = 0
    for stem, eids in sorted(catalog.items()):
        if not eids:
            continue
        path = _find_emevd(emevd_dir, stem)
        if path is None:
            if log:
                log(f"  wake_inject: no EMEVD for {stem} (skipped)")
            continue
        try:
            with open(path, 'rb') as f:
                data = f.read()
            new_data, n = inject_wakes(data, eids, radius, wake_event_id)
            if n:
                with open(path, 'wb') as f:
                    f.write(new_data)
                n_files += 1
                n_wakes += n
        except Exception as e:             # noqa: BLE001 — one odd file mustn't kill the run
            if log:
                log(f"  wake_inject: {stem} skipped ({type(e).__name__}: {e})")
            continue
    return n_files, n_wakes


def _find_emevd(emevd_dir, stem):
    """Decompressed EMEVD on disk is '<stem>.emevd'. Tolerate a couple of
    spellings just in case."""
    for cand in (stem + '.emevd', stem, stem + '.emevd.dcx'):
        p = os.path.join(emevd_dir, cand)
        if os.path.isfile(p):
            return p
    return None
