"""Tests for plugin system"""

import unittest
from argparse import ArgumentParser, Namespace
from unittest.mock import MagicMock

from icloudpd.plugins.base import IcloudpdPlugin
from icloudpd.plugins.demo import DemoPlugin
from icloudpd.plugins.manager import PluginManager
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import AssetVersionSize


class MockPlugin(IcloudpdPlugin):
    """Mock plugin for testing"""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.configured = False
        self.cleaned_up = False
        self.mock_option = None
        self.configure_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock plugin for testing"

    def add_arguments(self, parser: ArgumentParser) -> None:
        group = parser.add_argument_group("Mock Plugin")
        group.add_argument("--mock-option", help="Mock option")

    def configure(self, config: Namespace, global_config=None, user_configs=None) -> None:
        self.configured = True
        self.configure_count += 1
        self.mock_option = getattr(config, "mock_option", None)

    def on_download_exists(
        self, download_path, photo_filename, download_size, photo, dry_run
    ) -> None:
        self.calls.append(("on_download_exists", download_path))

    def on_download_downloaded(
        self, download_path, photo_filename, download_size, photo, dry_run
    ) -> None:
        self.calls.append(("on_download_downloaded", download_path))

    def on_download_complete(
        self, download_path, photo_filename, download_size, photo, dry_run
    ) -> None:
        self.calls.append(("on_download_complete", download_path))

    def on_download_all_sizes_complete(self, photo, dry_run) -> None:
        self.calls.append(("on_download_all_sizes_complete", photo.filename))

    def on_run_completed(self, dry_run) -> None:
        self.calls.append(("on_run_completed", None))

    def cleanup(self) -> None:
        self.cleaned_up = True


class BrokenPlugin(IcloudpdPlugin):
    """Plugin that raises errors for testing error handling"""

    @property
    def name(self) -> str:
        return "broken"

    def on_download_complete(self, **kwargs) -> None:
        raise RuntimeError("Simulated plugin error")


