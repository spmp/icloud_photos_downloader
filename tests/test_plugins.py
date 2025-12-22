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

    @property
    def name(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock plugin for testing"

    def add_arguments(self, parser: ArgumentParser) -> None:
        group = parser.add_argument_group("Mock Plugin")
        group.add_argument("--mock-option", help="Mock option")

    def configure(self, config: Namespace) -> None:
        self.configured = True
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


if __name__ == "__main__":
    unittest.main()
