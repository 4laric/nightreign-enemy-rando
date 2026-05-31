"""Tests for v0.24.14 name-composition stub. The rewriter doesn't call
these yet, but we want them solid before wire-in so the eventual flip
is just one decide_rewrites edit.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rewriter import compose_name, load_title_pool


class TestLoadTitlePool(unittest.TestCase):
    def test_loads_from_default_path(self):
        # Default path resolves to <project>/data/title_pool.json
        titles = load_title_pool()
        self.assertIsInstance(titles, list)
        self.assertGreater(len(titles), 0)
        for t in titles:
            self.assertIsInstance(t, str)
            self.assertTrue(t)  # non-empty

    def test_default_pool_contains_expected_entries(self):
        titles = load_title_pool()
        # Spot-check a few known entries to catch accidental clobbers
        self.assertIn('and more', titles)
        self.assertIn('the Nightlord', titles)
        self.assertIn('Lord of Blood', titles)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_title_pool('/nonexistent/path/title_pool.json')


class TestComposeNameFormat(unittest.TestCase):
    POOL = ['Naturalborn of the Void']  # length-1 pool → deterministic title

    def test_vanilla_to_vanilla_uses_arrow(self):
        result = compose_name(
            'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
            self.POOL, 42, show_arrow_prefix=True)
        self.assertEqual(
            result, 'Tree Sentinel → Tibia Mariner, Naturalborn of the Void')

    def test_heritage_no_original_drops_arrow(self):
        result = compose_name(
            None, 'Mohg', None, 'c5290', self.POOL, 42)
        self.assertEqual(result, 'Mohg, Naturalborn of the Void')

    def test_same_c_prefix_drops_arrow(self):
        # When original and replacement are the same c-prefix, no swap
        # actually happened — just emit "<name>, <title>"
        result = compose_name(
            'Banished Knight', 'Banished Knight', 'c4170', 'c4170',
            self.POOL, 42)
        self.assertEqual(result, 'Banished Knight, Naturalborn of the Void')

    def test_same_name_diff_c_drops_arrow(self):
        # Different c-prefixes that happen to share a display name
        # (the vanilla NpcName has multiple "Fell Omen" entries at
        # different IDs). Still considered a no-swap visually.
        result = compose_name(
            'Fell Omen', 'Fell Omen', 'c2031', 'c2030',
            self.POOL, 42)
        self.assertEqual(result, 'Fell Omen, Naturalborn of the Void')


class TestComposeNameDeterminism(unittest.TestCase):
    POOL = ['t0', 't1', 't2', 't3', 't4', 't5', 't6', 't7']

    def test_same_inputs_same_output(self):
        # Repeated calls with the same args produce the same result
        r1 = compose_name('A', 'B', 'c1', 'c2', self.POOL, 42)
        r2 = compose_name('A', 'B', 'c1', 'c2', self.POOL, 42)
        self.assertEqual(r1, r2)

    def test_seed_affects_title(self):
        # Different seeds should generally produce different titles
        # (collision possible but unlikely across many seeds)
        results = set()
        for seed in range(20):
            r = compose_name('A', 'B', 'c1', 'c2', self.POOL, seed)
            results.add(r)
        # Pool has 8 entries; across 20 seeds we should see >1 unique
        self.assertGreater(len(results), 1,
            "Different seeds collapsed to one title — hash distribution broken")

    def test_pair_affects_title(self):
        # Different (original, replacement) pairs roll independently
        r1 = compose_name('A', 'B', 'c1', 'c2', self.POOL, 42)
        r2 = compose_name('A', 'B', 'c3', 'c4', self.POOL, 42)
        # Could collide by chance but usually different
        pair_results = set()
        for c1 in ('c1', 'c2', 'c3'):
            for c2 in ('c4', 'c5', 'c6'):
                pair_results.add(
                    compose_name('A', 'B', c1, c2, self.POOL, 42))
        self.assertGreater(len(pair_results), 1)


class TestComposeNameEdgeCases(unittest.TestCase):
    def test_empty_pool_raises(self):
        with self.assertRaises(ValueError):
            compose_name('A', 'B', 'c1', 'c2', [], 42)

    def test_unicode_safe(self):
        # Replacement names from heritage imports could contain accents,
        # quotes, em-dashes, etc. Make sure the hash key encoding handles it.
        r = compose_name(
            'Margit', 'Mohg, Lord of Blood',
            'c2030', 'c5290', ['the Cursed'], 42)
        self.assertIn('Mohg, Lord of Blood', r)
        self.assertIn('the Cursed', r)


class TestComposeNameTemplates(unittest.TestCase):
    """v2 template syntax: {r} and {o} placeholders."""

    def test_template_r_only(self):
        r = compose_name(
            'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
            ['The Dread Pirate {r}'], 42)
        self.assertEqual(r, 'The Dread Pirate Tibia Mariner')

    def test_template_o_and_r(self):
        r = compose_name(
            'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
            ["{o} 'The Rock' {r}"], 42)
        self.assertEqual(r, "Tree Sentinel 'The Rock' Tibia Mariner")

    def test_template_o_returns_none_when_no_original(self):
        # v0.24.108: heritage case with {o}-referencing template now
        # returns None (was: substituted {o} with replacement, producing
        # "Mohg 'The Rock' Mohg"). Returning None lets the caller fall
        # through to non-composed output, which reads better than
        # tautological substitutions.
        r = compose_name(
            None, 'Mohg', None, 'c5290',
            ["{o} 'The Rock' {r}"], 42)
        self.assertIsNone(r)

    def test_template_no_comma_prefix(self):
        # Templates REPLACE the name; they don't get the "<name>, "
        # prefix that epithets do
        r = compose_name(
            'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
            ["'Stone Cold' {r}"], 42)
        self.assertFalse(r.startswith('Tibia Mariner,'))
        self.assertFalse(r.startswith('Tree Sentinel'))
        self.assertEqual(r, "'Stone Cold' Tibia Mariner")

    def test_mixed_pool_routes_correctly(self):
        # A pool can contain both templates and epithets; the dispatcher
        # picks behavior per-entry based on placeholder presence
        pool = ['Beast of Night', 'The Dread Pirate {r}']
        results = set()
        for seed in range(50):
            results.add(compose_name(
                'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
                pool, seed, show_arrow_prefix=True))
        # Over 50 seeds we should see both formats
        epithet_form = 'Tree Sentinel → Tibia Mariner, Beast of Night'
        template_form = 'The Dread Pirate Tibia Mariner'
        self.assertIn(epithet_form, results)
        self.assertIn(template_form, results)


# ===========================================================================
# v0.24.108: {o}-as-epithet (OBJECT-EPITHET) + heritage-with-{o} returns None
# ===========================================================================
class TestObjectEpithetForm(unittest.TestCase):
    """Titles containing {o} but NOT {r} are object-epithets: the {o}
    placeholder substitutes original_name, and the whole thing reads as
    an epithet appended after comma."""

    def test_object_epithet_substitutes_original(self):
        result = compose_name(
            'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
            ['of {o} fame'], 42, show_arrow_prefix=True)
        self.assertEqual(
            result, 'Tree Sentinel → Tibia Mariner, of Tree Sentinel fame')

    def test_object_epithet_same_cprefix_drops_arrow(self):
        result = compose_name(
            'Banished Knight', 'Banished Knight', 'c4170', 'c4170',
            ['of {o} fame'], 42)
        # Same name, same prefix → no arrow; result is the epithet form
        # WITHOUT the arrow prefix
        self.assertEqual(
            result, 'Banished Knight, of Banished Knight fame')


class TestHeritageWithObjectReference(unittest.TestCase):
    """Heritage cases (original_name=None) skip titles that reference
    {o} — return None signals caller to fall through."""

    def test_object_epithet_with_heritage_returns_none(self):
        result = compose_name(
            None, 'Centipede Demon', None, 'c7710',
            ['of {o} fame'], 42)
        self.assertIsNone(result)

    def test_template_with_o_and_r_heritage_returns_none(self):
        result = compose_name(
            None, 'Centipede Demon', None, 'c7710',
            ['{r} née {o}'], 42)
        self.assertIsNone(result)

    def test_template_with_only_r_heritage_works(self):
        # No {o} reference → no skip; pure-{r} templates still work
        result = compose_name(
            None, 'Centipede Demon', None, 'c7710',
            ['The Notorious {r}'], 42)
        self.assertEqual(result, 'The Notorious Centipede Demon')

    def test_plain_epithet_heritage_works(self):
        # Pure epithets (no placeholders) still work in heritage
        result = compose_name(
            None, 'Centipede Demon', None, 'c7710',
            ['the Nightlord'], 42)
        self.assertEqual(result, 'Centipede Demon, the Nightlord')


class TestNeeBridgeForm(unittest.TestCase):
    """{r} née {o} renders 'replacement née original' — etymologically
    correct French (née = born as, refers to the original/maiden name)."""

    def test_nee_substitutes_both(self):
        result = compose_name(
            'Tree Sentinel', 'Tibia Mariner', 'c4500', 'c4910',
            ['{r} née {o}'], 42)
        self.assertEqual(result, 'Tibia Mariner née Tree Sentinel')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    n_ok = result.testsRun - len(result.failures) - len(result.errors)
    print(f"\n{n_ok}/{result.testsRun} passed")
    sys.exit(0 if result.wasSuccessful() else 1)
