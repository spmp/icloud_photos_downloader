# Plugin System

icloudpd includes a plugin system that allows you to extend functionality by hooking into the download process. Plugins can respond to events like file downloads, processing completions, and more.

## Overview

The plugin system uses a **hook-based architecture** where plugins can register callbacks for specific events during the download process. This allows you to:

- Process photos after they're downloaded (e.g., upload to cloud storage)
- Organize files based on metadata (e.g., create albums, stacks)
- Track download statistics and generate reports
- Integrate with external services (e.g., Immich, PhotoPrism)

## Built-in Plugins

### Immich Plugin

The [Immich plugin](../plugins/immich/README.md) integrates with [Immich](https://immich.app) photo management. It automatically:
- Registers downloaded photos in Immich's external library
- Creates stacks for size variants (original, adjusted, medium)
- Syncs favorites from iCloud to Immich
- Organizes photos into albums
- Associates live photo videos with images

See the [Immich plugin README](../plugins/immich/README.md) for complete documentation.

### Demo Plugin

The demo plugin demonstrates the plugin system's capabilities. Use it as a reference when building your own plugins:

```bash
icloudpd --plugin demo --demo-verbose --recent 5
```

See [`src/icloudpd/plugins/demo.py`](../src/icloudpd/plugins/demo.py) for the implementation.

## Using Plugins

### Enabling a Plugin

Enable a plugin with the `--plugin` flag:

```bash
icloudpd --directory /photos --username me@example.com --plugin immich
```

### Plugin-Specific Options

Each plugin adds its own CLI arguments. Use `--help` to see available options:

```bash
icloudpd --plugin immich --help
```

## Available Hooks

Plugins can implement the following hooks to respond to download events:

### Per-Size Hooks

These hooks are called for each size variant (original, adjusted, medium, etc.) of a photo:

#### `on_download_exists(download_path, photo_filename, download_size, photo, dry_run)`

Called when a file already exists on disk (not downloaded).

**Parameters:**
- `download_path` (str): Full path to the file
- `photo_filename` (str): Original filename from iCloud
- `download_size` (VersionSize): Size variant (ORIGINAL, ADJUSTED, MEDIUM, etc.)
- `photo` (PhotoAsset): Photo metadata object
- `dry_run` (bool): True if running in dry-run mode

**Use case:** Track which files already exist, skip processing for existing files

#### `on_download_downloaded(download_path, photo_filename, download_size, photo, dry_run)`

Called when a file is newly downloaded.

**Parameters:** Same as `on_download_exists`

**Use case:** Process newly downloaded files, upload to external service

#### `on_download_complete(download_path, photo_filename, download_size, photo, dry_run)`

Called after a size variant is fully processed (always runs, regardless of exists/downloaded).

**Parameters:** Same as `on_download_exists`

**Use case:** Ensure all files are tracked, even if they didn't go through exists or downloaded hooks

### Live Photo Hooks

These hooks are called for live photo video components (.mov files):

#### `on_download_exists_live(download_path, photo_filename, download_size, photo, dry_run)`

Called when a live photo video already exists.

**Parameters:** Same as `on_download_exists`

#### `on_download_downloaded_live(download_path, photo_filename, download_size, photo, dry_run)`

Called when a live photo video is newly downloaded.

**Parameters:** Same as `on_download_exists`

#### `on_download_complete_live(download_path, photo_filename, download_size, photo, dry_run)`

Called after a live photo video is fully processed.

**Parameters:** Same as `on_download_exists`

### Completion Hooks

#### `on_download_all_sizes_complete(photo, dry_run)`

**MOST IMPORTANT HOOK** - Called after all size variants of a photo are downloaded/processed.

**Parameters:**
- `photo` (PhotoAsset): Complete photo metadata
- `dry_run` (bool): True if running in dry-run mode

**Use case:** Process all variants together (e.g., stack them, upload as a group, add to album)

**Why this hook is critical:**
- This is where you process the complete photo with all its size variants
- You have access to all accumulated file paths from previous hooks
- You can read photo metadata (favorite status, creation date, etc.)
- This is the right place to clear your accumulators for the next photo

#### `on_run_completed(dry_run)`

Called when the entire icloudpd run completes.

**Parameters:**
- `dry_run` (bool): True if running in dry-run mode

**Use case:** Generate final reports, upload statistics, cleanup tasks

## Building a Plugin

### 1. Plugin Structure

Create a new plugin by inheriting from `IcloudpdPlugin`:

```python
import logging
from argparse import ArgumentParser, Namespace

from icloudpd.plugins.base import IcloudpdPlugin
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import VersionSize

# Initialize logger with explicit namespace
logger = logging.getLogger("icloudpd.plugins.myplugin")


class MyPlugin(IcloudpdPlugin):
    """My custom plugin"""

    def __init__(self):
        """Initialize plugin state"""
        # Accumulators for current photo
        self.current_files = []

        # Global counters
        self.total_photos = 0

    @property
    def name(self) -> str:
        """Plugin name (used with --plugin flag)"""
        return "myplugin"

    @property
    def version(self) -> str:
        """Plugin version"""
        return "1.0.0"

    @property
    def description(self) -> str:
        """Plugin description (shown in --help)"""
        return "My custom plugin for processing photos"
```

### 2. Add CLI Arguments

```python
def add_arguments(self, parser: ArgumentParser) -> None:
    """Add plugin-specific CLI arguments"""
    group = parser.add_argument_group('MyPlugin Options')
    group.add_argument(
        '--myplugin-option',
        help='Example plugin option'
    )
```

### 3. Configure from Arguments

```python
def configure(self, config: Namespace, global_config=None, user_configs=None) -> None:
    """Configure plugin from parsed arguments"""
    self.option = getattr(config, 'myplugin_option', 'default')

    # Use print() in configure() - logger not yet initialized
    print("=" * 70)
    print(f"MyPlugin: Initialized (version {self.version})")
    print(f"  Option: {self.option}")
    print("=" * 70)
```

### 4. Implement Hooks

**CRITICAL PATTERN - Use the Accumulator Pattern:**

```python
def on_download_downloaded(
    self,
    download_path: str,
    photo_filename: str,
    download_size: VersionSize,
    photo: PhotoAsset,
    dry_run: bool,
) -> None:
    """Accumulate downloaded files"""
    logger.info(f"Downloaded: {download_size.value} - {download_path}")

    # ACCUMULATE - don't process yet!
    self.current_files.append({
        'path': download_path,
        'size': download_size.value,
        'status': 'downloaded'
    })

def on_download_all_sizes_complete(
    self,
    photo: PhotoAsset,
    dry_run: bool,
) -> None:
    """Process all accumulated files for this photo"""
    self.total_photos += 1

    logger.info(f"Processing photo: {photo.filename}")
    logger.info(f"  Files: {len(self.current_files)}")

    # Process all accumulated files together
    for file_info in self.current_files:
        # Upload to service, create stacks, etc.
        self._process_file(file_info)

    # CRITICAL: Clear accumulator for next photo
    self.current_files.clear()

def on_run_completed(self, dry_run: bool) -> None:
    """Final summary"""
    logger.info("=" * 70)
    logger.info("MyPlugin: Run Completed")
    logger.info(f"  Total Photos: {self.total_photos}")
    logger.info("=" * 70)
```

### 5. Install Your Plugin

Place your plugin in one of these locations:

1. **Built-in plugins:** `src/icloudpd/plugins/myplugin.py`
2. **External plugins:** `~/.icloudpd/plugins/myplugin.py` (if supported)

Then use it with:

```bash
icloudpd --plugin myplugin --myplugin-option value
```

## Key Concepts and Gotchas

### 1. The Accumulator Pattern

**DO THIS:**
```python
# Accumulate in per-size hooks
def on_download_downloaded(self, download_path, ...):
    self.current_files.append({'path': download_path})

# Process in all-sizes-complete hook
def on_download_all_sizes_complete(self, photo, dry_run):
    # Process all files together
    for file in self.current_files:
        self._process(file)

    # CRITICAL: Clear for next photo
    self.current_files.clear()
```

**DON'T DO THIS:**
```python
# WRONG: Processing in per-size hook
def on_download_downloaded(self, download_path, ...):
    self._process(download_path)  # ❌ Wrong! Process in all_sizes_complete
```

**Why:** You need all size variants together to create stacks, determine which file is primary, etc.

### 2. Logger Initialization

**DO THIS:**
```python
import logging

# Use explicit namespace
logger = logging.getLogger("icloudpd.plugins.myplugin")
```

**DON'T DO THIS:**
```python
# WRONG: Using __name__
logger = logging.getLogger(__name__)  # ❌ Can vary depending on import
```

**Why:** Explicit namespace ensures correct logger hierarchy and inheritance.

### 3. Print vs Logger

**In `configure()`:** Use `print()` - logging not yet initialized
```python
def configure(self, config, ...):
    print("Plugin: Initialized")  # ✓ Correct in configure()
```

**Everywhere else:** Use `logger`
```python
def on_download_downloaded(self, ...):
    logger.info("Downloaded file")  # ✓ Correct in hooks
```

### 4. Accessing Photo Metadata

```python
def on_download_all_sizes_complete(self, photo: PhotoAsset, dry_run):
    # Check if photo is favorite
    is_fav = photo._asset_record.get("fields", {}).get("isFavorite", {}).get("value") == 1

    # Get creation date
    created = photo.created

    # Get photo ID
    photo_id = photo.id

    # Get filename
    filename = photo.filename
```

### 5. Dry Run Mode

Always respect the `dry_run` flag:

```python
def on_download_all_sizes_complete(self, photo, dry_run):
    if dry_run:
        logger.info(f"[DRY RUN] Would process {photo.filename}")
        self.current_files.clear()
        return

    # Actual processing
    self._process_files()
    self.current_files.clear()
```

### 6. Error Handling

Don't crash icloudpd - handle errors gracefully:

```python
def on_download_all_sizes_complete(self, photo, dry_run):
    try:
        self._process_files()
    except Exception as e:
        logger.error(f"Failed to process {photo.filename}: {e}")
        # Continue - don't raise
    finally:
        # ALWAYS clear accumulator
        self.current_files.clear()
```

### 7. Cleanup

Implement cleanup for graceful shutdown:

```python
def cleanup(self) -> None:
    """Called on shutdown"""
    logger.debug("MyPlugin: Cleanup called")
    # Close connections, save state, etc.
```

## Common Patterns

### Pattern 1: File Accumulation with Metadata

```python
def on_download_downloaded(self, download_path, photo_filename, download_size, photo, dry_run):
    self.current_files.append({
        'path': download_path,
        'size': download_size.value,
        'status': 'downloaded',
        'is_live': False,
        'filename': photo_filename,
    })

def on_download_exists(self, download_path, photo_filename, download_size, photo, dry_run):
    self.current_files.append({
        'path': download_path,
        'size': download_size.value,
        'status': 'existed',
        'is_live': False,
        'filename': photo_filename,
    })
```

### Pattern 2: Conditional Processing

```python
def on_download_all_sizes_complete(self, photo, dry_run):
    # Only process favorites
    is_fav = photo._asset_record.get("fields", {}).get("isFavorite", {}).get("value") == 1

    if not is_fav:
        logger.debug(f"Skipping non-favorite: {photo.filename}")
        self.current_files.clear()
        return

    # Process favorite
    self._process_favorite(photo)
    self.current_files.clear()
```

### Pattern 3: Batch Processing

```python
def __init__(self):
    self.current_files = []
    self.batch_queue = []
    self.batch_size = 10

def on_download_all_sizes_complete(self, photo, dry_run):
    # Add to batch
    self.batch_queue.append({
        'photo': photo,
        'files': self.current_files.copy()
    })
    self.current_files.clear()

    # Process when batch full
    if len(self.batch_queue) >= self.batch_size:
        self._process_batch()

def on_run_completed(self, dry_run):
    # Process remaining batch
    if self.batch_queue:
        self._process_batch()
```

## Testing Your Plugin

### Unit Testing

```python
import unittest
from unittest.mock import Mock
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import AssetVersionSize

class TestMyPlugin(unittest.TestCase):
    def test_accumulation(self):
        plugin = MyPlugin()
        plugin.configure(Mock(myplugin_option='test'))

        mock_photo = Mock(spec=PhotoAsset)
        mock_photo.filename = 'test.jpg'

        # Simulate download
        plugin.on_download_downloaded(
            download_path='/path/test.jpg',
            photo_filename='test.jpg',
            download_size=AssetVersionSize.ORIGINAL,
            photo=mock_photo,
            dry_run=False
        )

        # Verify accumulation
        self.assertEqual(len(plugin.current_files), 1)

        # Simulate completion
        plugin.on_download_all_sizes_complete(
            photo=mock_photo,
            dry_run=False
        )

        # Verify cleared
        self.assertEqual(len(plugin.current_files), 0)
```

### Integration Testing

Test with real icloudpd:

```bash
# Test with demo plugin first
icloudpd --plugin demo --demo-verbose --recent 1

# Test your plugin
icloudpd --plugin myplugin --myplugin-option test --recent 1 --dry-run
```

## Examples

See these plugins for real-world examples:

- **Immich Plugin** ([plugins/immich/immich.py](../plugins/immich/immich.py)) - Complete production plugin with stacking, favorites, albums, batch processing
- **Demo Plugin** ([src/icloudpd/plugins/demo.py](../src/icloudpd/plugins/demo.py)) - Educational example showing all hooks and patterns

## Plugin Lifecycle

```
icloudpd starts
  ↓
Plugin.__init__()
  ↓
Plugin.add_arguments(parser)
  ↓
[Arguments parsed]
  ↓
Plugin.configure(config)
  ↓
[For each photo]
  ↓
  [For each size variant]
    ↓
    on_download_exists() OR on_download_downloaded()
    ↓
    on_download_complete()
  ↓
  [For each live photo]
    ↓
    on_download_exists_live() OR on_download_downloaded_live()
    ↓
    on_download_complete_live()
  ↓
  on_download_all_sizes_complete()  ← KEY HOOK
  ↓
[After all photos]
  ↓
on_run_completed()
  ↓
cleanup()
  ↓
icloudpd exits
```

## Best Practices

1. ✅ **Use the accumulator pattern** - collect data in per-size hooks, process in all-sizes-complete
2. ✅ **Always clear accumulators** - prevent data leaking between photos
3. ✅ **Use explicit logger names** - `logging.getLogger("icloudpd.plugins.myplugin")`
4. ✅ **Respect dry-run mode** - check the flag and skip actual operations
5. ✅ **Handle errors gracefully** - don't crash icloudpd
6. ✅ **Use print() only in configure()** - use logger everywhere else
7. ✅ **Document your options** - add clear help text to CLI arguments
8. ✅ **Test with --dry-run first** - verify behavior before processing real files

## Troubleshooting

### Plugin not found

Check that:
1. Plugin file is in `src/icloudpd/plugins/` directory
2. Plugin class name matches the pattern `{Name}Plugin`
3. Plugin implements required properties: `name`, `version`, `description`

### Hooks not being called

Check that:
1. Hook method signatures exactly match the base class
2. Hook methods accept all required parameters
3. You're not raising exceptions in hooks

### Data not accumulating

Check that:
1. You're appending to accumulators in per-size hooks
2. You're not clearing accumulators too early
3. You're clearing accumulators in `on_download_all_sizes_complete`

### Logger not working

Check that:
1. You initialized logger with explicit namespace: `logging.getLogger("icloudpd.plugins.myplugin")`
2. You're using `print()` in `configure()` (before logging is initialized)
3. You're using `logger` everywhere else

## Additional Resources

- [Base Plugin Class](../src/icloudpd/plugins/base.py) - Reference implementation
- [Plugin Manager](../src/icloudpd/plugins/manager.py) - How plugins are loaded and called
- [Immich Plugin README](../plugins/immich/README.md) - Complete plugin documentation
- [PhotoAsset API](https://github.com/icloud-photos-downloader/icloud_photos_downloader) - Photo metadata reference