class TestPluginManager(unittest.TestCase):
    """Test PluginManager functionality"""

    def test_init(self):
        """Test plugin manager initialization"""
        manager = PluginManager()
        self.assertEqual(manager.available, {})
        self.assertEqual(manager.enabled, {})

    def test_list_available(self):
        """Test listing available plugins"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin
        manager.available["broken"] = BrokenPlugin

        plugins = manager.list_available()
        self.assertIn("mock", plugins)
        self.assertIn("broken", plugins)
        # Should be sorted
        self.assertEqual(plugins, sorted(plugins))

    def test_get_plugin_info(self):
        """Test getting plugin information"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        info = manager.get_plugin_info("mock")
        self.assertEqual(info["name"], "mock")
        self.assertEqual(info["description"], "Mock plugin for testing")
        self.assertIn("version", info)

    def test_get_plugin_info_not_found(self):
        """Test getting info for unknown plugin raises KeyError"""
        manager = PluginManager()

        with self.assertRaises(KeyError):
            manager.get_plugin_info("nonexistent")

    def test_enable_plugin(self):
        """Test enabling a plugin with explicit config"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        config = Namespace(mock_option="test")
        manager.enable("mock", config)

        self.assertIn("mock", manager.enabled)
        self.assertIsInstance(manager.enabled["mock"], MockPlugin)
        self.assertTrue(manager.enabled["mock"].configured)
        self.assertEqual(manager.enabled["mock"].mock_option, "test")

    def test_enable_plugin_with_stored_config(self):
        """Test enabling a plugin using stored config"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        # Store config first
        config = Namespace(mock_option="from_stored")
        manager.set_plugin_config(config)

        # Enable without passing config explicitly
        manager.enable("mock")

        self.assertIn("mock", manager.enabled)
        self.assertIsInstance(manager.enabled["mock"], MockPlugin)
        self.assertTrue(manager.enabled["mock"].configured)
        self.assertEqual(manager.enabled["mock"].mock_option, "from_stored")

    def test_enable_plugin_without_config_raises(self):
        """Test enabling plugin without config raises ValueError"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        # Don't set config or pass it
        with self.assertRaises(ValueError) as ctx:
            manager.enable("mock")

        self.assertIn("No configuration available", str(ctx.exception))

    def test_enable_unknown_plugin(self):
        """Test enabling unknown plugin raises KeyError"""
        manager = PluginManager()

        with self.assertRaises(KeyError):
            manager.enable("nonexistent", Namespace())

    def test_disable_plugin(self):
        """Test disabling a plugin calls cleanup"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin
        manager.enable("mock", Namespace())

        plugin = manager.enabled["mock"]
        self.assertIn("mock", manager.enabled)

        manager.disable("mock")

        self.assertNotIn("mock", manager.enabled)
        self.assertTrue(plugin.cleaned_up)

    def test_is_enabled(self):
        """Test checking if plugin is enabled"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        self.assertFalse(manager.is_enabled("mock"))

        manager.enable("mock", Namespace())
        self.assertTrue(manager.is_enabled("mock"))

        manager.disable("mock")
        self.assertFalse(manager.is_enabled("mock"))

    def test_configure_called_once_with_runtime_configs(self):
        """Test that configure is only called once when runtime configs are provided later"""
        from unittest.mock import MagicMock

        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        # Step 1: Store config (like cli.py does)
        config = Namespace(mock_option="test")
        manager.set_plugin_config(config)

        # Step 2: Enable plugin (like cli.py does) - should call configure once
        manager.enable("mock")

        plugin = manager.enabled["mock"]
        self.assertEqual(plugin.configure_count, 1)

        # Step 3: Provide runtime configs (like base.py does) - should NOT call configure again
        mock_global_config = MagicMock()
        mock_user_configs = [MagicMock()]
        manager.set_plugin_config(config, mock_global_config, mock_user_configs)

        # Verify configure was still only called once
        self.assertEqual(plugin.configure_count, 1)

    def test_add_plugin_arguments(self):
        """Test adding plugin arguments to parser"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin

        parser = ArgumentParser()
        manager.add_plugin_arguments(parser, ["mock"])

        # Parse args with plugin option
        args = parser.parse_args(["--mock-option", "value"])
        self.assertEqual(args.mock_option, "value")

    def test_call_hook_single_plugin(self):
        """Test calling hooks on a single enabled plugin"""
        manager = PluginManager()
        manager.available["mock"] = MockPlugin
        manager.enable("mock", Namespace())

        # Create mock photo
        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"

        manager.call_hook(
            "on_download_complete",
            download_path="/path/to/file.jpg",
            photo_filename="test.jpg",
            download_size=AssetVersionSize.ORIGINAL,
            photo=mock_photo,
            dry_run=False,
        )

        plugin = manager.enabled["mock"]
        self.assertEqual(len(plugin.calls), 1)
        self.assertEqual(plugin.calls[0][0], "on_download_complete")
        self.assertEqual(plugin.calls[0][1], "/path/to/file.jpg")

    def test_call_hook_multiple_plugins(self):
        """Test hooks called on all enabled plugins"""
        manager = PluginManager()

        class MockPlugin1(MockPlugin):
            @property
            def name(self):
                return "mock1"

        class MockPlugin2(MockPlugin):
            @property
            def name(self):
                return "mock2"

        manager.available["mock1"] = MockPlugin1
        manager.available["mock2"] = MockPlugin2

        manager.enable("mock1", Namespace())
        manager.enable("mock2", Namespace())

        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"

        manager.call_hook(
            "on_download_all_sizes_complete", photo=mock_photo, dry_run=False
        )

        self.assertEqual(len(manager.enabled["mock1"].calls), 1)
        self.assertEqual(len(manager.enabled["mock2"].calls), 1)

    def test_call_hook_only_enabled_plugins(self):
        """Test hooks only called on enabled plugins"""
        manager = PluginManager()

        class MockPlugin2(MockPlugin):
            @property
            def name(self):
                return "mock2"

        manager.available["mock1"] = MockPlugin
        manager.available["mock2"] = MockPlugin2

        # Only enable mock1
        manager.enable("mock1", Namespace())

        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"

        manager.call_hook("on_download_all_sizes_complete", photo=mock_photo, dry_run=False)

        self.assertEqual(len(manager.enabled["mock1"].calls), 1)
        # mock2 not enabled
        self.assertNotIn("mock2", manager.enabled)

    def test_cleanup_all(self):
        """Test cleanup_all disables all plugins"""
        manager = PluginManager()

        class MockPlugin1(MockPlugin):
            @property
            def name(self):
                return "mock1"

        class MockPlugin2(MockPlugin):
            @property
            def name(self):
                return "mock2"

        manager.available["mock1"] = MockPlugin1
        manager.available["mock2"] = MockPlugin2

        manager.enable("mock1", Namespace())
        manager.enable("mock2", Namespace())

        plugin1 = manager.enabled["mock1"]
        plugin2 = manager.enabled["mock2"]

        manager.cleanup_all()

        self.assertEqual(len(manager.enabled), 0)
        self.assertTrue(plugin1.cleaned_up)
        self.assertTrue(plugin2.cleaned_up)


