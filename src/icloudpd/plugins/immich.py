"""Immich plugin for stacking, favoriting, and adding photos to albums

This plugin integrates with Immich to:
1. Register photos in Immich external library via scan-and-wait
2. Stack multiple size variants together (original, medium, adjusted)
3. Associate live photo videos with multiple size variants
4. Mark specific sizes as favorites based on iCloud favorite status
5. Add specific sizes to albums with flexible size-based rules

NOTES on Immich API Behavior
-----------------------------
Stacking:
- Stacks are visual groupings only, not returnable asset IDs
- Stacked images appear grouped in timeline/favorites but NOT in albums
- Individual assets from a stack can be favorited/added to albums independently

Favoriting:
- Can favorite individual assets OR multiple assets in a stack
- Favorited assets in a stack appear stacked in favorites view
- Deleting a stack leaves favorited assets in favorites

Albums:
- Stacks cannot be added to albums (no API support)
- Individual assets must be added to albums
- Adding all assets from a stack to an album doesn't show them as stacked

Live Photos:
- Immich auto-associates the MOV with original HEIC (MOV becomes hidden)
- We can associate the same livePhotoVideoId with other sizes (adjusted, medium, etc.)
- This allows live photo playback for all size variants
"""

import argparse
import logging
import re
import sys
import time
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

import requests

from icloudpd.plugins.base import IcloudpdPlugin
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import VersionSize

if TYPE_CHECKING:
    from typing import Sequence

    from icloudpd.config import GlobalConfig, UserConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================

def _parse_sizes(value: str | None) -> List[str]:
    """Parse comma-separated size list and validate against available sizes.

    Args:
        value: Comma-separated size list or None (means all sizes)

    Returns:
        List of valid size names

    Raises:
        argparse.ArgumentTypeError: If invalid sizes specified
    """
    available = ['original', 'adjusted', 'alternative', 'medium', 'thumb']

    # No value given (--flag with no argument) → return all
    if value is None:
        return available

    # Parse comma-separated values
    items = [s.strip() for s in value.split(',')]

    # Validate against available
    invalid = [s for s in items if s not in available]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Invalid sizes: {invalid}. Available: {available}"
        )

    return items


# ============================================================================
# Album Rule Class
# ============================================================================

class AlbumRule:
    """Represents a single album assignment rule.

    Format: [size1,size2]:album_template or just album_template

    Examples:
        [adjusted]:iCloud Photos/{:%Y/%m}  - Only adjusted size
        [original]:iCloud Raw              - Only original size
        [adjusted,medium]:Processed        - Adjusted and medium sizes
        All Photos                         - All sizes (no filter)

    Note: [stacked] is no longer supported since stacks cannot be added to albums
    """

    def __init__(self, rule_string: str):
        """Parse album rule string.

        Args:
            rule_string: Format "[sizes]:template" or just "template" (no filter)

        Raises:
            ValueError: If rule format is invalid or contains [stacked]
        """
        # Try to match [sizes]:template format
        match = re.match(r'^\[([^\]]+)\]:(.+)$', rule_string.strip())

        if match:
            # Has size filter
            sizes_str, self.template = match.groups()

            # Parse size targets
            self.size_targets = [s.strip() for s in sizes_str.split(',')]

            # Validate: [stacked] is no longer allowed
            if 'stacked' in self.size_targets:
                raise ValueError(
                    "Album rule '[stacked]:...' is not supported. "
                    "Stacks cannot be added to albums in Immich. "
                    "Use specific sizes like [adjusted]:... or [original]:... instead."
                )

            # Validate all sizes are known
            valid_sizes = ['original', 'adjusted', 'alternative', 'medium', 'thumb']
            invalid = [s for s in self.size_targets if s not in valid_sizes]
            if invalid:
                raise ValueError(
                    f"Invalid sizes in album rule: {invalid}. "
                    f"Valid sizes: {valid_sizes}"
                )

            self.match_all = False
        else:
            # No filter - match everything
            self.template = rule_string.strip()
            if not self.template:
                raise ValueError(f"Empty album template: {rule_string}")

            self.size_targets = []
            self.match_all = True

    def matches(self, size: str) -> bool:
        """Check if this rule matches the given size.

        Args:
            size: The size name (e.g., 'original', 'adjusted')

        Returns:
            True if this rule should be applied to this size
        """
        # Match-all rule: matches everything
        if self.match_all:
            return True

        # Check if size is in target list
        return size in self.size_targets

    def __repr__(self) -> str:
        if self.match_all:
            return f"AlbumRule(all:{self.template})"
        return f"AlbumRule([{','.join(self.size_targets)}]:{self.template})"


