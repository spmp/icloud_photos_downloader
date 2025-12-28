"""Tests for Immich plugin"""

import argparse
import unittest
from argparse import ArgumentParser, Namespace
from unittest.mock import Mock, patch

from plugins.immich.immich import AlbumRule, ImmichPlugin, _parse_sizes
from pyicloud_ipd.services.photos import PhotoAsset


class TestParseSizes(unittest.TestCase):
    """Test _parse_sizes helper function"""

    def test_parse_sizes_none(self):
        """Test parsing None returns all sizes"""
        result = _parse_sizes(None)
        self.assertEqual(
            result, ['original', 'adjusted', 'alternative', 'medium', 'thumb']
        )

    def test_parse_sizes_comma_separated(self):
        """Test parsing comma-separated size list"""
        result = _parse_sizes('original,medium')
        self.assertEqual(result, ['original', 'medium'])

    def test_parse_sizes_single(self):
        """Test parsing single size"""
        result = _parse_sizes('adjusted')
        self.assertEqual(result, ['adjusted'])

    def test_parse_sizes_with_spaces(self):
        """Test parsing with spaces around commas"""
        result = _parse_sizes('original, medium, adjusted')
        self.assertEqual(result, ['original', 'medium', 'adjusted'])

    def test_parse_sizes_invalid_raises(self):
        """Test parsing invalid size raises ArgumentTypeError"""
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_sizes('invalid')


class TestAlbumRule(unittest.TestCase):
    """Test AlbumRule class"""

    def test_parse_single_size(self):
        """Test parsing rule with single size"""
        rule = AlbumRule('[original]:Originals')
        self.assertEqual(rule.size_targets, ['original'])
        self.assertEqual(rule.template, 'Originals')
        self.assertFalse(rule.match_all)

    def test_parse_multiple_sizes(self):
        """Test parsing rule with multiple sizes"""
        rule = AlbumRule('[original,adjusted]:High Quality')
        self.assertEqual(rule.size_targets, ['original', 'adjusted'])
        self.assertEqual(rule.template, 'High Quality')
        self.assertFalse(rule.match_all)

    def test_parse_all_sizes(self):
        """Test parsing rule without size filter (matches all)"""
        rule = AlbumRule('All Photos')
        self.assertTrue(rule.match_all)
        self.assertEqual(rule.template, 'All Photos')
        self.assertEqual(rule.size_targets, [])

    def test_parse_date_template(self):
        """Test parsing rule with date template"""
        rule = AlbumRule('[adjusted]:{:%Y/%m}')
        self.assertEqual(rule.size_targets, ['adjusted'])
        self.assertEqual(rule.template, '{:%Y/%m}')

    def test_parse_invalid_format_raises(self):
        """Test parsing empty template raises ValueError"""
        with self.assertRaises(ValueError):
            AlbumRule('')

    def test_parse_missing_bracket_raises(self):
        """Test parsing invalid sizes raises ValueError"""
        with self.assertRaises(ValueError):
            AlbumRule('[invalidsize]:Photos')

    def test_matches_wildcard(self):
        """Test match_all matches all sizes"""
        rule = AlbumRule('All Photos')
        self.assertTrue(rule.matches('original'))
        self.assertTrue(rule.matches('adjusted'))
        self.assertTrue(rule.matches('medium'))

    def test_matches_specific_size(self):
        """Test specific size matching"""
        rule = AlbumRule('[original]:Originals')
        self.assertTrue(rule.matches('original'))
        self.assertFalse(rule.matches('adjusted'))

    def test_matches_multiple_sizes(self):
        """Test multiple size matching"""
        rule = AlbumRule('[original,adjusted]:High Quality')
        self.assertTrue(rule.matches('original'))
        self.assertTrue(rule.matches('adjusted'))
        self.assertFalse(rule.matches('medium'))

    def test_str_representation(self):
        """Test string representation"""
        rule_specific = AlbumRule('[original]:Originals')
        self.assertEqual(repr(rule_specific), 'AlbumRule([original]:Originals)')

        rule_all = AlbumRule('All Photos')
        self.assertEqual(repr(rule_all), 'AlbumRule(all:All Photos)')


