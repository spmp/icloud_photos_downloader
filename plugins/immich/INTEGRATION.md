# Immich Plugin — Complete Immich Interaction Reference

Generated from `plugins/immich/immich.py` (plugin v2.0.5), for discussion with
Immich upstream about API contract changes. This document is descriptive of
the code as-is, not aspirational.

**Key fact for readers unfamiliar with this integration:** the plugin never
uploads photo bytes to Immich. icloudpd writes files to a directory shared
with Immich (the library's `importPaths`), and the plugin only talks to
Immich's management/metadata REST API (`x-api-key` auth) to tell it to scan,
then to query/organize what it found.

---

## 1. Architecture / data flow

```mermaid
graph LR
    iCloud[(iCloud Photos)] -->|pyicloud API| icloudpd[icloudpd core]
    icloudpd -->|writes files| Disk[/Shared filesystem<br/>Immich library importPath/]
    icloudpd -->|plugin hooks| Plugin[Immich Plugin]
    Plugin -->|REST API, x-api-key| API[Immich Server API]
    API -->|scans/reads| Disk
    API --> DB[(Immich DB / asset store)]
    Plugin -.->|batch log JSON<br/>crash recovery only, not Immich| Log[/immich_pending_files.json/]

    style Disk fill:#f9f5e3,stroke:#c9a94d
    style API fill:#e3f2fd,stroke:#1565c0
```

---

## 2. Startup / configuration validation

Runs once per icloudpd invocation, before any downloads happen.

```mermaid
sequenceDiagram
    autonumber
    participant Core as icloudpd core
    participant Plugin as Immich Plugin
    participant API as Immich API
    participant FS as Local disk (batch log)

    Core->>Plugin: configure(cli_args, global_config, user_configs)
    Plugin->>API: GET /api/server/about
    API-->>Plugin: 200 OK
    Plugin->>API: GET /api/libraries/{library_id}
    API-->>Plugin: 200 OK { name, importPaths: [...] }
    Plugin->>Plugin: assert every icloudpd download dir is a<br/>subdirectory of an importPath (date templates stripped)
    alt connection fails, library not found, or dir outside importPaths
        Plugin-->>Core: print error, sys.exit(1)
    end
    opt batch_size != 1 (batch mode enabled)
        Plugin->>FS: read immich_pending_files.json
        FS-->>Plugin: pending batch items left from a crashed prior run, if any
    end
    Core->>Plugin: on_configure_complete()
    opt pending batch loaded above is non-empty
        Plugin->>Plugin: _process_batch() — drains it immediately (see §4/§5)
    end
```

---

## 3. Per-size download hooks → batch accumulation

Purely local bookkeeping; no Immich calls happen here. This is what feeds
the registration pipeline in §4.

```mermaid
sequenceDiagram
    autonumber
    participant Core as icloudpd core
    participant Plugin as Immich Plugin
    participant FS as Local disk (batch log)

    loop for each configured size (original / medium / adjusted / ...)
        Core->>Plugin: on_download_downloaded(path, size, photo)<br/>or on_download_exists(...)
        Plugin->>Plugin: current_photo_files.append({status, path, size})
    end
    Core->>Plugin: on_download_all_sizes_complete(photo)
    Plugin->>Plugin: _accumulate_to_batch(photo) → batch_queue.append(...)
    Plugin->>FS: overwrite immich_pending_files.json (crash recovery)
    alt batch_size reached (batch_size==1 ⇒ every photo)
        Plugin->>Plugin: _process_batch()  →  §4 / §5
    else still accumulating
        Note over Plugin: wait for more photos, or on_run_completed()
    end
```

---

## 4. Asset registration algorithm (search-before-scan)

This is the part most sensitive to upstream API/behavior changes — it's a
polling loop built entirely on `/api/search/metadata` exact-path lookups
plus a single library-scan trigger per batch.

```mermaid
flowchart TD
    A[Batch ready to process] --> B["POST /api/search/metadata<br/>for every file path (no scan yet)"]
    B --> C{All files found?}
    C -- yes --> Z[Proceed to post-processing, §5]
    C -- no --> D["POST /api/libraries/{id}/scan<br/>{refreshAllFiles: false}<br/>(at most once per batch)"]
    D --> E[Immich scans filesystem asynchronously]
    E --> F[sleep poll_interval seconds]
    F --> G["POST /api/search/metadata<br/>for still-missing paths only"]
    G --> H{All files found now?}
    H -- yes --> Z
    H -- no --> I{elapsed >= scan_timeout<br/>and scan_timeout != 0?}
    I -- no --> F
    I -- yes --> J[log error, sys.exit 1]
```

Notes:
- Every photo group whose files become fully available mid-poll is
  processed immediately (`_process_ready_groups`), not just at the end —
  so a batch of N photos can finish at N different times within one poll loop.
- `scan_timeout=0` means wait indefinitely.

---

## 5. Post-processing pipeline (per photo group)

Runs once all of a photo's size-variant files are confirmed registered as
Immich assets.

```mermaid
sequenceDiagram
    autonumber
    participant Plugin as Immich Plugin
    participant API as Immich API

    Note over Plugin: assets = [{size, asset_id, live_photo_video_id}, ...]

    opt --immich-stack-media
        Plugin->>API: POST /api/stacks { assetIds: [primary, ...] }
        API-->>Plugin: 201 Created
    end

    opt --associate-live-with-extra-sizes AND a live_photo_video_id exists
        loop each target size not already carrying that video id
            Plugin->>API: PUT /api/assets { ids:[asset_id], livePhotoVideoId }
            API-->>Plugin: 200 OK
        end
    end

    opt --immich-favorite AND photo.isFavorite in iCloud
        Plugin->>API: PUT /api/assets { ids: [...favorite sizes], isFavorite: true }
        API-->>Plugin: 200 OK
    end

    opt --immich-album rules configured
        loop each album name matched by a rule
            Plugin->>API: GET /api/albums
            API-->>Plugin: [ {id, albumName}, ... ]
            alt album not found by exact name
                Plugin->>API: POST /api/albums { albumName }
                API-->>Plugin: 201 Created { id }
            end
            Plugin->>API: PUT /api/albums/{album_id}/assets { ids: [...] }
            API-->>Plugin: 200 OK
        end
    end
```

`on_run_completed()` drains any still-pending batch through §4/§5 one more
time, then logs a summary (`total_photos`, `total_registered`,
`total_stacked`, `total_favorited`, `total_live_associated`,
`total_added_to_albums`). `cleanup()` is a no-op.

---

## 6. Complete Immich API surface used

All requests send header `x-api-key: <api_key>`. This is the entire set of
endpoints the plugin depends on.

| # | Method | Endpoint | Purpose | Called from | Request body | Frequency |
|---|--------|----------|---------|--------------|---------------|-----------|
| 1 | GET  | `/api/server/about` | Connectivity/auth check | `_test_immich_connection` | – | once at startup |
| 2 | GET  | `/api/libraries/{library_id}` | Validate library exists; read `name` + `importPaths` | `_test_immich_connection`, `_validate_directories` | – | 1–2× at startup |
| 3 | POST | `/api/libraries/{library_id}/scan` | Trigger external library rescan | `_trigger_library_scan` | `{ refreshAllFiles: false }` | ≤1 per batch |
| 4 | POST | `/api/search/metadata` | Look up one asset by exact `originalPath` | `_search_asset_by_path` | `{ originalPath: <abs path> }` | per file, repeated while polling |
| 5 | POST | `/api/stacks` | Group size variants into a stack (first id = primary) | `_create_stack` | `{ assetIds: [...] }` | once per photo group, if stacking enabled |
| 6 | PUT  | `/api/assets` | Bulk-set `isFavorite` | `_set_favorite` | `{ ids: [...], isFavorite }` | once per photo group, if favoriting enabled |
| 6b| PUT  | `/api/assets` | Set `livePhotoVideoId` (single asset per call) | `_associate_live_photo` | `{ ids: [asset_id], livePhotoVideoId }` | once per target size, if live-assoc enabled |
| 7 | GET  | `/api/albums` | List all albums, find by exact `albumName` | `_get_or_create_album` | – | once per album name touched |
| 8 | POST | `/api/albums` | Create album if not found in step 7 | `_get_or_create_album` | `{ albumName }` | once per new album |
| 9 | PUT  | `/api/albums/{album_id}/assets` | Add assets to album | `_add_assets_to_album` | `{ ids: [...] }` | once per album per photo group |

---

## 7. Behavioral assumptions baked into this plugin

These are documented in the top-of-file docstring in `immich.py` and are
the most likely candidates if upstream API *semantics* (not just schema)
have shifted — worth confirming line-by-line with the Immich team:

- **Stacking**: stacks are visual groupings only, not independently
  addressable by ID; stacked assets don't appear grouped in albums; deleting
  a stack leaves favorited member assets in favorites.
- **Favoriting**: individual assets or whole stacks can be favorited;
  favorited assets within a stack still show stacked in the favorites view.
- **Albums**: stacks cannot be added to albums — only individual assets;
  this plugin deliberately dropped a `[stacked]` album-rule target for that
  reason (see `AlbumRule.__init__`).
- **Live photos**: Immich auto-associates a MOV with the *original* HEIC
  only; the plugin's `--associate-live-with-extra-sizes` exists purely to
  extend that association to other size variants via `livePhotoVideoId`.
- **External library scan**: `POST /api/libraries/{id}/scan` is
  fire-and-forget/async — the plugin has no scan-completion signal and only
  infers completion by polling `/api/search/metadata` until expected paths
  resolve, bounded by `--immich-scan-timeout`.

README states this plugin was "tested with Immich v1.100+" — worth
establishing which version(s) the current break has been observed against.
