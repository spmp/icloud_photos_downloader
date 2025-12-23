"""Base plugin class for icloudpd

All plugins should inherit from IcloudpdPlugin and implement the hooks they need.
"""

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from typing import TYPE_CHECKING

from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import VersionSize

if TYPE_CHECKING:
    from typing import Sequence

    from icloudpd.config import GlobalConfig, UserConfig


class IcloudpdPlugin(ABC):
    """Base class for icloudpd plugins.
    
    To create a plugin:
    1. Subclass IcloudpdPlugin
    2. Implement the name property (required)
    3. Implement hook methods you need (optional)
    4. Add CLI arguments if needed (optional)
    5. Register via entry point in pyproject.toml
    
    Example:
        >>> class MyPlugin(IcloudpdPlugin):
        ...     @property
        ...     def name(self) -> str:
        ...         return "myplugin"
        ...     
        ...     def on_download_all_sizes_complete(self, photo, **kwargs):
        ...         print(f"Photo complete: {photo.filename}")
        
        Then in pyproject.toml:
        [project.entry-points."icloudpd.plugins"]
        myplugin = "my_package.plugin:MyPlugin"
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name (e.g., 'immich', 'backup')
        
        This must match the entry point name in pyproject.toml.
        Used for --plugin NAME on the command line.
        
        Returns:
            Plugin name in lowercase, no spaces
        """
        ...
    
    @property
    def version(self) -> str:
        """Plugin version
        
        Returns:
            Version string (e.g., '1.0.0')
        """
        return "0.1.0"
    
    @property
    def description(self) -> str:
        """Short description shown in help text
        
        Returns:
            One-line description of what the plugin does
        """
        return ""
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add plugin-specific CLI arguments.
        
        Create an argument group for your plugin and add arguments to it.
        Arguments will be shown in --help when the plugin is enabled.
        
        Args:
            parser: ArgumentParser to add arguments to
            
        Example:
            >>> def add_arguments(self, parser):
            ...     group = parser.add_argument_group('My Plugin Options')
            ...     group.add_argument('--my-option', help='My option')
            ...     group.add_argument('--my-flag', action='store_true')
        """
        pass
    
    def configure(
        self,
        config: Namespace,
        global_config: "GlobalConfig | None" = None,
        user_configs: "Sequence[UserConfig] | None" = None,
    ) -> None:
        """Configure plugin from parsed CLI arguments.

        Called twice during initialization:
        1. Early: After CLI parsing, before configs are created (global_config and user_configs are None)
        2. Late: After configs are created in run_with_configs (global_config and user_configs are set)

        Use this to initialize your plugin with the provided configuration.

        Args:
            config: Parsed arguments namespace containing all CLI arguments
            global_config: Global configuration object (None during early call)
            user_configs: List of user configurations (None during early call)

        Example:
            >>> def configure(self, config, global_config=None, user_configs=None):
            ...     self.api_key = config.my_api_key
            ...     self.client = MyClient(self.api_key)
            ...     # Use configs if available for validation
            ...     if user_configs:
            ...         directories = [uc.directory for uc in user_configs]
            ...         self.validate_directories(directories)
        """
        pass
    
    # ========================================================================
    # HOOK METHODS - All optional, implement what you need
    # ========================================================================
    
    # Per-size hooks (called for each size variant)
    
    def on_download_exists(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called when a file already exists (per size variant)"""
        pass
    
    def on_download_downloaded(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called after a file is downloaded (per size variant)"""
        pass
    
    def on_download_complete(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called after a size is processed - ALWAYS runs (per size variant)"""
        pass
    
    # Live photo hooks
    
    def on_download_exists_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called when live photo video already exists"""
        pass
    
    def on_download_downloaded_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called after live photo video is downloaded"""
        pass
    
    def on_download_complete_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called after live photo is processed - ALWAYS runs"""
        pass
    
    # Per-photo hook (KEY HOOK - called once per photo)
    
    def on_download_all_sizes_complete(
        self,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Called after ALL sizes of a photo are complete.
        
        This is the most important hook for most plugins.
        Use this to process the complete photo with all its size variants.
        """
        pass
    
    # Per-run hook (called once at end)
    
    def on_run_completed(
        self,
        dry_run: bool,
    ) -> None:
        """Called after entire download run is complete"""
        pass
    
    def cleanup(self) -> None:
        """Called on shutdown, even if there was an error.
        
        Override this to clean up resources, close connections, etc.
        Will be called even if downloads failed or were interrupted.
        """
        pass