class TestImmichPluginInit(unittest.TestCase):
    """Test ImmichPlugin initialization and properties"""

    def test_plugin_initialization(self):
        """Test plugin can be initialized"""
        plugin = ImmichPlugin()
        self.assertIsNotNone(plugin)

    def test_plugin_name(self):
        """Test plugin name property"""
        plugin = ImmichPlugin()
        self.assertEqual(plugin.name, 'immich')

    def test_plugin_version(self):
        """Test plugin version property"""
        plugin = ImmichPlugin()
        # Version should be a string with format like "1.0.0"
        self.assertIsInstance(plugin.version, str)
        self.assertRegex(plugin.version, r'^\d+\.\d+\.\d+$')

    def test_plugin_description(self):
        """Test plugin description property"""
        plugin = ImmichPlugin()
        self.assertIsInstance(plugin.description, str)
        self.assertIn('immich', plugin.description.lower())

    def test_initial_state(self):
        """Test initial plugin state"""
        plugin = ImmichPlugin()
        # Configuration should be None/default
        self.assertIsNone(plugin.server_url)
        self.assertIsNone(plugin.api_key)
        self.assertIsNone(plugin.library_id)
        self.assertFalse(plugin.process_existing)
        self.assertEqual(plugin.scan_timeout, 5.0)
        self.assertEqual(plugin.poll_interval, 1.0)
        self.assertFalse(plugin.stack_media)
        self.assertEqual(plugin.favorite_sizes, [])
        self.assertEqual(plugin.album_rules, [])
        # Accumulators should be empty
        self.assertEqual(plugin.current_photo_files, [])
        self.assertEqual(plugin.current_immich_assets, [])


class TestImmichPluginArguments(unittest.TestCase):
    """Test ImmichPlugin CLI argument registration"""

    def test_add_arguments(self):
        """Test that plugin adds all expected CLI arguments"""
        parser = ArgumentParser()
        plugin = ImmichPlugin()
        plugin.add_arguments(parser)

        # Parse empty args to get defaults
        args = parser.parse_args([])

        # Check that all expected arguments exist
        self.assertTrue(hasattr(args, 'immich_server_url'))
        self.assertTrue(hasattr(args, 'immich_api_key'))
        self.assertTrue(hasattr(args, 'immich_library_id'))
        self.assertTrue(hasattr(args, 'immich_process_existing'))
        self.assertTrue(hasattr(args, 'immich_scan_timeout'))
        self.assertTrue(hasattr(args, 'immich_poll_interval'))
        self.assertTrue(hasattr(args, 'immich_stack_media'))
        self.assertTrue(hasattr(args, 'immich_favorite'))
        self.assertTrue(hasattr(args, 'associate_live_with_extra_sizes'))
        self.assertTrue(hasattr(args, 'immich_albums'))

    def test_default_arguments(self):
        """Test default values for CLI arguments"""
        parser = ArgumentParser()
        plugin = ImmichPlugin()
        plugin.add_arguments(parser)

        args = parser.parse_args([])

        self.assertIsNone(args.immich_server_url)
        self.assertIsNone(args.immich_api_key)
        self.assertIsNone(args.immich_library_id)
        self.assertFalse(args.immich_process_existing)
        self.assertEqual(args.immich_scan_timeout, 5.0)
        self.assertEqual(args.immich_poll_interval, 1.0)
        self.assertFalse(args.immich_stack_media)  # Default is False, not None
        self.assertFalse(args.immich_favorite)  # Default is False, not None
        self.assertFalse(args.associate_live_with_extra_sizes)  # Default is False
        self.assertIsNone(args.immich_albums)  # append action with no default


