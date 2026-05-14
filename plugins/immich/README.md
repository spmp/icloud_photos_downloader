# Immich Plugin for icloudpd

The Immich plugin integrates icloudpd with [Immich](https://immich.app), an open-source photo management solution. It automatically registers downloaded photos in Immich's external library, creates stacks for size variants, marks favorites, and organizes photos into albums.

> **Note**: This plugin does NOT upload files — it uses Immich's external library feature to discover files already on disk.

## Requirements

- Immich server (tested with v1.100+)
- Immich API key (generate in Immich: Account Settings → API Keys)
- Immich external library with configured import paths
- icloudpd download directory must be within the Immich library's import paths

## Quick Start

```bash
icloudpd \
  --directory /path/to/photos \
  --username me@you.com \
  --plugin immich \
  --immich-server-url http://localhost:2283 \
  --immich-api-key YOUR_API_KEY \
  --immich-library-id YOUR_LIBRARY_ID \
  --immich-stack-media \
  --immich-favorite adjusted
```

**Finding your Library ID:**

```bash
curl -H "x-api-key: YOUR_API_KEY" http://localhost:2283/api/libraries
```

Look for the `id` field of your external library in the JSON response.

## Configuration Reference

### Plugin Options (`--plugin immich`)

```
--immich-server-url URL         Immich server URL (e.g., http://localhost:2283). Required.
--immich-api-key KEY            Immich API key for authentication. Required.
--immich-library-id ID          Immich external library ID. Required.
--immich-process-existing       Process files that already exist on disk, not just newly
                                downloaded ones. Useful for initial setup or rebuilding albums.
--immich-stack-media [SIZES]    Stack size variants together. No argument = all sizes; with
                                argument = comma-separated priority list (first = stack primary).
--immich-favorite [SIZES]       Mark sizes as favorite in Immich based on iCloud favorite
                                status. No argument = all sizes; with argument = comma-separated
                                size list.
--associate-live-with-extra-sizes [SIZES]
                                Associate the live photo MOV with additional size variants so
                                all sizes have live photo playback. No argument = all sizes.
--immich-album RULE             Album assignment rule ([sizes]:template or template for all
                                sizes). Supports date templates, e.g. {:%Y/%m}. Repeatable.
--immich-scan-timeout SECONDS   Maximum seconds to wait for Immich library scan to complete
                                (default: 5.0, 0 = wait indefinitely).
--immich-poll-interval SECONDS  Seconds between polls while waiting for scan (default: 1.0).
--immich-batch-process [N|all]  Accumulate photos before processing to reduce server load.
                                No argument or "all" = process all at end of run; N = process
                                every N photos. Default: disabled (process each immediately).
--immich-batch-log-file PATH    Batch log file for crash recovery
                                (default: ~/.pyicloud/immich_pending_files.json).
```

### Related icloudpd Options

The following core icloudpd options are particularly useful with this plugin:

```
--process-existing-favorites    Mark favorited images for already-downloaded files in Immich.
                                Requires --favorite-to-rating. Use with --until-found for
                                efficiency. Cannot be combined with --immich-process-existing.
```

---

## Stacking (`--immich-stack-media`)

Stack multiple size variants (original, adjusted, medium) together in Immich.

```bash
--immich-stack-media                    # Stack all downloaded sizes
--immich-stack-media adjusted,original  # Stack with adjusted as the primary (top of stack)
```

The first size in the list becomes the primary (visible) asset in the stack. Sizes not listed are appended after in their download order.

> **Note**: Stacks cannot be added to albums. Add individual sizes to albums using `--immich-album`.

---

## Favoriting (`--immich-favorite`)

Sync iCloud favorites to Immich. The plugin reads the `isFavorite` flag from iCloud and marks the specified sizes as favorites in Immich.

```bash
--immich-favorite adjusted              # Mark adjusted size as favorite
--immich-favorite adjusted,medium       # Mark multiple sizes as favorite
--immich-favorite                       # Mark all sizes as favorite
```

---

## Albums (`--immich-album`)

Organize photos into Immich albums using flexible rules. Can be specified multiple times.

```bash
--immich-album "iCloud Photos"                  # All sizes → one album
--immich-album "[adjusted]:iCloud"              # Only adjusted size
--immich-album "[adjusted]:iCloud/{:%Y/%m}"     # Date-based sub-albums
--immich-album "[medium]:iCloud JPG"
--immich-album "[original]:iCloud Raw"
```

**Album rule syntax:**

- `[size1,size2]:template` — Only these sizes go to this album
- `template` — All sizes go to this album
- `{:%Y/%m}` — Date substitution using the photo's creation date (strftime format codes)

**Date-based album examples:**
- `iCloud/{:%Y/%m}` → "iCloud/2024/01", "iCloud/2024/02", etc.
- `Photos/{:%Y}` → "Photos/2024", "Photos/2025", etc.

---

## Live Photo Association (`--associate-live-with-extra-sizes`)

Associate live photo video files with additional size variants so that all sizes support live photo playback in Immich.

```bash
--associate-live-with-extra-sizes                  # Associate with all downloaded sizes
--associate-live-with-extra-sizes adjusted,medium  # Associate with specific sizes
```

By default, Immich auto-associates the MOV only with the original HEIC. This option extends that association to other sizes (e.g., medium, adjusted) so live playback works in all variants.

---

## Processing Modes

### Full Existing Processing (`--immich-process-existing`)

Process files that icloudpd reports as already on disk, not just newly downloaded ones. Useful for initial setup or rebuilding Immich albums after deletion.

```bash
--immich-process-existing
```

**What it does:**
- Registers already-downloaded assets in Immich (triggering library scan if needed)
- Creates stacks for size variants
- Marks favorites based on `--immich-favorite`
- Adds to albums based on `--immich-album`
- Associates live photos

> **Note**: Only covers assets visible to icloudpd. Files deleted from iCloud cannot be processed this way.

### Favorites-Only Mode (`--process-existing-favorites`)

This is a **core icloudpd option** (not plugin-specific) that, when the Immich plugin is active, restricts existing-file processing to favorited photos only. It is especially useful with `--until-found` for cases where photos are favorited in iPhotos some time after they were taken and initially synced.

```bash
--process-existing-favorites
```

Requires `--favorite-to-rating` to be set. Cannot be combined with `--immich-process-existing`.

**What it does:**
- Marks favorites in Immich for existing files that are favorited in iCloud

**What it does NOT do:**
- Unmark favorites
- Process non-favorited files
- Stack, album, or live-associate

**Example — daily download with favorite updates on existing images:**

```bash
icloudpd \
  --directory /mnt/photos \
  --username user@icloud.com \
  --size original --size medium --size adjusted \
  --watch-with-interval 86400 \
  --until-found 1000 \
  --favorite-to-rating 1 \
  --plugin immich \
  --immich-server-url https://immich.example.com \
  --immich-api-key YOUR_API_KEY \
  --immich-library-id abc123 \
  --immich-stack-media \
  --associate-live-with-extra-sizes \
  --immich-favorite adjusted \
  --process-existing-favorites \
  --immich-album "[adjusted]:iCloud"
```

**Example — one-time full sync of existing library:**

```bash
icloudpd \
  --directory /mnt/photos \
  --username user@icloud.com \
  --size original --size medium --size adjusted \
  --plugin immich \
  --immich-server-url https://immich.example.com \
  --immich-api-key YOUR_API_KEY \
  --immich-library-id abc123 \
  --immich-stack-media \
  --associate-live-with-extra-sizes \
  --immich-favorite adjusted \
  --immich-album "[adjusted]:iCloud" \
  --immich-process-existing
```

---

## Batch Processing (`--immich-batch-process`)

Batch processing reduces load on your Immich server by accumulating photos before triggering library scans, so scans happen once per batch rather than once per photo. This prevents OOM errors on the Immich server when processing large libraries.

```bash
--immich-batch-process 10               # Process every 10 photos
--immich-batch-process all              # Process all at end of run
--immich-batch-process                  # Process all at end of run
--immich-batch-log-file /path/file.json # Custom log file (optional)
```

**Options:**
- **No argument or `all`**: Process all photos at end of run
- **Integer N**: Process every N photos
- **Default**: Disabled — each photo is processed immediately

### Crash Recovery

The batch log file (`~/.pyicloud/immich_pending_files.json` by default) tracks unprocessed photos so an interrupted run can resume.

1. During a run, each photo is added to the batch queue and written to the log file.
2. When a batch is successfully processed, those photos are removed from the log file.
3. On the next run, pending photos from the log file are processed first, before new photos.

```bash
# View pending photos
cat ~/.pyicloud/immich_pending_files.json

# Clear pending photos (start fresh)
rm ~/.pyicloud/immich_pending_files.json
```

---

## Performance Tuning

```bash
--immich-scan-timeout 60.0              # Wait up to 60s for library scan (default: 5s)
--immich-poll-interval 1.0              # Check every 1s during scan wait (default: 1s)
```

- `--immich-scan-timeout`: Maximum seconds to wait for Immich to scan and register files. Use `0` for infinite wait. Increase if your Immich server is slow to scan.
- `--immich-poll-interval`: How frequently to check if assets are registered. Lower = more responsive, but more API calls.

---

## Real-World Example

Complete setup for continuous sync with Immich integration:

```bash
icloudpd \
  --directory /path/to/iCloud \
  --cookie-directory /home/user/.pyicloud \
  --username me@you.com \
  --folder-structure none \
  --set-exif-datetime \
  --watch-with-interval 86400 \
  --until-found 1000 \
  --keep-unicode-in-filenames \
  --file-match-policy name-id7 \
  --size original --size medium --size adjusted \
  --log-level debug \
  --xmp-sidecar \
  --favorite-to-rating 1 \
  --plugin immich \
  --immich-server-url http://localhost:2283 \
  --immich-api-key "XYZ" \
  --immich-library-id "ABC" \
  --immich-stack-media \
  --immich-favorite adjusted \
  --process-existing-favorites \
  --associate-live-with-extra-sizes \
  --immich-scan-timeout 60.0 \
  --immich-poll-interval 1.0 \
  --immich-batch-process 10 \
  --immich-album "[adjusted]:iCloud" \
  --immich-album "[medium]:iCloud JPG" \
  --immich-album "[original]:iCloud Raw"
```

This configuration:
- Downloads 3 sizes (original, medium, adjusted)
- Runs daily via `--watch-with-interval 86400`
- Checks up to 1000 existing photos per run (`--until-found 1000`)
- Updates favorites for existing favorited photos (`--process-existing-favorites`)
- Batches every 10 photos to reduce server load
- Stacks all size variants together
- Marks adjusted size as favorite in Immich
- Organizes into 3 albums by size type

---

## How It Works

This plugin uses Immich's **external library** feature:

1. **Download**: icloudpd downloads photos to a directory within Immich's library import paths
2. **Trigger Scan**: Plugin triggers an Immich external library scan to discover new files
3. **Wait for Assets**: Polls Immich API until all downloaded files are registered as assets
4. **Stack**: If enabled, stacks size variants using Immich's stack API
5. **Associate Live Photos**: Links live photo videos to image assets
6. **Mark Favorites**: Syncs favorite status from iCloud to Immich
7. **Organize Albums**: Adds photos to albums based on configured rules

---

## Directory Validation

The plugin validates that all icloudpd download directories are within Immich library import paths. If validation fails, icloudpd exits with an error showing which directories are invalid.

To fix validation errors:
1. Check your Immich library's import paths (Settings → Libraries)
2. Ensure the icloudpd download directory is a subdirectory of an import path
3. Date templates (e.g., `%Y/%m`) in the folder structure are stripped before validation

```bash
# Immich import path: /mnt/photos
# icloudpd directory: /mnt/photos/icloud  ✓ Valid
# icloudpd directory: /home/user/downloads  ✗ Invalid
```

---

## License

MIT
