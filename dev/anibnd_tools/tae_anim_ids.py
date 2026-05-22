#!/usr/bin/env python3
"""Skim animation IDs from a chr's TAE inside an anibnd.

Usage:
    python3 tae_anim_ids.py <anibnd_path> [<anibnd_path> ...]

For variant chrs whose anibnd is skeleton-only (e.g., c4441.anibnd has only
skeleton.hkx), no TAE is present — these chrs inherit anims from their
parent chr (c4441 → c4440). Returns None for those.

Useful for entrance-animation classification (v0.24.79+). Confirmed pattern:
- chrs WITHOUT anim 9000: bespoke cinematic intro (GIGA bosses etc.) — NOT
  emerge_from_ground
- chrs WITH anim 9000: generic "encounter wake-up" — NECESSARY but not
  SUFFICIENT for emerge classification. Real signature requires event-level
  TAE parsing (not implemented yet — see comment in entrance_animations.json
  _meta.tae_analysis_findings.next_step).
"""
import struct
import sys
import os
from bnd4_reader import parse_bnd4, extract_entry


def get_chr_anim_ids(anibnd_path):
    """Return set of animation IDs from the chr's own TAE, or None if no TAE.

    A None return means the chr is skeleton-only and inherits anims from a
    parent chr (e.g., c4441 → c4440). The caller is responsible for parent
    resolution if needed.
    """
    with open(anibnd_path, 'rb') as f:
        data = f.read()
    info = parse_bnd4(data)
    for e in info['entries']:
        if e['name'].lower().endswith('.tae'):
            tae = extract_entry(data, e)
            if tae[:4] != b'TAE ' or len(tae) < 0x110:
                return None
            anim_count = struct.unpack_from('<I', tae, 0x54)[0]
            if not (0 < anim_count < 1000):
                return None
            return set(
                struct.unpack_from('<I', tae, 0x110 + i * 16)[0]
                for i in range(anim_count)
            )
    return None


if __name__ == '__main__':
    for path in sys.argv[1:]:
        ids = get_chr_anim_ids(path)
        name = os.path.basename(path)
        if ids is None:
            print(f'{name}: skeleton-only (inherits from parent)')
        else:
            has_9000 = 9000 in ids
            print(f'{name}: {len(ids)} anims, has 9000? {has_9000}')