class TestImmichPluginConfiguration(unittest.TestCase):
    """Test ImmichPlugin configuration"""

    @patch('plugins.immich.immich.ImmichPlugin._test_immich_connection')
    def test_configure_basic(self, mock_test_conn):
        """Test basic plugin configuration"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        plugin.configure(config, None, None)

        self.assertEqual(plugin.server_url, 'http://localhost:2283')
        self.assertEqual(plugin.api_key, 'test-key')
        self.assertEqual(plugin.library_id, 'lib-123')
        self.assertFalse(plugin.process_existing)
        self.assertEqual(plugin.scan_timeout, 5.0)
        self.assertEqual(plugin.poll_interval, 1.0)

    @patch('plugins.immich.immich.ImmichPlugin._test_immich_connection')
    def test_configure_stacking_with_priority(self, mock_test_conn):
        """Test configuration with stacking and priority"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=['adjusted', 'original'],
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        plugin.configure(config, None, None)

        self.assertTrue(plugin.stack_media)
        self.assertEqual(plugin.stack_priority, ['adjusted', 'original'])

    @patch('plugins.immich.immich.ImmichPlugin._test_immich_connection')
    def test_configure_favorite_specific_sizes(self, mock_test_conn):
        """Test configuration with specific favorite sizes"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=['adjusted'],
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        plugin.configure(config, None, None)

        self.assertEqual(plugin.favorite_sizes, ['adjusted'])

    @patch('plugins.immich.immich.ImmichPlugin._test_immich_connection')
    def test_configure_favorite_all_sizes(self, mock_test_conn):
        """Test configuration with all favorite sizes"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=['original', 'adjusted', 'alternative', 'medium', 'thumb'],
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        plugin.configure(config, None, None)

        self.assertEqual(
            plugin.favorite_sizes,
            ['original', 'adjusted', 'alternative', 'medium', 'thumb']
        )

    @patch('plugins.immich.immich.ImmichPlugin._test_immich_connection')
    def test_configure_album_rules(self, mock_test_conn):
        """Test configuration with album rules"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=['[adjusted]:Favorites', '[original]:Originals'],
        )

        plugin.configure(config, None, None)

        self.assertEqual(len(plugin.album_rules), 2)
        self.assertEqual(plugin.album_rules[0].template, 'Favorites')
        self.assertEqual(plugin.album_rules[1].template, 'Originals')

    def test_configure_validation_missing_api_key(self):
        """Test configuration fails with missing API key"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key=None,
            immich_library_id='lib-123',
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        with self.assertRaises(SystemExit):
            plugin.configure(config, None, None)

    def test_configure_validation_missing_library_id(self):
        """Test configuration fails with missing library ID"""
        plugin = ImmichPlugin()
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id=None,
            immich_process_existing=False,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        with self.assertRaises(SystemExit):
            plugin.configure(config, None, None)


class TestImmichPluginDirectoryValidation(unittest.TestCase):
    """Test ImmichPlugin directory validation methods"""

    def test_strip_date_templates(self):
        """Test stripping date templates from paths"""
        plugin = ImmichPlugin()

        # Test various date template patterns
        self.assertEqual(
            plugin._strip_date_templates('/photos/%Y/%m'),
            '/photos'
        )
        self.assertEqual(
            plugin._strip_date_templates('/photos/{:%Y/%m}'),
            '/photos'
        )
        self.assertEqual(
            plugin._strip_date_templates('/photos/no-template'),
            '/photos/no-template'
        )

    def test_is_subdirectory_valid(self):
        """Test subdirectory check with valid paths"""
        plugin = ImmichPlugin()

        self.assertTrue(
            plugin._is_subdirectory('/photos/icloud', '/photos')
        )
        self.assertTrue(
            plugin._is_subdirectory('/photos/subdir/deep', '/photos')
        )

    def test_is_subdirectory_invalid(self):
        """Test subdirectory check with invalid paths"""
        plugin = ImmichPlugin()

        self.assertFalse(
            plugin._is_subdirectory('/other/path', '/photos')
        )
        self.assertFalse(
            plugin._is_subdirectory('/photo', '/photos')  # Not a subdirectory
        )