class TestDemoPlugin(unittest.TestCase):
    """Test the demo plugin"""

    def test_demo_plugin_initialization(self):
        """Test demo plugin can be created"""
        plugin = DemoPlugin()
        self.assertEqual(plugin.name, "demo")
        self.assertIn("demo", plugin.description.lower())
        self.assertEqual(plugin.version, "1.0.0")

    def test_demo_plugin_arguments(self):
        """Test demo plugin adds arguments"""
        plugin = DemoPlugin()
        parser = ArgumentParser()
        plugin.add_arguments(parser)

        # Test --demo-verbose
        args = parser.parse_args(["--demo-verbose"])
        self.assertTrue(args.demo_verbose)

        # Test --demo-compact
        args = parser.parse_args(["--demo-compact"])
        self.assertTrue(args.demo_compact)

    def test_demo_plugin_accumulation(self):
        """Test demo plugin accumulates files in on_download_complete"""
        plugin = DemoPlugin()
        plugin.configure(Namespace(demo_verbose=False, demo_compact=True))

        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"
        mock_photo.id = "ABC123"
        mock_photo._asset_record = {"fields": {}}

        # Simulate files being processed with on_download_complete
        # (This is what always runs, so it should accumulate)
        plugin.on_download_complete(
            download_path="/path/original.jpg",
            photo_filename="test.jpg",
            download_size=AssetVersionSize.ORIGINAL,
            photo=mock_photo,
            dry_run=False,
        )

        plugin.on_download_complete(
            download_path="/path/medium.jpg",
            photo_filename="test.jpg",
            download_size=AssetVersionSize.MEDIUM,
            photo=mock_photo,
            dry_run=False,
        )

        # Should have accumulated 2 files
        self.assertEqual(len(plugin.current_photo_files), 2)

        # Process all sizes complete
        plugin.on_download_all_sizes_complete(photo=mock_photo, dry_run=False)

        # Accumulator should be cleared
        self.assertEqual(len(plugin.current_photo_files), 0)
        self.assertEqual(plugin.total_photos, 1)

    def test_demo_plugin_counts_downloads_and_exists(self):
        """Test demo plugin tracks downloaded vs existing files"""
        plugin = DemoPlugin()
        plugin.configure(Namespace(demo_verbose=False, demo_compact=True))

        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"
        mock_photo._asset_record = {"fields": {}}

        # File exists
        plugin.on_download_exists(
            download_path="/path/original.jpg",
            photo_filename="test.jpg",
            download_size=AssetVersionSize.ORIGINAL,
            photo=mock_photo,
            dry_run=False,
        )

        # File downloaded
        plugin.on_download_downloaded(
            download_path="/path/medium.jpg",
            photo_filename="test.jpg",
            download_size=AssetVersionSize.MEDIUM,
            photo=mock_photo,
            dry_run=False,
        )

        self.assertEqual(plugin.total_files_existed, 1)
        self.assertEqual(plugin.total_files_downloaded, 1)


