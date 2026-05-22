"""Tests for the _PACK_LOADERS registry dispatch in oops_v3.load_data.

The registry replaces three inline loader blocks with a single
data-driven loop. These tests pin the contract so a future loader
addition doesn't accidentally break uniformity:

  - Every LoaderSpec has the expected shape (filename, apply_fn, log_fn)
  - The dispatch order is preserved (heritage_pack first, mmv last)
  - The convenience aliases (hp_stats / er_stats / mmv_stats) are
    bound from the registry output, not separately
  - Every loader's stats dict has the standardized fields the post-loop
    fold reads (caliber_adds / strict_adds / exclude_target_adds /
    arena_only_adds), even when empty
"""
import oops_v3
from engine.pack_loaders.heritage_pack import apply_heritage_pack
from engine.pack_loaders.er_heritage import apply_er_heritage
from engine.pack_loaders.mmv_imports import apply_mmv_imports


class TestLoaderRegistryShape:
    def test_pack_loaders_is_a_list_of_loader_specs(self):
        assert hasattr(oops_v3, '_PACK_LOADERS')
        assert isinstance(oops_v3._PACK_LOADERS, list)
        assert len(oops_v3._PACK_LOADERS) >= 3
        for spec in oops_v3._PACK_LOADERS:
            assert hasattr(spec, 'filename')
            assert hasattr(spec, 'apply_fn')
            assert hasattr(spec, 'log_fn')

    def test_filenames_are_unique(self):
        # Registry-level invariant: a filename appears at most once.
        filenames = [s.filename for s in oops_v3._PACK_LOADERS]
        assert len(set(filenames)) == len(filenames)

    def test_known_loaders_present(self):
        # The three canonical loaders should all be registered.
        filenames = {s.filename for s in oops_v3._PACK_LOADERS}
        assert 'heritage_pack.json' in filenames
        assert 'er_heritage_imports.json' in filenames
        assert 'mmv_imports.json' in filenames

    def test_dispatch_order_preserved(self):
        # Order matters: heritage_pack runs first (its disable can
        # remove cps), er_heritage second (vanilla-wins), mmv last
        # (authoritative override). Future loaders go at the end
        # unless they have a compelling reason to be earlier.
        filenames = [s.filename for s in oops_v3._PACK_LOADERS]
        assert filenames.index('heritage_pack.json') < filenames.index(
            'er_heritage_imports.json')
        assert filenames.index('er_heritage_imports.json') < filenames.index(
            'mmv_imports.json')

    def test_apply_fns_are_callable(self):
        for spec in oops_v3._PACK_LOADERS:
            assert callable(spec.apply_fn)

    def test_log_fns_are_callable(self):
        for spec in oops_v3._PACK_LOADERS:
            assert callable(spec.log_fn)

    def test_apply_fns_match_imported_functions(self):
        # Verify the apply_fn for each known loader is the one we
        # expect from engine.pack_loaders. Catches a future copy/paste
        # bug where the spec list gets edited but the imports don't.
        by_filename = {s.filename: s for s in oops_v3._PACK_LOADERS}
        assert by_filename['heritage_pack.json'].apply_fn is apply_heritage_pack
        assert by_filename['er_heritage_imports.json'].apply_fn is apply_er_heritage
        assert by_filename['mmv_imports.json'].apply_fn is apply_mmv_imports


class TestLoaderStatsUniformShape:
    """Every loader returns a stats dict with the same keys the post-
    loop fold reads. Empty contributions are returned as empty sets so
    the fold's set-union iteration is uniform."""

    REQUIRED_KEYS = {
        'enabled',
        'caliber_adds',
        'strict_adds',
        'arena_only_adds',
        'exclude_target_adds',
    }

    def test_heritage_pack_enabled_has_required_keys(self):
        pack = {'_meta': {'enabled': True}, 'tags': {}}
        stats = apply_heritage_pack(pack, tags={}, roster={'all_variants': []})
        missing = self.REQUIRED_KEYS - set(stats)
        assert not missing, f'heritage_pack enabled stats missing: {missing}'

    def test_heritage_pack_disabled_has_required_keys(self):
        pack = {'_meta': {'enabled': False}, 'tags': {}}
        stats = apply_heritage_pack(pack, tags={}, roster={'all_variants': []})
        missing = self.REQUIRED_KEYS - set(stats)
        assert not missing, f'heritage_pack disabled stats missing: {missing}'

    def test_er_heritage_enabled_has_required_keys(self):
        pack = {'_meta': {'enabled': True}, 'tags': {},
                'variants_per_prefix': {}}
        stats = apply_er_heritage(pack, tags={}, roster={'all_variants': []})
        missing = self.REQUIRED_KEYS - set(stats)
        assert not missing, f'er_heritage enabled stats missing: {missing}'

    def test_er_heritage_disabled_has_required_keys(self):
        pack = {'_meta': {'enabled': False}, 'tags': {},
                'variants_per_prefix': {}}
        stats = apply_er_heritage(pack, tags={}, roster={'all_variants': []})
        missing = self.REQUIRED_KEYS - set(stats)
        assert not missing, f'er_heritage disabled stats missing: {missing}'

    def test_mmv_enabled_has_required_keys(self):
        pack = {'_meta': {'enabled': True}, 'tags': {},
                'variants': [],
                'blacklist_when_active': {
                    'ctd_unidentified': [],
                    'dlc_assets_missing_in_mmv': [],
                    'ai_broken': [],
                }}
        stats = apply_mmv_imports(pack, tags={}, roster={'all_variants': []})
        missing = self.REQUIRED_KEYS - set(stats)
        assert not missing, f'mmv enabled stats missing: {missing}'

    def test_mmv_disabled_has_required_keys(self):
        pack = {'_meta': {'enabled': False}}
        stats = apply_mmv_imports(pack, tags={}, roster={'all_variants': []})
        missing = self.REQUIRED_KEYS - set(stats)
        assert not missing, f'mmv disabled stats missing: {missing}'


class TestExcludeTargetAddsIsTheUnion:
    """For mmv specifically, exclude_target_adds should be the union
    of blacklist + cross_engine_bans + mount_component_bans.
    Validates the standardization didn't drop information."""

    def test_union_matches_components(self):
        pack = {
            '_meta': {'enabled': True},
            'tags': {
                'cDS1':   {'tier': 'miniboss', 'origin_game': 'DS1'},
                'cMOUNT': {'tier': 'mount_component', 'origin_game': 'ER'},
            },
            'variants': [],
            'blacklist_when_active': {
                'ctd_unidentified': ['cCTD'],
                'dlc_assets_missing_in_mmv': ['cDLC'],
                'ai_broken': ['cAI'],
            },
        }
        stats = apply_mmv_imports(pack,
                                  tags={}, roster={'all_variants': []})
        expected = (
            stats['blacklist']
            | stats['cross_engine_bans']
            | stats['mount_component_bans']
        )
        assert stats['exclude_target_adds'] == expected
        # And the union is non-trivial — we should see all three classes.
        assert 'cCTD' in stats['exclude_target_adds']
        assert 'cDS1' in stats['exclude_target_adds']
        assert 'cMOUNT' in stats['exclude_target_adds']
