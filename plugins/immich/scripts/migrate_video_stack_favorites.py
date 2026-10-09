#!/usr/bin/env python3
"""Move favorites in existing Immich video stacks to a selected size.

The script is dry-run by default and only handles video-only stacks. By
default, it processes stacks with exactly one favorited video, regardless of
which size that video is. Use --source to require a particular current size.
Stacks with multiple favorites are skipped unless --force is supplied.

Usage:
    python3 migrate_video_stack_favorites.py \
        --server-url https://immich.example.com --target original

    python3 migrate_video_stack_favorites.py \
        --server-url https://immich.example.com \
        --source adjusted --target original --apply
"""

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional

import requests

API_KEY_ENV_VAR = "IMMICH_API_KEY"
KNOWN_SIZES = ("original", "adjusted", "alternative", "medium", "thumb")
SIZE_SUFFIX_RE = re.compile(r"-(adjusted|alternative|medium|thumb)(?=\.[^.]+$)", re.IGNORECASE)


def resolve_api_key(cli_value: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    return cli_value or env.get(API_KEY_ENV_VAR)


def asset_path(asset: Mapping[str, Any]) -> str:
    return str(asset.get("originalPath") or asset.get("originalFileName") or "")


def asset_size(asset: Mapping[str, Any]) -> str:
    match = SIZE_SUFFIX_RE.search(asset_path(asset))
    return match.group(1).lower() if match else "original"


def is_video_asset(asset: Mapping[str, Any]) -> bool:
    return str(asset.get("type", "")).upper() == "VIDEO"


def get_all_stacks(server_url: str, api_key: str) -> List[Dict[str, Any]]:
    response = requests.get(
        f"{server_url}/api/stacks", headers={"x-api-key": api_key}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def set_favorite(server_url: str, api_key: str, asset_ids: List[str], value: bool) -> None:
    if not asset_ids:
        return
    response = requests.put(
        f"{server_url}/api/assets",
        headers={"x-api-key": api_key},
        json={"ids": asset_ids, "isFavorite": value},
        timeout=30,
    )
    response.raise_for_status()


def candidate_favorite_migration(
    stack: Mapping[str, Any], target_size: str, source_size: Optional[str], force: bool
) -> tuple[List[str], List[str], str] | None:
    """Return (old favorite IDs, new favorite IDs, description) if actionable."""
    assets = stack.get("assets", [])
    if not isinstance(assets, list) or len(assets) < 2:
        return None
    if not all(isinstance(asset, dict) and is_video_asset(asset) for asset in assets):
        return None

    favorite_assets = [asset for asset in assets if asset.get("isFavorite") is True]
    if not favorite_assets or (len(favorite_assets) > 1 and not force):
        return None
    if source_size and not any(asset_size(asset) == source_size for asset in favorite_assets):
        return None

    target_assets = [asset for asset in assets if asset_size(asset) == target_size]
    if len(target_assets) != 1:
        return None

    target_id = target_assets[0].get("id")
    old_ids = [asset.get("id") for asset in favorite_assets if asset.get("id") != target_id]
    if not target_id or any(not asset_id for asset_id in old_ids):
        return None
    if not old_ids:
        return None

    source_description = ", ".join(
        f"{asset_size(asset)} ({asset_path(asset)})" for asset in favorite_assets
    )
    return old_ids, [target_id], source_description


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--server-url", required=True, metavar="URL", help="Immich server URL")
    parser.add_argument(
        "--api-key", default=None, metavar="KEY", help=f"Immich API key. Falls back to {API_KEY_ENV_VAR}."
    )
    parser.add_argument(
        "--source", choices=KNOWN_SIZES, default=None, help="Current favorite size to migrate."
    )
    parser.add_argument(
        "--target", choices=KNOWN_SIZES, default="original", help="Size to favorite (default: original)."
    )
    parser.add_argument(
        "--library-id", default=None, metavar="ID", help="Only process stacks in this library."
    )
    parser.add_argument(
        "--force", action="store_true", help="Migrate stacks with multiple current favorites."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually update favorites. Without this, only reports changes."
    )
    args = parser.parse_args()

    api_key = resolve_api_key(args.api_key, os.environ)
    if not api_key:
        parser.error(f"An API key is required: pass --api-key or set {API_KEY_ENV_VAR}")

    server_url = args.server_url.rstrip("/")
    try:
        stacks = get_all_stacks(server_url, api_key)
    except requests.RequestException as error:
        print(f"Error: Failed to fetch stacks from Immich: {error}", file=sys.stderr)
        sys.exit(1)

    candidates = []
    multiple_favorites = 0
    for stack in stacks:
        assets = stack.get("assets", [])
        if not isinstance(assets, list) or not all(
            isinstance(asset, dict) and is_video_asset(asset) for asset in assets
        ):
            continue
        if args.library_id and not all(
            asset.get("libraryId") == args.library_id for asset in assets
        ):
            continue
        favorite_count = sum(asset.get("isFavorite") is True for asset in assets)
        if favorite_count > 1:
            multiple_favorites += 1
        migration = candidate_favorite_migration(
            stack, args.target, args.source, args.force
        )
        if migration:
            candidates.append((stack, *migration))

    print(f"Fetched {len(stacks)} stack(s) from Immich")
    print(f"Video stacks needing favorite migration: {len(candidates)}")
    if multiple_favorites and not args.force:
        print(
            f"Stacks with multiple favorites skipped: {multiple_favorites} "
            "(use --force to include them)"
        )

    if not candidates:
        print("Nothing to do.")
        return

    for stack, old_ids, new_ids, source_description in candidates:
        print(
            f"  - stack {stack.get('id')}: {source_description} -> "
            f"{args.target} ({new_ids[0]})"
        )

    if not args.apply:
        print("\nDry run: no changes made. Re-run with --apply to migrate these favorites.")
        return

    changed = 0
    try:
        for _, old_ids, new_ids, _ in candidates:
            set_favorite(server_url, api_key, old_ids, False)
            set_favorite(server_url, api_key, new_ids, True)
            changed += 1
    except requests.RequestException as error:
        print(f"Error: Failed after migrating {changed} stack(s): {error}", file=sys.stderr)
        sys.exit(1)

    print(f"\nMigrated favorites for {changed} video stack(s).")


if __name__ == "__main__":
    main()
