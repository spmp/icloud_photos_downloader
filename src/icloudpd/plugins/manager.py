"""Plugin manager for discovery, loading, and hook dispatching

The PluginManager handles:
- Discovering plugins via Python entry points
- Loading and enabling plugins
- Dispatching hook calls to all enabled plugins
- Plugin lifecycle (configure, cleanup)
"""

import logging
from importlib.metadata import entry_points
from typing import Any, Dict, List
from argparse import ArgumentParser, Namespace

from icloudpd.plugins.base import IcloudpdPlugin

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages plugin discovery, loading, and hook dispatching.
    
    Usage:
        >>> manager = PluginManager()
        >>> manager.discover()  # Find all installed plugins
        >>> print(manager.list_available())  # ['demo', 'immich', ...]
        >>> manager.enable('demo', config)  # Enable a plugin
        >>> manager.call_hook('on_photo_downloaded', ...)  # Call hooks
    """
    
    def __init__(self):
        """Initialize the plugin manager."""
        self.available: Dict[str, type] = {}  # name -> plugin class
        self.enabled: Dict[str, IcloudpdPlugin] = {}  # name -> plugin instance
    
    def discover(self) -> None:
        """Discover all installed plugins via entry points.
        
        Looks for plugins registered under the 'icloudpd.plugins' entry point group.
        Plugins are registered in pyproject.toml like:
        
            [project.entry-points."icloudpd.plugins"]
            demo = "icloudpd.plugins.demo:DemoPlugin"
            
        This allows plugins to be automatically discovered when installed.
        """
        try:
            discovered_eps = entry_points(group='icloudpd.plugins')
        except Exception as e:
            logger.warning(f"Failed to discover plugins: {e}")
            return
        
        for ep in discovered_eps:
            try:
                plugin_class = ep.load()
                self.available[ep.name] = plugin_class
                logger.debug(f"Discovered plugin: {ep.name} ({plugin_class})")
            except Exception as e:
                logger.warning(f"Failed to load plugin {ep.name}: {e}")
    
    def list_available(self) -> List[str]:
        """Get list of available plugin names.
        
        Returns:
            List of plugin names that have been discovered
        """
        return sorted(self.available.keys())
    
    def get_plugin_info(self, name: str) -> Dict[str, str]:
        """Get information about a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            Dictionary with 'name', 'version', 'description'
            
        Raises:
            KeyError: If plugin not found
        """
        if name not in self.available:
            raise KeyError(f"Plugin '{name}' not found")
        
        plugin_class = self.available[name]
        temp_instance = plugin_class()
        
        return {
            'name': temp_instance.name,
            'version': temp_instance.version,
            'description': temp_instance.description,
        }
    
    def enable(self, name: str, config: Namespace) -> None:
        """Enable and configure a plugin.
        
        Creates an instance of the plugin and calls its configure() method.
        
        Args:
            name: Plugin name to enable
            config: Parsed CLI arguments
            
        Raises:
            KeyError: If plugin name not found in available plugins
        """
        if name not in self.available:
            available = ', '.join(self.list_available())
            raise KeyError(
                f"Plugin '{name}' not found. "
                f"Available plugins: {available if available else 'none'}"
            )
        
        try:
            plugin_class = self.available[name]
            plugin = plugin_class()
            
            # Configure the plugin with CLI args
            plugin.configure(config)
            
            self.enabled[name] = plugin
            logger.info(f"Enabled plugin: {name} (v{plugin.version})")
            
        except Exception as e:
            logger.error(f"Failed to enable plugin {name}: {e}", exc_info=True)
            raise
    
    def disable(self, name: str) -> None:
        """Disable a plugin and call its cleanup method.
        
        Args:
            name: Plugin name to disable
        """
        if name in self.enabled:
            try:
                self.enabled[name].cleanup()
                logger.debug(f"Called cleanup for plugin: {name}")
            except Exception as e:
                logger.warning(f"Error during {name} plugin cleanup: {e}")
            
            del self.enabled[name]
            logger.info(f"Disabled plugin: {name}")
    
    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is currently enabled.
        
        Args:
            name: Plugin name
            
        Returns:
            True if plugin is enabled
        """
        return name in self.enabled
    
    def add_plugin_arguments(
        self,
        parser: ArgumentParser,
        plugin_names: List[str]
    ) -> None:
        """Add CLI arguments for specified plugins.
        
        Calls add_arguments() on each plugin to let them register
        their CLI options.
        
        Args:
            parser: ArgumentParser to add arguments to
            plugin_names: List of plugin names to add arguments for
        """
        for name in plugin_names:
            if name in self.available:
                try:
                    plugin_class = self.available[name]
                    temp_instance = plugin_class()
                    temp_instance.add_arguments(parser)
                    logger.debug(f"Added arguments for plugin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to add arguments for plugin {name}: {e}")
    
    def call_hook(self, hook_name: str, **kwargs) -> None:
        """Call a hook on all enabled plugins.
        
        Calls the specified hook method on each enabled plugin.
        If a plugin's hook raises an exception, it's logged but
        doesn't stop other plugins from running.
        
        Args:
            hook_name: Name of the hook method to call
            **kwargs: Arguments to pass to the hook
            
        Example:
            >>> manager.call_hook('on_photo_downloaded',
            ...                  photo_id='ABC123',
            ...                  photo_filename='IMG_1234.jpg',
            ...                  downloaded_files=[...],
            ...                  is_favorite=True,
            ...                  metadata={...})
        """
        for plugin_name, plugin in self.enabled.items():
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                try:
                    method(**kwargs)
                except Exception as e:
                    logger.error(
                        f"Plugin '{plugin_name}' hook '{hook_name}' failed: {e}",
                        exc_info=True
                    )
    
    def cleanup_all(self) -> None:
        """Cleanup all enabled plugins.
        
        Calls cleanup() on all enabled plugins and disables them.
        Safe to call multiple times.
        """
        # Create a list to avoid modifying dict during iteration
        plugin_names = list(self.enabled.keys())
        
        for name in plugin_names:
            self.disable(name)
        
        logger.debug("All plugins cleaned up")