class TestImmichPluginHooks(unittest.TestCase):
    """Test ImmichPlugin hook methods"""

    def setUp(self):
        """Set up test plugin with basic config"""
        self.plugin = ImmichPlugin()
        # Set attributes directly without calling configure
        self.plugin.server_url = 'http://localhost:2283'
        self.plugin.api_key = 'test-key'
        self.plugin.library_id = 'lib-123'
        self.plugin.process_existing = False
        self.plugin.scan_timeout = 5.0
        self.plugin.poll_interval = 1.0

    def test_on_download_exists_without_process_existing(self):
        """Test on_download_exists hook without process_existing flag"""
        photo = Mock(spec=PhotoAsset)
        download_size = Mock()
        download_size.name = 'adjusted'

        self.plugin.on_download_exists(
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=download_size,
            photo=photo,
            dry_run=False
        )

        # Should not add to current_photo_files
        self.assertEqual(len(self.plugin.current_photo_files), 0)

    def test_on_download_exists_with_process_existing(self):
        """Test on_download_exists hook with process_existing flag"""
        self.plugin.process_existing = True
        photo = Mock(spec=PhotoAsset)
        download_size = Mock()
        download_size.name = 'adjusted'

        self.plugin.on_download_exists(
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=download_size,
            photo=photo,
            dry_run=False
        )

        # Should add to current_photo_files
        self.assertEqual(len(self.plugin.current_photo_files), 1)
        self.assertEqual(self.plugin.current_photo_files[0]['status'], 'existed')

    def test_on_download_exists_with_process_existing_favorites_favorite_photo(self):
        """Test on_download_exists with process_existing_favorites for favorite photo"""
        self.plugin.process_existing_favorites = True

        # Create mock photo that IS a favorite
        photo = Mock(spec=PhotoAsset)
        photo._asset_record = {
            "fields": {
                "isFavorite": {"value": 1}
            }
        }

        download_size = Mock()
        download_size.value = 'adjusted'

        self.plugin.on_download_exists(
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=download_size,
            photo=photo,
            dry_run=False
        )

        # Should add to current_photo_files because photo is favorite
        self.assertEqual(len(self.plugin.current_photo_files), 1)
        self.assertEqual(self.plugin.current_photo_files[0]['status'], 'existed')

    def test_on_download_exists_with_process_existing_favorites_non_favorite_photo(self):
        """Test on_download_exists with process_existing_favorites for non-favorite photo"""
        self.plugin.process_existing_favorites = True

        # Create mock photo that is NOT a favorite
        photo = Mock(spec=PhotoAsset)
        photo._asset_record = {
            "fields": {
                "isFavorite": {"value": 0}
            }
        }

        download_size = Mock()
        download_size.value = 'adjusted'

        self.plugin.on_download_exists(
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=download_size,
            photo=photo,
            dry_run=False
        )

        # Should NOT add to current_photo_files because photo is not favorite
        self.assertEqual(len(self.plugin.current_photo_files), 0)

    def test_on_download_downloaded(self):
        """Test on_download_downloaded hook"""
        photo = Mock(spec=PhotoAsset)
        download_size = Mock()
        download_size.name = 'adjusted'

        self.plugin.on_download_downloaded(
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=download_size,
            photo=photo,
            dry_run=False
        )

        # Should add to current_photo_files
        self.assertEqual(len(self.plugin.current_photo_files), 1)
        self.assertEqual(self.plugin.current_photo_files[0]['status'], 'downloaded')

    def test_on_download_complete(self):
        """Test on_download_complete hook (doesn't reset state per-file)"""
        # Add some data
        self.plugin.current_photo_files.append({'test': 'data'})

        photo = Mock(spec=PhotoAsset)
        download_size = Mock()
        download_size.name = 'adjusted'

        self.plugin.on_download_complete(
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=download_size,
            photo=photo,
            dry_run=False
        )

        # State persists (on_download_complete is called per-file, state resets in on_download_all_sizes_complete)
        self.assertEqual(len(self.plugin.current_photo_files), 1)

    def test_cleanup(self):
        """Test cleanup method (no-op)"""
        # Should not raise any exceptions and doesn't reset state
        self.plugin.current_photo_files.append({'test': 'data'})
        self.plugin.cleanup()
        # State should remain (cleanup is a no-op)
        self.assertEqual(len(self.plugin.current_photo_files), 1)