# ============================================================================
# Immich Plugin
# ============================================================================

class ImmichPlugin(IcloudpdPlugin):
    """Immich integration plugin for photo management.

    Registers photos in Immich external library with optional stacking,
    favoriting, and flexible album management based on size variants.

    Example:
        $ icloudpd --plugin immich --immich-server-url https://immich.example.com \\
                   --immich-api-key YOUR_API_KEY --immich-library-id abc123 \\
                   --immich-album "[adjusted]:iCloud/{:%Y/%B}" \\
                   --immich-album "[original]:Raw"

        $ icloudpd --plugin immich --immich-server-url https://immich.example.com \\
                   --immich-api-key YOUR_API_KEY --immich-library-id abc123 \\
                   --immich-stack-media adjusted,original \\
                   --immich-favorite adjusted \\
                   --immich-album "[adjusted]:Favorites"
    """

    def __init__(self):
        """Initialize Immich plugin with configuration and accumulators"""
        # Configuration options
        self.server_url: str | None = None
        self.api_key: str | None = None
        self.library_id: str | None = None
        self.process_existing: bool = False
        self.scan_timeout: float = 5.0

        # Stacking configuration
        self.stack_media: bool = False
        self.stack_priority: List[str] = ['adjusted', 'medium', 'original']

        # Favoriting configuration - now a list of sizes to favorite
        self.favorite_sizes: List[str] = []

        # Live photo association configuration
        self.associate_live_sizes: List[str] = []

        # Album rules
        self.album_rules: List[AlbumRule] = []

        # Accumulators for current photo being processed
        # Each entry: {'status': 'downloaded'|'existed', 'path': str, 'size': str, 'is_live': bool, 'photo_filename': str}
        self.current_photo_files: List[Dict[str, Any]] = []

        # Will be populated with Immich asset IDs after registration
        # Each entry: {'size': str, 'asset_id': str, 'path': str, 'is_live': bool, 'live_photo_video_id': Optional[str]}
        self.current_immich_assets: List[Dict[str, Any]] = []

        # Track which asset has the original live photo video (for association with other sizes)
        self.live_photo_filename: str | None = None

        # Global counters for the run
        self.total_photos = 0
        self.total_registered = 0
        self.total_stacked = 0
        self.total_favorited = 0
        self.total_added_to_albums = 0
        self.total_live_associated = 0

    @property
    def name(self) -> str:
        """Plugin name"""
        return "immich"

    @property
    def version(self) -> str:
        """Plugin version"""
        return "2.0.0"

    @property
    def description(self) -> str:
        """Plugin description"""
        return "Register and organize photos in Immich with stacking, favorites, and album support"

    # ========================================================================
    # CLI Argument Configuration
    # ========================================================================

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add Immich plugin CLI arguments"""
        group = parser.add_argument_group('Immich Plugin Options')

        group.add_argument(
            '--immich-server-url',
            metavar='URL',
            help='Immich server URL (e.g., https://immich.example.com)'
        )

        group.add_argument(
            '--immich-api-key',
            metavar='KEY',
            help='Immich API key for authentication'
        )

        group.add_argument(
            '--immich-library-id',
            metavar='ID',
            help='Immich external library ID (required for scanning)'
        )

        group.add_argument(
            '--immich-process-existing',
            action='store_true',
            help='Process files that already existed (in addition to newly downloaded files)'
        )

        group.add_argument(
            '--immich-stack-media',
            nargs='?',
            const=None,
            default=False,
            type=_parse_sizes,
            metavar='SIZE(Primary),SIZE,...',
            help='Stack size variants. No argument stacks all sizes. '
                 'With argument: comma-separated priority list (first=primary)'
        )

        group.add_argument(
            '--immich-favorite',
            nargs='?',
            const=None,
            default=False,
            type=_parse_sizes,
            metavar='SIZE,SIZE,...',
            help='Mark sizes as favorite in Immich based on iCloud favorite status. '
                 'No argument favorites all sizes. With argument: comma-separated list of sizes'
        )

        group.add_argument(
            '--associate-live-with-extra-sizes',
            nargs='?',
            const=None,
            default=False,
            type=_parse_sizes,
            metavar='SIZE,SIZE,...',
            help='Associate live photo MOV with other sizes. '
                 'No argument associates with all sizes. With argument: comma-separated list of sizes'
        )

        group.add_argument(
            '--immich-album',
            action='append',
            dest='immich_albums',
            metavar='RULE',
            help='Album rule in format [sizes]:template or just template (all sizes). '
                 'Can be used multiple times. '
                 'Examples: --immich-album "[adjusted]:iCloud/{:%%Y/%%m}" '
                 '--immich-album "[original]:Raw" --immich-album "All Photos"'
        )

        group.add_argument(
            '--immich-scan-timeout',
            type=float,
            default=5.0,
            metavar='SECONDS',
            help='Time to wait for Immich library scan to complete after adding photos '
                 '(default: 5.0, 0 for infinite)'
        )

    # ========================================================================
    # Plugin Configuration
    # ========================================================================

    def configure(
        self,
        config: Namespace,
        global_config: "GlobalConfig | None" = None,
        user_configs: "Sequence[UserConfig] | None" = None,
    ) -> None:
        """Configure Immich plugin from CLI arguments and runtime configs.

        This is called twice:
        1. Early (from cli.py): Only config is available
        2. Late (from base.py): All parameters are available

        Args:
            config: Parsed CLI arguments namespace
            global_config: Global configuration (None on first call)
            user_configs: List of user configurations (None on first call)
        """
        # Basic configuration
        self.server_url = getattr(config, 'immich_server_url', None)
        self.api_key = getattr(config, 'immich_api_key', None)
        self.library_id = getattr(config, 'immich_library_id', None)
        self.process_existing = getattr(config, 'immich_process_existing', False)
        self.scan_timeout = getattr(config, 'immich_scan_timeout', 5.0)

        # Parse stack_media argument (False, None=all, or list of sizes)
        stack_arg = getattr(config, 'immich_stack_media', False)
        if stack_arg is not False:
            self.stack_media = True
            if stack_arg is not None and isinstance(stack_arg, list):
                # User provided custom priority list (first=primary)
                self.stack_priority = stack_arg

        # Parse favorite argument (False, None=all, or list of sizes)
        favorite_arg = getattr(config, 'immich_favorite', False)
        if favorite_arg is not False:
            if favorite_arg is None:
                # Favorite all sizes
                self.favorite_sizes = ['original', 'adjusted', 'alternative', 'medium', 'thumb']
            elif isinstance(favorite_arg, list):
                # Favorite specific sizes
                self.favorite_sizes = favorite_arg

        # Parse associate-live argument (False, None=all, or list of sizes)
        associate_arg = getattr(config, 'associate_live_with_extra_sizes', False)
        if associate_arg is not False:
            if associate_arg is None:
                # Associate with all sizes
                self.associate_live_sizes = ['original', 'adjusted', 'alternative', 'medium', 'thumb']
            elif isinstance(associate_arg, list):
                # Associate with specific sizes
                self.associate_live_sizes = associate_arg

        # Parse album rules
        album_rules_raw = getattr(config, 'immich_albums', None) or []
        for rule_str in album_rules_raw:
            try:
                rule = AlbumRule(rule_str)
                self.album_rules.append(rule)
            except ValueError as e:
                print(f"Error: Invalid album rule '{rule_str}': {e}", file=sys.stderr)
                sys.exit(1)

        # Validation
        if self.server_url and not self.api_key:
            print("Error: Immich server URL provided but no API key", file=sys.stderr)
            sys.exit(1)
        if self.api_key and not self.server_url:
            print("Error: Immich API key provided but no server URL", file=sys.stderr)
            sys.exit(1)
        if not self.library_id:
            print("Error: Immich library ID is required (--immich-library-id)", file=sys.stderr)
            sys.exit(1)

        # Print configuration (using print since logger isn't configured yet)
        print("\n" + "=" * 70)
        print("Immich Plugin: Initialized")
        print("=" * 70)
        print(f"  Version:           {self.version}")
        print(f"  Server URL:        {self.server_url}")
        print(f"  Library ID:        {self.library_id}")
        print(f"  Process Existing:  {self.process_existing}")
        print(f"  Scan Timeout:      {self.scan_timeout}s")
        print(f"  Stack Media:       {self.stack_media}")
        if self.stack_media:
            print(f"  Stack Priority:    {', '.join(self.stack_priority)}")
        print(f"  Favorite Sizes:    {', '.join(self.favorite_sizes) if self.favorite_sizes else 'None'}")
        print(f"  Live Association:  {', '.join(self.associate_live_sizes) if self.associate_live_sizes else 'None'}")
        print(f"  Album Rules:       {len(self.album_rules)}")
        for rule in self.album_rules:
            print(f"    - {rule}")
        print("=" * 70 + "\n")

        # Test Immich connection (after showing config so user knows what's being tested)
        if self.server_url and self.api_key:
            self._test_immich_connection()

            # Validate directories when user_configs are available (second call from base.py)
            if user_configs is not None:
                self._validate_directories(user_configs)


    @staticmethod
    def _strip_date_templates(path: str) -> str:
        """Strip date templates from a directory path.

        Converts paths like '/a/b/c/%Y/%m' to '/a/b/c'

        Args:
            path: Directory path potentially containing date templates

        Returns:
            Base path with date templates removed
        """
        # Remove path components that contain % (date templates)
        parts = path.split('/')
        # Keep only parts that don't contain %
        base_parts = [p for p in parts if '%' not in p]
        # Rejoin, ensuring we preserve leading /
        result = '/'.join(base_parts)
        # Normalize path (remove duplicate slashes, etc.)
        from pathlib import Path
        return str(Path(result))

    @staticmethod
    def _is_subdirectory(child: str, parent: str) -> bool:
        """Check if child path is within parent directory.

        Args:
            child: Potential subdirectory path
            parent: Parent directory path

        Returns:
            True if child is within parent directory
        """
        from pathlib import Path
        try:
            child_path = Path(child).resolve()
            parent_path = Path(parent).resolve()
            # Check if child is relative to parent (will raise ValueError if not)
            child_path.relative_to(parent_path)
            return True
        except (ValueError, RuntimeError):
            return False

    def _validate_directories(self, user_configs: "Sequence[UserConfig]") -> None:
        """Validate that all icloudpd directories are within Immich library importPaths.

        Args:
            user_configs: List of user configurations containing directory settings

        Raises:
            SystemExit: If any directory is not within library importPaths
        """
        assert self.server_url is not None
        assert self.api_key is not None
        assert self.library_id is not None

        try:
            # Fetch library data to get importPaths
            url = f"{self.server_url}/api/libraries/{self.library_id}"
            headers = {"x-api-key": self.api_key}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            library_data = response.json()
            import_paths = library_data.get('importPaths', [])

            if not import_paths:
                print("Warning: Immich library has no importPaths configured", file=sys.stderr)
                print("Please configure importPaths in your Immich library settings", file=sys.stderr)
                sys.exit(1)

            # Collect all directories from user configs
            user_directories = []
            for user_config in user_configs:
                directory = user_config.directory
                # Strip date templates from the directory path
                base_directory = self._strip_date_templates(directory)
                user_directories.append((directory, base_directory))

            # Validate each directory is within at least one importPath
            invalid_dirs = []
            for original_dir, base_dir in user_directories:
                is_valid = False
                for import_path in import_paths:
                    if self._is_subdirectory(base_dir, import_path):
                        is_valid = True
                        break

                if not is_valid:
                    invalid_dirs.append(original_dir)

            # If any directories are invalid, exit with error
            if invalid_dirs:
                print("Error: The following icloudpd directories are not within Immich library importPaths:", file=sys.stderr)
                for invalid_dir in invalid_dirs:
                    print(f"  - {invalid_dir}", file=sys.stderr)
                print("\nImmich library importPaths:", file=sys.stderr)
                for import_path in import_paths:
                    print(f"  - {import_path}", file=sys.stderr)
                print("\nAll icloudpd directories must be subdirectories of at least one Immich importPath.", file=sys.stderr)
                sys.exit(1)

            # Success - print confirmation
            print(f"  Directory validation: OK ({len(user_directories)} directories validated)")

        except requests.RequestException as e:
            print(f"Error: Failed to fetch library data for directory validation: {e}", file=sys.stderr)
            sys.exit(1)

    def _test_immich_connection(self) -> None:
        """Test connection to Immich server and validate library ID.

        Raises:
            SystemExit: If connection fails or library ID is invalid
        """
        # Validate required values (should be guaranteed by configure() validation)
        assert self.server_url is not None
        assert self.api_key is not None
        assert self.library_id is not None

        try:
            # Test general connection with /api/server-info
            url = f"{self.server_url}/api/server-info"
            headers = {"x-api-key": self.api_key}

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Validate library ID exists
            url = f"{self.server_url}/api/libraries/{self.library_id}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            library_data = response.json()
            library_name = library_data.get('name', 'Unknown')
            print(f"  Connected to Immich library: {library_name}")

        except requests.RequestException as e:
            print(f"Error: Failed to connect to Immich: {e}", file=sys.stderr)
            print("Please check --immich-server-url, --immich-api-key, and --immich-library-id", file=sys.stderr)
            sys.exit(1)

    # ========================================================================
    # Per-Size Hooks - Accumulate Data
    # ========================================================================

    def on_download_exists(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """File already exists - add to accumulator if process_existing is enabled"""
        if self.process_existing:
            logger.debug(f"Immich: Accumulating existing file {download_size.value} - {download_path}")
            self.current_photo_files.append({
                'status': 'existed',
                'path': download_path,
                'size': download_size.value,
                'is_live': False,
                'photo_filename': photo_filename,
            })
        else:
            logger.debug("Immich: Skipping existing file (process_existing=False)")

    def on_download_downloaded(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """File was downloaded - always add to accumulator"""
        logger.debug(f"Immich: Accumulating downloaded file {download_size.value} - {download_path}")
        self.current_photo_files.append({
            'status': 'downloaded',
            'path': download_path,
            'size': download_size.value,
            'is_live': False,
            'photo_filename': photo_filename,
        })

    def on_download_complete(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Size processing complete - hook available but not needed"""
        pass

    # ========================================================================
    # Live Photo Hooks - Track Live Photo Filename
    # ========================================================================

    def on_download_exists_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Live photo exists - track filename for later association"""
        if self.process_existing:
            logger.debug(f"Immich: Accumulating existing live photo {download_size.value} - {download_path}")
            self.current_photo_files.append({
                'status': 'existed',
                'path': download_path,
                'size': download_size.value,
                'is_live': True,
                'photo_filename': photo_filename,
            })
            # Track that this photo has a live component
            self.live_photo_filename = photo_filename

    def on_download_downloaded_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Live photo downloaded - track filename for later association"""
        logger.debug(f"Immich: Accumulating downloaded live photo {download_size.value} - {download_path}")
        self.current_photo_files.append({
            'status': 'downloaded',
            'path': download_path,
            'size': download_size.value,
            'is_live': True,
            'photo_filename': photo_filename,
        })
        # Track that this photo has a live component
        self.live_photo_filename = photo_filename

    def on_download_complete_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Live photo processing complete - hook available but not needed"""
        pass

    # ========================================================================
    # Immich API Functions
    # ========================================================================

    def _trigger_library_scan(self, library_id: str) -> None:
        """Trigger a library scan in Immich.

        Args:
            library_id: The Immich library ID to scan

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/libraries/{library_id}/scan"
        headers = {"x-api-key": self.api_key}
        body = {"refreshAllFiles": False}

        logger.debug(f"POST {url}")
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        logger.debug(f"Library scan triggered: {response.status_code}")

    def _search_assets_by_originalpath(self, path_prefix: str) -> List[Dict[str, Any]]:
        """Search for assets by originalPath prefix.

        Args:
            path_prefix: The path prefix to search for (without extension or size suffix)

        Returns:
            List of asset dictionaries from Immich API

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/search/metadata"
        headers = {"x-api-key": self.api_key}
        body = {"originalPath": f"{path_prefix}*"}

        logger.debug(f"POST {url} (searching for: {path_prefix}*)")
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Extract assets from response: {"assets": {"items": [...]}}
        assets = data.get("assets", {}).get("items", [])
        logger.debug(f"Found {len(assets)} assets matching prefix")
        return assets

    def _create_stack(self, asset_ids: List[str], primary_id: str) -> None:
        """Create a stack in Immich with specified assets.

        Args:
            asset_ids: List of asset IDs to stack together
            primary_id: Asset ID to use as stack primary

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/assets/stack"
        headers = {"x-api-key": self.api_key}
        body = {
            "assetIds": asset_ids
        }

        logger.debug(f"PUT {url}")
        logger.debug(f"  Stacking {len(asset_ids)} assets, primary: {primary_id}")
        response = requests.put(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        logger.debug("Stack created successfully")

    def _set_favorite(self, asset_ids: List[str], is_favorite: bool) -> None:
        """Set favorite status for multiple assets.

        Args:
            asset_ids: List of asset IDs
            is_favorite: Whether to mark as favorite

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/assets"
        headers = {"x-api-key": self.api_key}
        body = {
            "ids": asset_ids,
            "isFavorite": is_favorite
        }

        logger.debug(f"PUT {url}")
        logger.debug(f"  Setting favorite={is_favorite} for {len(asset_ids)} assets")
        response = requests.put(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        logger.debug("Favorites updated successfully")

    def _get_or_create_album(self, album_name: str) -> str:
        """Get existing album or create new one.

        Args:
            album_name: Name of the album

        Returns:
            Album ID

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/albums"
        headers = {"x-api-key": self.api_key}

        # Get all albums
        logger.debug(f"GET {url} (searching for album: {album_name})")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        albums = response.json()

        # Search for existing album
        for album in albums:
            if album.get('albumName') == album_name:
                album_id = album.get('id')
                logger.debug(f"Found existing album: {album_name} (id: {album_id})")
                return album_id

        # Create new album
        body = {"albumName": album_name}
        logger.debug(f"POST {url} (creating album: {album_name})")
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        album_data = response.json()
        album_id = album_data.get('id')
        logger.debug(f"Created new album: {album_name} (id: {album_id})")
        return album_id

    def _add_assets_to_album(self, album_id: str, asset_ids: List[str]) -> None:
        """Add assets to an album.

        Args:
            album_id: The album ID
            asset_ids: List of asset IDs to add

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/albums/{album_id}/assets"
        headers = {"x-api-key": self.api_key}
        body = {"ids": asset_ids}

        logger.debug(f"PUT {url}")
        logger.debug(f"  Adding {len(asset_ids)} assets to album")
        response = requests.put(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        logger.debug("Assets added to album successfully")

    def _associate_live_photo(self, asset_id: str, live_photo_video_id: str) -> None:
        """Associate a live photo video with an asset.

        Args:
            asset_id: The image asset ID to associate with
            live_photo_video_id: The live photo video ID

        Raises:
            requests.RequestException: If API call fails
        """
        assert self.server_url is not None
        assert self.api_key is not None
        url = f"{self.server_url}/api/assets/{asset_id}"
        headers = {"x-api-key": self.api_key}
        body = {"livePhotoVideoId": live_photo_video_id}

        logger.debug(f"PATCH {url}")
        logger.debug(f"  Associating live video: {live_photo_video_id}")
        response = requests.patch(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        logger.debug("Live photo associated successfully")

    # ========================================================================
    # Processing Logic
    # ========================================================================

    def _extract_path_prefix(self, full_path: str) -> str:
        """Extract the path prefix for searching (remove extension and size suffix).

        Args:
            full_path: Full path like /path/to/IMG_1234_UUID-original.HEIC

        Returns:
            Path prefix like /path/to/IMG_1234_UUID
        """
        path = Path(full_path)
        stem = path.stem

        # Remove size suffix (e.g., -original, -medium, -adjusted)
        for size in ['original', 'medium', 'adjusted', 'thumb', 'alternative']:
            if stem.endswith(f'-{size}'):
                stem = stem[:-len(f'-{size}')]
                break

        return str(path.parent / stem)

    def _wait_for_assets(
        self,
        expected_files: List[Dict[str, Any]],
        timeout: float
    ) -> Dict[str, Dict[str, Any]]:
        """Wait for all expected files to appear in Immich after scan.

        Polls Immich every 50ms until all files are found or timeout occurs.

        Args:
            expected_files: List of file info dicts from current_photo_files
            timeout: Maximum time to wait in seconds (0 = infinite)

        Returns:
            Mapping of path -> asset info (includes 'id', 'originalPath', 'livePhotoVideoId', etc.)

        Raises:
            SystemExit: If timeout exceeded before all assets found
        """
        if not expected_files:
            return {}

        # Extract path prefix from first file (all should share same base)
        first_path = expected_files[0]['path']
        path_prefix = self._extract_path_prefix(first_path)

        # Build set of expected paths for quick lookup
        expected_paths = {f['path'] for f in expected_files}

        logger.info(f"  Waiting for {len(expected_paths)} assets to appear in Immich...")
        logger.debug(f"  Search prefix: {path_prefix}")

        start_time = time.time()
        poll_interval = 0.05  # 50ms
        found_assets: Dict[str, Dict[str, Any]] = {}

        while True:
            # Search for assets
            assets = self._search_assets_by_originalpath(path_prefix)

            # Match found assets to expected paths
            for asset in assets:
                asset_path = asset.get('originalPath', '')
                if asset_path in expected_paths and asset_path not in found_assets:
                    found_assets[asset_path] = asset
                    logger.debug(f"    Found: {asset_path} -> {asset.get('id', 'unknown')}")

            # Check if all found
            if len(found_assets) == len(expected_paths):
                elapsed = time.time() - start_time
                logger.info(f"  All {len(found_assets)} assets found in {elapsed:.2f}s")
                return found_assets

            # Check timeout
            elapsed = time.time() - start_time
            if timeout > 0 and elapsed >= timeout:
                missing = expected_paths - set(found_assets.keys())
                logger.error(f"Timeout waiting for Immich assets after {timeout}s")
                logger.error(f"Found {len(found_assets)}/{len(expected_paths)} assets")
                logger.error(f"Missing: {missing}")
                sys.exit(1)

            # Sleep before next poll
            time.sleep(poll_interval)

    # ========================================================================
    # Main Processing Hook
    # ========================================================================

    def on_download_all_sizes_complete(
        self,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Process all accumulated files after all sizes are downloaded.

        Workflow:
        1. Trigger library scan
        2. Wait for all files to appear in Immich
        3. Stack size variants (if enabled)
        4. Associate live photos with other sizes (if enabled)
        5. Mark favorites (if enabled and photo is iCloud favorite)
        6. Add to albums based on rules
        7. Clear accumulators

        Args:
            photo: PhotoAsset with metadata (for favorite status, date, etc.)
            dry_run: If True, only log what would happen
        """
        # Validate required configuration (should be guaranteed by configure())
        assert self.server_url is not None
        assert self.api_key is not None
        assert self.library_id is not None

        self.total_photos += 1

        # Skip if no files to process
        if not self.current_photo_files:
            logger.debug(f"Immich: No files to process for {photo.filename}")
            return

        logger.info(f"Immich: Processing {photo.filename} ({len(self.current_photo_files)} files)")

        # Dry run mode - just log and clear
        if dry_run:
            for file_info in self.current_photo_files:
                logger.info(f"  [DRY RUN] Would register {file_info['size']}: {file_info['path']}")
            logger.info("  [DRY RUN] Would trigger library scan and wait for assets")
            self.current_photo_files.clear()
            self.live_photo_filename = None
            return

        # Step 1: Trigger library scan
        logger.info(f"  Triggering library scan for {len(self.current_photo_files)} files")
        try:
            self._trigger_library_scan(self.library_id)
        except requests.RequestException as e:
            logger.error(f"Failed to trigger library scan: {e}")
            self.current_photo_files.clear()
            self.live_photo_filename = None
            return

        # Step 2: Wait for all files to appear in Immich
        try:
            found_assets = self._wait_for_assets(
                expected_files=self.current_photo_files,
                timeout=self.scan_timeout
            )
        except SystemExit:
            raise  # Timeout - exit icloudpd

        # Step 3: Build current_immich_assets from found assets
        for file_info in self.current_photo_files:
            path = file_info['path']
            asset = found_assets.get(path)

            if not asset:
                logger.error(f"Asset not found for {path} (should not happen)")
                continue

            self.current_immich_assets.append({
                'size': file_info['size'],
                'asset_id': asset.get('id'),
                'path': path,
                'is_live': file_info['is_live'],
                'photo_filename': file_info['photo_filename'],
                'live_photo_video_id': asset.get('livePhotoVideoId'),
            })

            logger.info(f"  Registered {file_info['size']}: {path} -> {asset.get('id')}")
            self.total_registered += 1

        # Step 4: Stack size variants (if enabled)
        if self.stack_media:
            self._stack_size_variants()

        # Step 5: Associate live photos with other sizes (if enabled and live photo exists)
        if self.associate_live_sizes and self.live_photo_filename:
            self._associate_live_photos()

        # Step 6: Mark favorites (if enabled and photo is iCloud favorite)
        is_favorite = photo._asset_record.get("fields", {}).get("isFavorite", {}).get("value") == 1
        if self.favorite_sizes and is_favorite:
            self._mark_favorites()

        # Step 7: Add to albums based on rules
        if self.album_rules:
            self._apply_album_rules(photo)

        # Clear accumulators for next photo
        self.current_photo_files.clear()
        self.current_immich_assets.clear()
        self.live_photo_filename = None

    def _stack_size_variants(self) -> None:
        """Stack size variants based on priority configuration.

        Only stacks regular (non-live) assets. Live photos are handled separately.
        """
        # Only stack regular (non-live) assets
        regular_assets = [a for a in self.current_immich_assets if not a['is_live']]

        if len(regular_assets) <= 1:
            logger.debug("  No size variants to stack (only 1 asset)")
            return

        # Determine primary based on priority list (first in list = primary)
        asset_ids = [a['asset_id'] for a in regular_assets]

        # Find primary: first size in stack_priority that exists
        primary_id = None
        for size in self.stack_priority:
            for asset in regular_assets:
                if asset['size'] == size:
                    primary_id = asset['asset_id']
                    break
            if primary_id:
                break

        # Fallback to first asset if no priority match
        if not primary_id:
            primary_id = asset_ids[0]

        # Create stack
        try:
            self._create_stack(asset_ids, primary_id)
            logger.info(f"  Stacked {len(asset_ids)} size variants (primary: {primary_id})")
            self.total_stacked += 1
        except requests.RequestException as e:
            logger.error(f"Failed to create stack: {e}")

    def _associate_live_photos(self) -> None:
        """Associate live photo video with other size variants.

        Finds the livePhotoVideoId from one asset and applies it to other sizes.
        """
        # Find the asset with livePhotoVideoId (typically original size)
        live_video_id = None
        for asset in self.current_immich_assets:
            if asset.get('live_photo_video_id'):
                live_video_id = asset['live_photo_video_id']
                logger.debug(f"  Found live video ID: {live_video_id} from {asset['size']}")
                break

        if not live_video_id:
            logger.debug("  No live photo video ID found, skipping association")
            return

        # Associate with configured sizes
        associated_count = 0
        for asset in self.current_immich_assets:
            # Skip if this size is not in the association list
            if asset['size'] not in self.associate_live_sizes:
                continue

            # Skip if already has this live video ID
            if asset.get('live_photo_video_id') == live_video_id:
                continue

            # Associate the live video with this asset
            try:
                self._associate_live_photo(asset['asset_id'], live_video_id)
                logger.info(f"  Associated live video with {asset['size']}")
                associated_count += 1
            except requests.RequestException as e:
                logger.error(f"Failed to associate live photo with {asset['size']}: {e}")

        if associated_count > 0:
            self.total_live_associated += associated_count

    def _mark_favorites(self) -> None:
        """Mark configured sizes as favorite based on iCloud favorite status."""
        # Collect asset IDs for configured favorite sizes
        asset_ids_to_favorite = []

        for asset in self.current_immich_assets:
            # Skip live photos (only favorite images, not videos)
            if asset['is_live']:
                continue

            # Check if this size should be favorited
            if asset['size'] in self.favorite_sizes:
                asset_ids_to_favorite.append(asset['asset_id'])

        if not asset_ids_to_favorite:
            logger.debug("  No assets matched favorite size criteria")
            return

        # Mark as favorite
        try:
            self._set_favorite(asset_ids_to_favorite, True)
            logger.info(f"  Marked {len(asset_ids_to_favorite)} assets as favorite")
            self.total_favorited += len(asset_ids_to_favorite)
        except requests.RequestException as e:
            logger.error(f"Failed to mark favorites: {e}")

    def _apply_album_rules(self, photo: PhotoAsset) -> None:
        """Apply all album rules to determine which assets go in which albums.

        Args:
            photo: PhotoAsset for date/metadata substitution in album templates
        """
        # Build a map of album_name -> [asset_ids]
        album_assignments: Dict[str, List[str]] = {}

        for rule in self.album_rules:
            # Parse the template with photo's created date
            try:
                if '{:' in rule.template:
                    album_name = rule.template.format(photo.created)
                else:
                    album_name = rule.template
            except (AttributeError, ValueError, KeyError) as e:
                logger.error(f"Error parsing album template '{rule.template}': {e}")
                continue

            # Find matching assets (skip live photos - only add images to albums)
            matching_asset_ids = []
            for asset in self.current_immich_assets:
                if asset['is_live']:
                    continue  # Don't add live videos to albums

                if rule.matches(asset['size']):
                    matching_asset_ids.append(asset['asset_id'])

            if matching_asset_ids:
                if album_name not in album_assignments:
                    album_assignments[album_name] = []
                album_assignments[album_name].extend(matching_asset_ids)

        # Add assets to their assigned albums
        for album_name, asset_ids in album_assignments.items():
            # Remove duplicates
            asset_ids = list(set(asset_ids))

            try:
                album_id = self._get_or_create_album(album_name)
                self._add_assets_to_album(album_id, asset_ids)
                logger.info(f"  Added {len(asset_ids)} assets to album '{album_name}'")
                self.total_added_to_albums += 1
            except requests.RequestException as e:
                logger.error(f"Failed to add assets to album '{album_name}': {e}")

    # ========================================================================
    # Run Complete Hook
    # ========================================================================

    def on_run_completed(self, dry_run: bool) -> None:
        """Run complete - show final summary"""
        logger.info("=" * 70)
        logger.info("Immich Plugin: Run Completed")
        logger.info("=" * 70)
        logger.info(f"  Total Photos Processed:    {self.total_photos}")
        logger.info(f"  Files Registered:          {self.total_registered}")
        logger.info(f"  Stacks Created:            {self.total_stacked}")
        logger.info(f"  Assets Favorited:          {self.total_favorited}")
        logger.info(f"  Live Photos Associated:    {self.total_live_associated}")
        logger.info(f"  Albums Updated:            {self.total_added_to_albums}")
        logger.info("=" * 70)

    def cleanup(self) -> None:
        """Cleanup called on shutdown"""
        logger.debug("Immich Plugin: Cleanup called")
