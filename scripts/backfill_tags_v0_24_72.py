"""v0.24.72 tag-backfill: fill in anim_class/size_class for untagged chrs.

Each entry is justified by sibling pattern OR name → known-chr mapping.
Confidence levels:
  'sibling' — adjacent c-prefix in same family has same anim/size
  'family' — c-prefix family pattern (Crab, Dog, Soldier, etc.)
  'known' — chr is well-known from ER/SOTE/DS3/DS1, anim/size verifiable
  'low' — best guess, may need correction

This script edits nr_enemy_tags.json AND mmv_imports.json in-place.
Marks each backfilled entry with _tags_backfilled_v0_24_72=True for
traceability.

Tags NOT backfilled:
  - cinematic tier (System, Player Template, etc.) — not in swap pool
  - unknown-name entries (c3210, c4362, etc.) — no inference possible
  - very-low-confidence (c7910 Storm King, c52313 Executor) — skip
"""
import json
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAGS_PATH = os.path.join(ROOT, 'data', 'nr_enemy_tags.json')
MMV_PATH = os.path.join(ROOT, 'data', 'mmv_imports.json')

# (cp, anim_class, size_class, justification)
BACKFILL = [
    # === Crab family (c2270-c2277) — all aquatic ===
    ('c2273', 'aquatic', 'S',  'family: Crab small variants are aquatic/S'),
    ('c2274', 'aquatic', 'XL', 'family: Giant Sleep Crab matches c2270/c2272 Giant Crab pattern'),
    ('c2275', 'aquatic', 'S',  'family: Crab variant'),
    ('c2277', 'aquatic', 'S',  'family: Crab (Golden Tufts) variant'),
    # === Frenzied Nomad — humanoid M (already excluded as target but tag for completeness) ===
    ('c3201', 'humanoid', 'M', 'sibling: c3200 Nomadic Merchant humanoid/M'),
    # === Ancestral Follower family ===
    # In ER, regular Ancestral Followers are deer-like (quadruped) wearing antlers.
    # Putrid AF (c3361) is the humanoid-on-deer mount variant.
    ('c3360', 'quadruped',  'L', 'known: ER Ancestral Follower = antlered deer-like, quadruped L'),
    ('c3370', 'humanoid',   'L', 'family: Shaman variant — anthropomorphic, matches c3371 humanoid/L'),
    # === Spiritcaller Snail boss form ===
    ('c4140', 'misc', 'M', 'known: Spiritcaller Snail = stationary misc, boss form M-sized'),
    # === Dog family (c4160-c4167) ===
    ('c4162', 'quadruped', 'S', 'family: Large Braided Dog = dog, c416x = quadruped/S'),
    ('c4163', 'quadruped', 'S', 'family: Braided Dog = dog'),
    ('c4167', 'quadruped', 'S', 'family: Mushroom Dog = dog'),
    # === Scarab family ===
    ('c4190', 'misc', 'S', 'family: Scarab, sibling c4191 misc/S'),
    ('c4192', 'misc', 'S', 'family: Scarab variant'),
    # === DLC Soldier/Knight variants (c431x, c4356, c4376) ===
    ('c4312', 'humanoid', 'M', 'family: Soldier — c4311/c4313/c4314/c4315 all humanoid/M'),
    ('c4316', 'humanoid', 'M', 'family: Haligtree Soldier matches c431x'),
    ('c4356', 'humanoid', 'M', 'family: Knight — c4351-c4354 all humanoid/M'),
    ('c4358', 'humanoid', 'M', 'family: Castle Knight Variant matches Knight family'),
    ('c4376', 'humanoid', 'M', 'family: Haligtree Foot Soldier matches c437x foot soldiers'),
    # === Knight's Horse family ===
    ('c4361', 'quadruped_large', 'L', 'family: Godrick Knight\'s Horse, sibling c4363 quadruped_large/L'),
    # === Land Squirt boss ===
    ('c4441', 'aquatic', 'L', 'family: Land Squirt Boss = bigger version of c4440 aquatic/M'),
    ('c4442', 'aquatic', 'M', 'family: Land Squirt Variant = small/M variant of c4440'),
    # === Walking Mausoleum — already has sz=XXL, need ac ===
    ('c4450', 'large_boss_ground', 'XXL', 'known: Walking Mausoleum = huge slow crawler, large_boss_ground'),
    # === Miranda Sprout family ===
    ('c4482', 'large_boss_ground', 'XL', 'family: Giant Fading Miranda matches c4480 large_boss_ground/XL'),
    ('c4483', 'misc',               'M', 'family: Fading Miranda Sprout matches c4481 misc/M'),
    # === Troll family — THE FIX ===
    ('c4601', 'humanoid', 'XXL', 'CONFIRMED by user; sibling c4600/c4602/c4603 all humanoid/XXL'),
    # === Ulcerated Tree Spirit Variant ===
    ('c4641', 'large_boss_ground', 'XL', 'sibling: c4640 Ulcerated Tree Spirit large_boss_ground/XXL; variant smaller'),
    # === Ancestor Spirit — has ac=humanoid, need sz ===
    ('c4670', 'humanoid', 'XL', 'known: ER Ancestor Spirit = giant deer-spirit, field_boss XL'),
    # === Grafted Scion — has ac=humanoid, need sz ===
    ('c4690', 'humanoid', 'L',  'known: ER Grafted Scion = misshapen humanoid, miniboss L'),
    # === Lord of Blood Spear ===
    ('c4801', 'humanoid', 'XL', 'sibling: c4800 Mohg humanoid/XL; Lord of Blood Spear = Mohg variant'),
    # === Erdtree Avatar Variant ===
    ('c4811', 'quadruped_large', 'XL', 'sibling: c4810 Erdtree Avatar quadruped_large/XL'),
    # === MMV imports with partial tags ===
    # c5000 has size=XL, missing anim. Commander Gaius = centaur in SOTE.
    ('c5000', 'quadruped_large', 'XL', 'known: Commander Gaius = boar-mounted centaur, quadruped_large'),
    # c5230 has size=XXL, missing anim. Scadutree Avatar = giant avatar like Erdtree.
    ('c5230', 'quadruped_large', 'XXL', 'known: Scadutree Avatar = SOTE giant avatar, matches c4810'),
    # === Mausoleum/Recluse remembrance variants ===
    ('c52309', 'humanoid', 'M', 'known: Priestess Duchess = humanoid female caster, M'),
    ('c52312', 'humanoid', 'L', 'known: Witch of the Wheel = wheel-bound humanoid, L due to wheel'),
    # c52313 Executor — too uncertain, skip
    # === MMV imports with partial tags ===
    ('c5930', 'humanoid', 'XL', 'known: Giant Skeleton (ER/DS3) = giant humanoid skeleton XL'),
    ('c6220', 'humanoid', 'L',  'known: Fire Demon (DS3) = horned humanoid L'),
    # === Dreg Heap chrs (DS3 DLC) ===
    ('c7610', 'humanoid', 'L',  'known: Traitorous Straghess = humanoid field_boss L; ac=humanoid set'),
    ('c7650', 'humanoid', 'M',  'known: Dreg Corpse (DS3 RoR) = humanoid grunt M'),
    ('c7651', 'humanoid', 'L',  'known: Large Dreg Corpse = humanoid miniboss L'),
    ('c7660', 'humanoid', 'M',  'known: Dreg Wormface = humanoid field_boss M'),
    # === DS3 boss script-spawns ===
    ('c7900', 'humanoid', 'L', 'known: Nameless King = humanoid post-dismount, L without mount'),
    # c7910 Storm King — too uncertain (dragon mount? standalone?). Skip.
    # === Demon from Below — already has sz=L, need ac ===
    ('c7930', 'humanoid', 'L', 'known: Demon from Below = winged humanoid demon'),
    # === Manus ===
    ('c8500', 'humanoid', 'L', 'known: Manus (DS1) = ape-like humanoid L'),
]