class TestImmichPluginIntegration(unittest.TestCase):
    """Integration tests for Immich plugin via PluginManager

    These tests verify that hooks are actually called when using the plugin manager,
    catching issues where the plugin works in isolation but not when integrated.
    """

    def test_immich_plugin_hook_calls_via_manager(self):
        """Test that plugin manager successfully calls Immich plugin hooks"""
        from plugins.immich.immich import ImmichPlugin

        manager = PluginManager()
        manager.available["immich"] = ImmichPlugin

        # Configure with minimal required settings
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

        # Enable the plugin (with mocked connection test)
        with unittest.mock.patch.object(ImmichPlugin, '_test_immich_connection'):
            manager.enable('immich', config)

        # Verify plugin was enabled
        self.assertTrue(manager.is_enabled('immich'))
        plugin = manager.enabled['immich']

        # Test that hooks are called via manager.call_hook()
        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"
        mock_photo.id = "ABC123"
        mock_photo._asset_record = {"fields": {"isFavorite": {"value": 0}}}
        mock_photo.created = MagicMock()

        # Call on_download_downloaded hook via manager
        manager.call_hook(
            'on_download_downloaded',
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=AssetVersionSize.ADJUSTED,
            photo=mock_photo,
            dry_run=False
        )

        # Verify the plugin accumulated the file
        self.assertEqual(len(plugin.current_photo_files), 1)
        self.assertEqual(plugin.current_photo_files[0]['status'], 'downloaded')
        self.assertEqual(plugin.current_photo_files[0]['size'], 'adjusted')

    def test_immich_plugin_hook_not_called_with_wrong_signature(self):
        """Test that hooks with mismatched signatures are not called

        This test verifies that if there's a signature mismatch between the
        base class and the plugin implementation, the hook won't be called.
        """
        from plugins.immich.immich import ImmichPlugin

        manager = PluginManager()
        manager.available["immich"] = ImmichPlugin

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

        with unittest.mock.patch.object(ImmichPlugin, '_test_immich_connection'):
            manager.enable('immich', config)

        plugin = manager.enabled['immich']

        # Try calling hook with wrong parameter names (should fail silently in call_hook)
        mock_photo = MagicMock(spec=PhotoAsset)

        # This should not raise but also should not accumulate anything
        # because the parameters don't match what the method expects
        manager.call_hook(
            'on_download_downloaded',
            wrong_param='/photos/IMG_001.jpg',
            another_wrong='IMG_001.jpg',
        )

        # Plugin should NOT have accumulated anything
        self.assertEqual(len(plugin.current_photo_files), 0)

    def test_immich_plugin_accumulation_via_manager(self):
        """Test full file accumulation workflow via plugin manager"""
        from plugins.immich.immich import ImmichPlugin

        manager = PluginManager()
        manager.available["immich"] = ImmichPlugin

        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=True,  # Enable processing existing files
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        with unittest.mock.patch.object(ImmichPlugin, '_test_immich_connection'):
            manager.enable('immich', config)

        plugin = manager.enabled['immich']

        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"
        mock_photo.id = "ABC123"
        mock_photo._asset_record = {"fields": {"isFavorite": {"value": 0}}}

        # Simulate download workflow: one exists, one downloaded
        manager.call_hook(
            'on_download_exists',
            download_path='/photos/original.jpg',
            photo_filename='test.jpg',
            download_size=AssetVersionSize.ORIGINAL,
            photo=mock_photo,
            dry_run=False
        )

        manager.call_hook(
            'on_download_downloaded',
            download_path='/photos/medium.jpg',
            photo_filename='test.jpg',
            download_size=AssetVersionSize.MEDIUM,
            photo=mock_photo,
            dry_run=False
        )

        # Should have accumulated 2 files
        self.assertEqual(len(plugin.current_photo_files), 2)
        self.assertEqual(plugin.current_photo_files[0]['status'], 'existed')
        self.assertEqual(plugin.current_photo_files[1]['status'], 'downloaded')

    def test_immich_plugin_discovered_and_callable(self):
        """Test that Immich plugin is discovered and hooks are callable

        This test mimics how icloudpd would actually use the plugin manager.
        """
        # Create manager and discover plugins
        manager = PluginManager()
        manager.discover()

        # Verify immich was discovered
        self.assertIn('immich', manager.list_available())

        # Configure plugin
        config = Namespace(
            immich_server_url='http://localhost:2283',
            immich_api_key='test-key',
            immich_library_id='lib-123',
            immich_process_existing=True,
            immich_scan_timeout=5.0,
            immich_poll_interval=1.0,
            immich_stack_media=False,
            immich_favorite=False,
            associate_live_with_extra_sizes=False,
            immich_albums=None,
        )

        # Store config and enable plugin (as icloudpd would do)
        manager.set_plugin_config(config)

        # Mock the connection test
        from plugins.immich.immich import ImmichPlugin
        with unittest.mock.patch.object(ImmichPlugin, '_test_immich_connection'):
            manager.enable('immich')

        # Verify plugin is enabled
        self.assertTrue(manager.is_enabled('immich'))

        # Call hooks as icloudpd would
        mock_photo = MagicMock(spec=PhotoAsset)
        mock_photo.filename = "test.jpg"
        mock_photo.id = "ABC123"
        mock_photo._asset_record = {"fields": {"isFavorite": {"value": 1}}}

        # Simulate the exact call pattern icloudpd uses
        manager.call_hook(
            'on_download_downloaded',
            download_path='/photos/IMG_001.jpg',
            photo_filename='IMG_001.jpg',
            download_size=AssetVersionSize.ADJUSTED,
            photo=mock_photo,
            dry_run=False
        )

        # Verify hook was called and plugin accumulated the file
        plugin = manager.enabled['immich']
        self.assertEqual(len(plugin.current_photo_files), 1,
                        "Plugin should have accumulated 1 file via hook call")
        self.assertEqual(plugin.current_photo_files[0]['size'], 'adjusted')


if __name__ == "__main__":
    unittest.main()
