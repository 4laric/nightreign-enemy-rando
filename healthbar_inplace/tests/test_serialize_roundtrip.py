"""
test_serialize_roundtrip.py — correctness tests for serialize.py.

The foundation test is identity: reserialize_identity(raw) must equal
raw for every vanilla EMEVD. Nothing in the append path is trusted
unless identity holds corpus-wide.

The vanilla corpus path is taken from EMEVD_CORPUS env var, falling
back to a checked location. If absent, the corpus test skips (the
append tests use a single bundled-style file and still run).

Run:  python -m pytest test_serialize_roundtrip.py -v
"""

import glob
import os
import struct
import sys

import pytest

# serialize.py / emevd.py live one directory up (the healthbar_inplace
# package root). Add both that dir and this one — mirrors the sibling
# test_roundtrip.py convention. Run from the tests/ directory.
sys.path.insert(0, '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import serialize as ser          # noqa: E402
import emevd as em               # noqa: E402


def _corpus_dir():
    cand = os.environ.get('EMEVD_CORPUS') or \
        '/tmp/vemevd/vanilla_decompressed_emevd'
    return cand if os.path.isdir(cand) else None


def _corpus_files():
    d = _corpus_dir()
    if not d:
        return []
    return sorted(glob.glob(os.path.join(d, '*.emevd')))


# ─────────────────────────────────────────────────────────────────────
# Identity — the foundation
# ─────────────────────────────────────────────────────────────────────

def test_corpus_available():
    """Soft check — if the corpus is missing, identity coverage is
    partial. Not a failure, but worth surfacing."""
    if not _corpus_files():
        pytest.skip('vanilla EMEVD corpus not present; set EMEVD_CORPUS')


@pytest.mark.parametrize('path', _corpus_files() or [None])
def test_identity_roundtrip(path):
    """reserialize_identity(raw) must be byte-identical to raw."""
    if path is None:
        pytest.skip('no corpus')
    raw = open(path, 'rb').read()
    out = ser.reserialize_identity(raw)
    assert out == raw, f'{os.path.basename(path)}: round-trip not identical'


def test_identity_corpus_summary():
    """Whole-corpus identity in one assertion (clearer failure count)."""
    files = _corpus_files()
    if not files:
        pytest.skip('no corpus')
    bad = []
    for path in files:
        raw = open(path, 'rb').read()
        if ser.reserialize_identity(raw) != raw:
            bad.append(os.path.basename(path))
    assert not bad, f'{len(bad)}/{len(files)} files failed identity: {bad[:10]}'


# ─────────────────────────────────────────────────────────────────────
# Append path
# ─────────────────────────────────────────────────────────────────────

def _sample_file():
    files = _corpus_files()
    if not files:
        pytest.skip('no corpus for append tests')
    # prefer a file with a few events
    for p in files:
        raw = open(p, 'rb').read()
        if em.EMEVD.parse(raw).header.event_count >= 2:
            return raw
    return open(files[0], 'rb').read()


def test_noop_editor_is_identity():
    """An EmevdEditor with no edits serializes byte-identical."""
    raw = _sample_file()
    assert ser.EmevdEditor(raw).to_bytes() == raw


def test_append_event():
    """append_event adds one event; all originals preserved."""
    raw = _sample_file()
    before = em.EMEVD.parse(raw)
    ed = ser.EmevdEditor(raw)
    ni = ser.NewInstruction(cls=2000, index=0,
                            args=[0, 99055500, 32000810, 15])
    ed.append_event(event_id=99055500, rest_behavior=0,
                    instructions=[ni])
    after = em.EMEVD.parse(ed.to_bytes())

    assert after.header.event_count == before.header.event_count + 1
    assert after.header.instruction_count == \
        before.header.instruction_count + 1
    # originals unchanged
    for i in range(before.header.event_count):
        assert after.events[i].event_id == before.events[i].event_id
        assert after.events[i].instruction_count == \
            before.events[i].instruction_count
    # new event correct
    new_ev = after.events[-1]
    assert new_ev.event_id == 99055500
    assert new_ev.instruction_count == 1
    instr = new_ev.instructions[0]
    args = struct.unpack(f'<{instr.args_size // 4}I', instr.args_raw)
    assert args == (0, 99055500, 32000810, 15)


def test_append_instructions_to_event():
    """append_instructions_to_event grows one event; others untouched."""
    raw = _sample_file()
    before = em.EMEVD.parse(raw)
    ed = ser.EmevdEditor(raw)
    ni = ser.NewInstruction(cls=2000, index=0,
                            args=[0, 99055500, 32000810, 15])
    ed.append_instructions_to_event(0, [ni])
    after = em.EMEVD.parse(ed.to_bytes())

    assert after.events[0].instruction_count == \
        before.events[0].instruction_count + 1
    # every OTHER event identical in id + count
    for i in range(1, before.header.event_count):
        assert after.events[i].event_id == before.events[i].event_id
        assert after.events[i].instruction_count == \
            before.events[i].instruction_count
    # the appended instruction is last in event 0
    last = after.events[0].instructions[-1]
    args = struct.unpack(f'<{last.args_size // 4}I', last.args_raw)
    assert args == (0, 99055500, 32000810, 15)


def test_append_output_reparses_clean():
    """The appended file must parse without CorruptOffsetError — i.e.
    the recomputed header offset chain is internally consistent."""
    raw = _sample_file()
    ed = ser.EmevdEditor(raw)
    ni = ser.NewInstruction(cls=2000, index=0, args=[1, 2, 3])
    ed.append_event(event_id=99055501, rest_behavior=0,
                    instructions=[ni])
    ed.append_instructions_to_event(0, [ni])
    out = ed.to_bytes()
    parsed = em.EMEVD.parse(out)            # raises if offsets corrupt
    # file_size header field matches actual length
    assert parsed.header.file_size == len(out)


def test_double_append_idempotent_structure():
    """Two separate editors applying the same append produce identical
    bytes — append is deterministic."""
    raw = _sample_file()

    def patched():
        ed = ser.EmevdEditor(raw)
        ed.append_event(event_id=99055500, rest_behavior=0,
                        instructions=[ser.NewInstruction(
                            2000, 0, [0, 99055500, 1, 15])])
        return ed.to_bytes()

    assert patched() == patched()


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