class TestImmichPluginProcessing(unittest.TestCase):
    """Test ImmichPlugin processing workflow"""

    def setUp(self):
        """Set up test plugin with basic config"""
        self.plugin = ImmichPlugin()
        # Set attributes directly without calling configure
        self.plugin.server_url = 'http://localhost:2283'
        self.plugin.api_key = 'test-key'
        self.plugin.library_id = 'lib-123'
        self.plugin.process_existing = True
        self.plugin.scan_timeout = 5.0
        self.plugin.poll_interval = 1.0
        self.plugin.stack_media = True
        self.plugin.stack_priority = ['adjusted', 'original']
        self.plugin.favorite_sizes = ['adjusted']
        self.plugin.album_rules = [AlbumRule('[adjusted]:Favorites')]

    def test_on_download_all_sizes_complete_no_files(self):
        """Test processing with no files"""
        mock_photo = Mock(spec=PhotoAsset)

        # No files in current_photo_files
        self.plugin.on_download_all_sizes_complete(photo=mock_photo, dry_run=False)

        # Should do nothing gracefully
        self.assertEqual(len(self.plugin.current_photo_files), 0)

    def test_on_download_all_sizes_complete_dry_run(self):
        """Test processing in dry run mode"""
        mock_photo = Mock(spec=PhotoAsset)

        self.plugin.current_photo_files = [
            {
                'path': '/photos/IMG_001.jpg',
                'size': 'adjusted',
                'status': 'downloaded',
                'is_live': False,
                'photo_filename': 'IMG_001.jpg',
            },
        ]

        self.plugin.on_download_all_sizes_complete(photo=mock_photo, dry_run=True)

        # Should not process in dry run mode
        self.assertEqual(len(self.plugin.current_immich_assets), 0)

    @patch('plugins.immich.immich.ImmichPlugin._wait_for_assets')
    @patch('plugins.immich.immich.ImmichPlugin._trigger_library_scan')
    @patch('plugins.immich.immich.ImmichPlugin._stack_size_variants')
    @patch('plugins.immich.immich.ImmichPlugin._mark_favorites')
    @patch('plugins.immich.immich.ImmichPlugin._apply_album_rules')
    def test_on_download_all_sizes_complete_success(
        self, mock_albums, mock_favs, mock_stack, mock_trigger, mock_wait
    ):
        """Test successful processing workflow"""
        mock_photo = Mock(spec=PhotoAsset)
        mock_photo.created = Mock()
        mock_photo._asset_record = {
            'fields': {
                'isFavorite': {'value': 1}
            }
        }

        self.plugin.current_photo_files = [
            {
                'path': '/photos/IMG_001.jpg',
                'size': 'adjusted',
                'status': 'downloaded',
                'is_live': False,
                'photo_filename': 'IMG_001.jpg',
            },
        ]

        self.plugin.on_download_all_sizes_complete(photo=mock_photo, dry_run=False)

        # Verify methods were called
        mock_trigger.assert_called_once()
        mock_wait.assert_called_once()
        mock_stack.assert_called_once()
        mock_favs.assert_called_once()
        mock_albums.assert_called_once_with(mock_photo)

    @patch('plugins.immich.immich.ImmichPlugin._search_asset_by_path')
    @patch('plugins.immich.immich.ImmichPlugin._trigger_library_scan')
    @patch('plugins.immich.immich.ImmichPlugin._wait_for_assets')
    @patch('plugins.immich.immich.ImmichPlugin._stack_size_variants')
    @patch('plugins.immich.immich.ImmichPlugin._mark_favorites')
    @patch('plugins.immich.immich.ImmichPlugin._apply_album_rules')
    def test_on_download_all_sizes_complete_existing_assets_found(
        self, mock_albums, mock_favs, mock_stack, mock_wait, mock_trigger, mock_search
    ):
        """Test optimization: skip scan when all existing files are already registered"""
        mock_photo = Mock(spec=PhotoAsset)
        mock_photo.created = Mock()
        mock_photo._asset_record = {
            'fields': {
                'isFavorite': {'value': 0}
            }
        }

        # All files have status 'existed'
        self.plugin.current_photo_files = [
            {
                'path': '/photos/IMG_001.jpg',
                'size': 'adjusted',
                'status': 'existed',
                'is_live': False,
                'photo_filename': 'IMG_001.jpg',
            },
            {
                'path': '/photos/IMG_001-medium.jpg',
                'size': 'medium',
                'status': 'existed',
                'is_live': False,
                'photo_filename': 'IMG_001.jpg',
            },
        ]

        # Mock that all assets are found
        mock_search.side_effect = [
            {'id': 'asset-1', 'originalPath': '/photos/IMG_001.jpg'},
            {'id': 'asset-2', 'originalPath': '/photos/IMG_001-medium.jpg'},
        ]

        self.plugin.on_download_all_sizes_complete(photo=mock_photo, dry_run=False)

        # Verify scan was NOT triggered (optimization worked)
        mock_trigger.assert_not_called()
        mock_wait.assert_not_called()

        # Verify search was called for each file
        self.assertEqual(mock_search.call_count, 2)

        # Verify other methods were still called
        mock_stack.assert_called_once()
        mock_favs.assert_not_called()  # Photo not favorite
        mock_albums.assert_called_once_with(mock_photo)

        # Verify accumulators were cleared at end
        self.assertEqual(len(self.plugin.current_immich_assets), 0)
        self.assertEqual(len(self.plugin.current_photo_files), 0)

    @patch('plugins.immich.immich.ImmichPlugin._search_asset_by_path')
    @patch('plugins.immich.immich.ImmichPlugin._trigger_library_scan')
    @patch('plugins.immich.immich.ImmichPlugin._wait_for_assets')
    @patch('plugins.immich.immich.ImmichPlugin._stack_size_variants')
    @patch('plugins.immich.immich.ImmichPlugin._mark_favorites')
    @patch('plugins.immich.immich.ImmichPlugin._apply_album_rules')
    def test_on_download_all_sizes_complete_existing_assets_missing(
        self, mock_albums, mock_favs, mock_stack, mock_wait, mock_trigger, mock_search
    ):
        """Test that scan is triggered when existing files are not all registered"""
        mock_photo = Mock(spec=PhotoAsset)
        mock_photo.created = Mock()
        mock_photo._asset_record = {
            'fields': {
                'isFavorite': {'value': 0}
            }
        }

        # All files have status 'existed'
        self.plugin.current_photo_files = [
            {
                'path': '/photos/IMG_001.jpg',
                'size': 'adjusted',
                'status': 'existed',
                'is_live': False,
                'photo_filename': 'IMG_001.jpg',
            },
            {
                'path': '/photos/IMG_001-medium.jpg',
                'size': 'medium',
                'status': 'existed',
                'is_live': False,
                'photo_filename': 'IMG_001.jpg',
            },
        ]

        # Mock that only one asset is found initially
        mock_search.side_effect = [
            {'id': 'asset-1', 'originalPath': '/photos/IMG_001.jpg'},
            None,  # Second asset not found
        ]

        # Mock wait_for_assets to return both assets
        mock_wait.return_value = {
            '/photos/IMG_001.jpg': {'id': 'asset-1', 'originalPath': '/photos/IMG_001.jpg'},
            '/photos/IMG_001-medium.jpg': {'id': 'asset-2', 'originalPath': '/photos/IMG_001-medium.jpg'},
        }

        self.plugin.on_download_all_sizes_complete(photo=mock_photo, dry_run=False)

        # Verify scan WAS triggered (some assets missing)
        mock_trigger.assert_called_once()
        mock_wait.assert_called_once()

        # Verify other methods were still called
        mock_stack.assert_called_once()
        mock_favs.assert_not_called()
        mock_albums.assert_called_once_with(mock_photo)


