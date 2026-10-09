#!/usr/bin/env python3
"""Reorder Immich video stacks so a selected video size is primary.

The script is deliberately dry-run by default. It only considers stacks whose
members are all Immich video assets. Mixed image/video stacks are reported and
skipped. Use --apply to submit the reordered member IDs to Immich.

The size is inferred from the filename suffix used by icloudpd:

    IMG_1234.MOV          -> original
    IMG_1234-medium.MOV   -> medium
    IMG_1234-adjusted.MOV -> adjusted

Usage:
    python3 reorder_video_stack_primary.py --server-url https://immich.example.com
    python3 reorder_video_stack_primary.py --server-url https://immich.example.com \
        --primary original --apply
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
    """Resolve the API key from the CLI argument or environment."""
    return cli_value or env.get(API_KEY_ENV_VAR)


def asset_path(asset: Mapping[str, Any]) -> str:
    """Return the best available path/name for size detection and reporting."""
    return str(asset.get("originalPath") or asset.get("originalFileName") or "")


def asset_size(asset: Mapping[str, Any]) -> str:
    """Infer an icloudpd size from an Immich asset filename."""
    match = SIZE_SUFFIX_RE.search(asset_path(asset))
    return match.group(1).lower() if match else "original"


def is_video_asset(asset: Mapping[str, Any]) -> bool:
    """Return whether an Immich asset is a video."""
    return str(asset.get("type", "")).upper() == "VIDEO"


def reorder_video_stack(
    stack: Mapping[str, Any], primary_size: str
) -> tuple[List[str], str] | None:
    """Return the reordered IDs and reason, or None when the stack is skipped."""
    assets = stack.get("assets", [])
    if not isinstance(assets, list) or len(assets) < 2:
        return None
    if not all(isinstance(asset, dict) for asset in assets):
        return None
    if not all(is_video_asset(asset) for asset in assets):
        return None

    matching = [asset for asset in assets if asset_size(asset) == primary_size]
    if not matching:
        return None

    primary_id = matching[0].get("id")
    asset_ids = [asset.get("id") for asset in assets]
    if not primary_id or any(not asset_id for asset_id in asset_ids):
        return None

    ordered_ids = [primary_id] + [asset_id for asset_id in asset_ids if asset_id != primary_id]
    if ordered_ids == asset_ids:
        return None

    return ordered_ids, f"{primary_size} ({asset_path(matching[0])})"


def get_all_stacks(server_url: str, api_key: str) -> List[Dict[str, Any]]:
    response = requests.get(
        f"{server_url}/api/stacks", headers={"x-api-key": api_key}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def create_stack(server_url: str, api_key: str, asset_ids: List[str]) -> None:
    response = requests.post(
        f"{server_url}/api/stacks",
        headers={"x-api-key": api_key},
        json={"assetIds": asset_ids},
        timeout=30,
    )
    response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--server-url", required=True, metavar="URL", help="Immich server URL")
    parser.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help=f"Immich API key. Falls back to {API_KEY_ENV_VAR}.",
    )
    parser.add_argument(
        "--primary",
        choices=KNOWN_SIZES,
        default="original",
        help="Video size to make primary (default: original).",
    )
    parser.add_argument(
        "--library-id",
        default=None,
        metavar="ID",
        help="Only process stacks whose assets all belong to this library.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually reorder stacks. Without this flag, only reports changes.",
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
    skipped_mixed = 0
    for stack in stacks:
        assets = stack.get("assets", [])
        if not isinstance(assets, list) or len(assets) < 2:
            continue
        if not all(isinstance(asset, dict) and is_video_asset(asset) for asset in assets):
            if any(isinstance(asset, dict) and is_video_asset(asset) for asset in assets):
                skipped_mixed += 1
            continue
        if args.library_id and not all(
            asset.get("libraryId") == args.library_id for asset in assets
        ):
            continue
        reordered = reorder_video_stack(stack, args.primary)
        if reordered:
            candidates.append((stack, *reordered))

    print(f"Fetched {len(stacks)} stack(s) from Immich")
    print(f"Video stacks needing reordering: {len(candidates)}")
    if skipped_mixed:
        print(f"Mixed image/video stacks skipped: {skipped_mixed}")

    if not candidates:
        print("Nothing to do.")
        return

    for stack, ordered_ids, primary_description in candidates:
        print(
            f"  - stack {stack.get('id')}: primary -> {primary_description}; "
            f"asset order {ordered_ids}"
        )

    if not args.apply:
        print("\nDry run: no changes made. Re-run with --apply to reorder these stacks.")
        return

    changed = 0
    try:
        for _, ordered_ids, _ in candidates:
            create_stack(server_url, api_key, ordered_ids)
            changed += 1
    except requests.RequestException as error:
        print(f"Error: Failed after reordering {changed} stack(s): {error}", file=sys.stderr)
        sys.exit(1)

    print(f"\nReordered {changed} video stack(s).")


if __name__ == "__main__":
    main()