def apply_backfill_to(tag_dict, label):
    """Apply BACKFILL entries to the given tag_dict (in-place).
    Returns (changes, skipped) string lists."""
    changes = []
    skipped = []
    for cp, ac, sz, justification in BACKFILL:
        if cp not in tag_dict:
            continue  # Not in this file; might be in the other
        entry = tag_dict[cp]
        old_ac = entry.get('anim_class')
        old_sz = entry.get('size_class')
        # Only fill in MISSING fields. Don't overwrite existing data
        # (existing data might have been hand-verified).
        new_ac = ac if old_ac is None else old_ac
        new_sz = sz if old_sz is None else old_sz
        if new_ac == old_ac and new_sz == old_sz:
            skipped.append(f"  {cp}: already fully tagged ({old_ac}/{old_sz})")
            continue
        entry['anim_class'] = new_ac
        entry['size_class'] = new_sz
        entry['_tags_backfilled_v0_24_72'] = True
        entry['_backfill_justification'] = justification
        changes.append(f"  {cp}: ({old_ac}/{old_sz}) → ({new_ac}/{new_sz})")
    print(f"  [{label}] {len(changes)} backfilled, {len(skipped)} already-tagged")
    return changes, skipped


def main(dry_run=False):
    # Load both files
    with open(TAGS_PATH) as f:
        nr_tags = json.load(f)
    with open(MMV_PATH) as f:
        mmv = json.load(f)
    mmv_tags = mmv.get('tags', {})

    print(f"Loaded {len(nr_tags)} entries from nr_enemy_tags.json")
    print(f"Loaded {len(mmv_tags)} entries from mmv_imports.json (tags section)")
    print(f"Backfill plan: {len(BACKFILL)} entries\n")

    all_changes = []
    all_changes += apply_backfill_to(nr_tags, 'nr_enemy_tags')
    all_changes += apply_backfill_to(mmv_tags, 'mmv_imports')

    # Check for cps in BACKFILL that weren't found in EITHER file
    bf_cps = {cp for cp, _, _, _ in BACKFILL}
    found_cps = set(nr_tags.keys()) | set(mmv_tags.keys())
    missing = bf_cps - found_cps
    if missing:
        print(f"\nWARNING: {len(missing)} backfill targets not found in either file:")
        for cp in sorted(missing):
            print(f"  {cp}")

    if not dry_run:
        with open(TAGS_PATH, 'w') as f:
            json.dump(nr_tags, f, indent=2, sort_keys=True)
        with open(MMV_PATH, 'w') as f:
            json.dump(mmv, f, indent=2, sort_keys=True)
        print(f"\nWrote updated nr_enemy_tags.json ({len(nr_tags)} entries)")
        print(f"Wrote updated mmv_imports.json ({len(mmv_tags)} tag entries)")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    main(dry_run=dry_run)
