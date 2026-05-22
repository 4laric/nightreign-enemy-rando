"""v0.24.95-patch16: lock-in test for 'Unused' variant marker filter.

c5840 Black Knight variant 58400000 'Black Knight CASTLE (Unused)' is
MMV's only NpcParam with '(Unused)' in name — deliberately non-functional.
If the filter loses 'Unused', the rando can pick this variant and place an
inert chr that just stands there.
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import oops_v3


def test_unused_in_trigger_markers():
    """'Unused' must remain in V3_VARIANT_TRIGGER_MARKERS."""
    assert 'Unused' in oops_v3.V3_VARIANT_TRIGGER_MARKERS, (
        "'Unused' marker missing — c5840 variant 58400000 will leak into "
        "placement pool and cause stand-still bugs.")


def test_c5840_unused_variant_filtered_at_load():
    """At load_data time, c5840's '(Unused)' variant must NOT survive."""
    roster, tags = oops_v3.load_data()
    prefix_variants, _ = oops_v3.build_per_prefix_data(roster)
    c5840_vars = prefix_variants.get('c5840', [])
    surviving_ids = {v.get('npc_param_id') for v in c5840_vars}
    assert 58400000 not in surviving_ids, (
        "c5840 variant 58400000 'Black Knight CASTLE (Unused)' leaked into "
        "post-load variant pool. The (Unused) filter is not catching it.")