class TestImmichPluginStacking(unittest.TestCase):
    """Test ImmichPlugin media stacking functionality"""

    def setUp(self):
        """Set up test plugin"""
        self.plugin = ImmichPlugin()
        self.plugin.server_url = 'http://localhost:2283'
        self.plugin.api_key = 'test-key'
        self.plugin.stack_media = True
        self.plugin.stack_priority = ['adjusted', 'original']

    def test_stack_size_variants_no_sizes(self):
        """Test stacking with no eligible sizes"""
        self.plugin.current_immich_assets = []
        self.plugin._stack_size_variants()
        # Should do nothing (just logs debug)

    def test_stack_size_variants_single_size(self):
        """Test stacking with single size (no stacking needed)"""
        self.plugin.current_immich_assets = [
            {'asset_id': 'asset-001', 'size': 'adjusted'}
        ]
        self.plugin._stack_size_variants()
        # Should do nothing (just logs debug)

    @patch('plugins.immich.immich.ImmichPlugin._create_stack')
    def test_stack_size_variants_multiple_sizes(self, mock_create_stack):
        """Test stacking with multiple sizes"""
        self.plugin.current_immich_assets = [
            {'asset_id': 'asset-001', 'size': 'adjusted'},
            {'asset_id': 'asset-002', 'size': 'original'}
        ]

        self.plugin._stack_size_variants()

        # Should call _create_stack with ordered IDs
        mock_create_stack.assert_called_once()
        called_ids = mock_create_stack.call_args[0][0]
        # First should be adjusted (higher priority)
        self.assertEqual(called_ids[0], 'asset-001')


