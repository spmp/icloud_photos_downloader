# Immich Plugin for icloudpd

Automatically register downloaded iCloud photos in Immich with advanced organization features.

## Features

- **Automatic Registration**: Photos are automatically registered in Immich after download via external library scanning
- **Size Variant Stacking**: Stack different size variants (original, adjusted, medium, etc.) together
- **Favorites Sync**: Synchronize iCloud favorites to Immich
- **Album Organization**: Organize photos into albums based on rules
- **Live Photo Support**: Associate live photo videos with their images
- **Directory Validation**: Ensures icloudpd directories are within Immich library import paths

## Requirements

- Immich server (tested with v1.100+)
- Immich API key
- Immich external library with configured import paths (this plugin does NOT upload files - it uses Immich's external library feature)
- icloudpd download directory must be within the Immich library's import paths

## Usage

### Basic Usage

```bash
icloudpd --plugin immich \
         --immich-server-url http://localhost:2283 \
         --immich-api-key YOUR_API_KEY \
         --immich-library-id YOUR_LIBRARY_ID
```

**Finding your Library ID:**

You can find your library ID using the Immich API:

```bash
curl -H "x-api-key: YOUR_API_KEY" http://localhost:2283/api/libraries
```

Look for the `id` field of your external library in the JSON response.

### Stacking Size Variants

Stack different size variants with custom priority order:

```bash
icloudpd --plugin immich \
         --immich-server-url http://localhost:2283 \
         --immich-api-key YOUR_API_KEY \
         --immich-library-id YOUR_LIBRARY_ID \
         --immich-stack-media adjusted,original,medium
```

The first size in the list becomes the primary (visible) image in Immich.

**Note:** Omitting a size list (using `--immich-stack-media` with no argument) will stack all available sizes:

```bash
--immich-stack-media  # Stacks all sizes: original, adjusted, alternative, medium, thumb
```

### Syncing Favorites

Mark specific sizes as favorites in Immich when the photo is favorited in iCloud:

```bash
icloudpd --plugin immich \
         --immich-server-url http://localhost:2283 \
         --immich-api-key YOUR_API_KEY \
         --immich-library-id YOUR_LIBRARY_ID \
         --immich-favorite adjusted
```

**Note:** Omitting a size list (using `--immich-favorite` with no argument) will mark all available sizes as favorites:

```bash
--immich-favorite  # Favorites all sizes: original, adjusted, alternative, medium, thumb
```

### Album Organization

Organize photos into albums based on size and custom templates:

```bash
icloudpd --plugin immich \
         --immich-server-url http://localhost:2283 \
         --immich-api-key YOUR_API_KEY \
         --immich-library-id YOUR_LIBRARY_ID \
         --immich-album "[adjusted]:{:%Y}" \
         --immich-album "[original]:Originals"
```

Album rule format: `[size_filter]:album_name`
- `size_filter`: Which sizes to include (e.g., `adjusted`, `original`, `*` for all)
- `album_name`: Album name, supports date formatting (e.g., `{:%Y/%m}` for `2024/03`)

### Processing Existing Files

By default, only newly downloaded files are uploaded. To also process files that already existed:

```bash
icloudpd --plugin immich \
         --immich-server-url http://localhost:2283 \
         --immich-api-key YOUR_API_KEY \
         --immich-library-id YOUR_LIBRARY_ID \
         --immich-process-existing
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--immich-server-url` | Immich server URL | Required |
| `--immich-api-key` | Immich API key | Required |
| `--immich-library-id` | Immich library ID | Required |
| `--immich-process-existing` | Process files that already exist | `False` |
| `--immich-scan-timeout` | Library scan timeout in seconds (0=infinite) | `5.0` |
| `--immich-poll-interval` | Poll interval between asset checks (seconds) | `1.0` |
| `--immich-stack-media` | Stack size variants (comma-separated priority) | Disabled |
| `--immich-favorite` | Which sizes to favorite (comma-separated) | None |
| `--immich-album` | Album rule (can be specified multiple times) | None |

## How It Works

This plugin uses Immich's **external library** feature - it does not upload files. Instead:

1. **Download**: icloudpd downloads photos to a directory within Immich's library import paths
2. **Trigger Scan**: Plugin triggers an Immich external library scan to discover new files
3. **Wait for Assets**: Polls Immich API until all downloaded files are registered as assets
4. **Stack**: If enabled, stacks size variants together using Immich's stack API
5. **Associate Live Photos**: Links live photo videos to images
6. **Mark Favorites**: Syncs favorite status from iCloud to Immich
7. **Organize Albums**: Adds photos to albums based on configured rules

## Directory Validation

The plugin validates that all icloudpd download directories are within Immich library import paths. If validation fails, icloudpd will exit with an error message showing which directories are invalid.

To fix validation errors:
1. Check your Immich library's import paths (Settings → Libraries)
2. Ensure icloudpd download directory is a subdirectory of an import path
3. Date templates (e.g., `%Y/%m`) are stripped before validation

## Troubleshooting

### Assets not found after scan

Increase the scan timeout:
```bash
--immich-scan-timeout 30
```

### Slow asset discovery

Adjust the poll interval:
```bash
--immich-poll-interval 0.5
```

### Directory validation fails

Ensure your icloudpd directory is within Immich's import paths:
```bash
# Example:
# Immich import path: /mnt/photos
# icloudpd directory: /mnt/photos/icloud  ✓ Valid
# icloudpd directory: /home/user/downloads  ✗ Invalid
```

## Version

1.0.0

## License

MIT