class TestImmichPluginFavorites(unittest.TestCase):
    """Test ImmichPlugin favorites functionality"""

    def setUp(self):
        """Set up test plugin"""
        self.plugin = ImmichPlugin()
        self.plugin.server_url = 'http://localhost:2283'
        self.plugin.api_key = 'test-key'
        self.plugin.favorite_sizes = ['adjusted']

    @patch('plugins.immich.immich.ImmichPlugin._set_favorite')
    def test_mark_favorites(self, mock_set_favorite):
        """Test marking assets as favorites"""
        self.plugin.current_immich_assets = [
            {'asset_id': 'asset-001', 'size': 'adjusted', 'is_favorite': False},
            {'asset_id': 'asset-002', 'size': 'original', 'is_favorite': False}
        ]

        self.plugin._mark_favorites()

        # Should call _set_favorite with only adjusted asset
        mock_set_favorite.assert_called_once_with(['asset-001'], True)

    def test_mark_favorites_no_matches(self):
        """Test marking favorites with no matching sizes"""
        self.plugin.current_immich_assets = [
            {'asset_id': 'asset-001', 'size': 'medium', 'is_favorite': False}
        ]

        # Should return early without calling any API
        self.plugin._mark_favorites()
        # No exception should be raised


class TestImmichPluginAlbums(unittest.TestCase):
    """Test ImmichPlugin album functionality"""

    def setUp(self):
        """Set up test plugin"""
        self.plugin = ImmichPlugin()
        self.plugin.server_url = 'http://localhost:2283'
        self.plugin.api_key = 'test-key'
        self.plugin.album_rules = [AlbumRule('[adjusted]:Favorites')]

    @patch('plugins.immich.immich.ImmichPlugin._add_assets_to_album')
    @patch('plugins.immich.immich.ImmichPlugin._get_or_create_album')
    def test_apply_album_rules(self, mock_get_album, mock_add_assets):
        """Test applying album rules"""
        mock_get_album.return_value = 'album-123'

        mock_photo = Mock(spec=PhotoAsset)
        mock_photo.created = Mock()

        self.plugin.current_immich_assets = [
            {'asset_id': 'asset-001', 'size': 'adjusted'},
            {'asset_id': 'asset-002', 'size': 'original'}
        ]

        self.plugin._apply_album_rules(mock_photo)

        # Should get/create album and add only adjusted asset
        mock_get_album.assert_called_once_with('Favorites')
        mock_add_assets.assert_called_once_with('album-123', ['asset-001'])


if __name__ == '__main__':
    unittest.main()
