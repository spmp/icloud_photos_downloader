#!/usr/bin/env python3
"""Remove orphaned Immich stacks left behind by the icloudpd Immich plugin's
repeated stacking calls (--immich-stack-media).

Background
----------
Immich's stack-merge endpoint (POST /api/stacks) only cleans up a previous
stack if that stack's *primary* asset is included in the new call: it looks
up existing stacks by primaryAssetId, deletes any it finds, and reassigns
all of their members (plus the new asset list) to a freshly created stack.
The icloudpd Immich plugin re-issues a stack-create call every time a photo
group is reprocessed (e.g. a second --immich-process-existing run, or a run
where a new size variant shows up). If that call settles on a different
primary than before, the *old* primary asset is never included in the new
asset list — so the old stack is never looked up, never merged, never
deleted. Every other member of the old stack gets reassigned to the new
stack, leaving the old stack containing exactly one asset: its own former
primary. Immich has an explicit safeguard against this exact situation
("0 or 1 asset would remain: dissolve the stack so it does not linger as a
single-asset stack") but it only runs on the asset-deletion path, not on
stack creation/merging — so this single-asset leftover is never cleaned up
on its own.

This is a standalone remediation script, not a plugin code change: run it
after an icloudpd/Immich sync (one-off, or on a schedule such as a cron job
chained after your icloudpd invocation) to catch and remove any leftover
single-asset stacks it creates.

Immich's web app queries live state, so it just shows that lone asset as a
normal favorite. Clients with a local sync cache (e.g. the mobile app) can
retain a stale record of that asset's previous stack membership from before
the reassignment, so the same favorited photo can appear twice there.

This script finds stacks with 0 or 1 live member assets via the Immich API
and deletes them — a stack that thin is never legitimate (the create API
itself requires at least 2 assets), so any that exist are leftovers from
this bug (or an equivalent one). Deleting a stack does not delete or
unfavorite its member asset(s); Immich sets their stackId back to null.
Run with --apply once you're happy with the dry-run report; without --apply
nothing is changed.

Scoping to a library
---------------------
Immich's stacks API is account-wide, not per-library: GET /api/stacks
returns every stack the API key's user owns, across all libraries, with no
server-side library filter. The 0-or-1-asset signal is invalid in any
library, so an account-wide run is safe on its own — but pass --library-id
if you'd rather restrict deletions to the library this plugin manages (each
stack's remaining asset carries its own libraryId, so this is filtered
client-side). Fully empty (0-asset) stacks have no asset to check the
library against, so with --library-id they're excluded from deletion and
listed separately for manual review instead.

Usage
-----
    # API key via argument
    python3 dedupe_favorite_stacks.py --server-url https://immich.example.com \\
        --api-key YOUR_API_KEY

    # API key via environment variable
    export IMMICH_API_KEY=YOUR_API_KEY
    python3 dedupe_favorite_stacks.py --server-url https://immich.example.com

    # Scope to a single library
    python3 dedupe_favorite_stacks.py --server-url https://immich.example.com \\
        --library-id YOUR_LIBRARY_ID

    # Apply the deletions (all forms above default to a dry-run report)
    python3 dedupe_favorite_stacks.py --server-url https://immich.example.com \\
        --api-key YOUR_API_KEY --apply
"""

import argparse
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

import requests

API_KEY_ENV_VAR = "IMMICH_API_KEY"


def _get_all_stacks(server_url: str, api_key: str) -> List[Dict[str, Any]]:
    """Fetch every stack owned by the API key's user.

    Args:
        server_url: Immich server base URL
        api_key: Immich API key

    Returns:
        List of stack dicts, each with 'id', 'primaryAssetId', and 'assets'

    Raises:
        requests.RequestException: If the API call fails
    """
    url = f"{server_url}/api/stacks"
    headers = {"x-api-key": api_key}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    stacks: List[Dict[str, Any]] = response.json()
    return stacks


def _delete_stacks(server_url: str, api_key: str, stack_ids: List[str]) -> None:
    """Delete stacks by ID.

    Args:
        server_url: Immich server base URL
        api_key: Immich API key
        stack_ids: List of stack IDs to delete

    Raises:
        requests.RequestException: If the API call fails
    """
    url = f"{server_url}/api/stacks"
    headers = {"x-api-key": api_key}
    body = {"ids": stack_ids}
    response = requests.delete(url, headers=headers, json=body, timeout=30)
    response.raise_for_status()


def find_orphaned_stacks(
    stacks: List[Dict[str, Any]], library_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Find stacks with 0 or 1 live member assets, optionally scoped to a library.

    Immich's own create API requires at least 2 assetIds to form a stack, so
    a stack that currently has fewer than 2 live members can only be a
    leftover from stack membership changing underneath it later (e.g. the
    re-stacking bug this script targets) — never a stack a user or the
    plugin created on purpose.

    Stacks aren't scoped by library server-side, so when library_id is given
    this filters client-side using each remaining asset's own libraryId.
    Fully empty (0-asset) stacks have no asset to check, so they're excluded
    from a scoped result — use find_unverifiable_orphans() to see those.

    Args:
        stacks: List of stack dicts from the Immich API
        library_id: If given, only return stacks whose sole remaining asset
            belongs to this library

    Returns:
        Subset of stacks with 0 or 1 live assets (matching library_id if given)
    """
    thin = [stack for stack in stacks if len(stack.get("assets", [])) <= 1]

    if library_id is None:
        return thin

    return [
        stack
        for stack in thin
        if stack.get("assets") and stack["assets"][0].get("libraryId") == library_id
    ]


def find_unverifiable_orphans(
    stacks: List[Dict[str, Any]], library_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Find fully-empty (0-asset) thin stacks that a library scope can't verify.

    These are still orphans by the same 0-or-1-asset rule, but with no
    member asset left to check against library_id, so they're surfaced
    separately for manual review rather than silently deleted or dropped.

    Args:
        stacks: List of stack dicts from the Immich API
        library_id: The library scope in effect, or None if unscoped

    Returns:
        Subset of stacks with zero live assets, only if library_id is set
    """
    if library_id is None:
        return []
    return [stack for stack in stacks if len(stack.get("assets", [])) == 0]


def resolve_api_key(cli_value: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    """Resolve the API key from the CLI argument or environment variable.

    The CLI argument takes precedence over the environment variable.

    Args:
        cli_value: The value of --api-key, or None if not provided
        env: Environment variables to check (os.environ in normal use)

    Returns:
        The resolved API key, or None if neither source provided one
    """
    return cli_value or env.get(API_KEY_ENV_VAR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server-url", required=True, metavar="URL", help="Immich server URL")
    parser.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help=f"Immich API key. Falls back to the {API_KEY_ENV_VAR} environment variable if not given.",
    )
    parser.add_argument(
        "--library-id",
        default=None,
        metavar="ID",
        help="Restrict deletions to stacks whose remaining asset belongs to this Immich "
        "library. Stacks aren't scoped by library server-side, so without this flag the "
        "scan covers every stack in the account.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the orphaned stacks. Without this flag, only reports what would be deleted.",
    )
    args = parser.parse_args()

    api_key = resolve_api_key(args.api_key, os.environ)
    if not api_key:
        parser.error(f"An API key is required: pass --api-key or set {API_KEY_ENV_VAR}")

    server_url = args.server_url.rstrip("/")

    try:
        stacks = _get_all_stacks(server_url, api_key)
    except requests.RequestException as e:
        print(f"Error: Failed to fetch stacks from Immich: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(stacks)} stack(s) from Immich")
    if args.library_id:
        print(f"Scoping to library {args.library_id}")

    orphaned = find_orphaned_stacks(stacks, args.library_id)
    unverifiable = find_unverifiable_orphans(stacks, args.library_id)

    if unverifiable:
        print(
            f"\n{len(unverifiable)} fully-empty stack(s) found but skipped: no remaining "
            "asset to check against --library-id. Review manually or rerun without "
            "--library-id to include them:"
        )
        for stack in unverifiable:
            print(f"  - stack {stack['id']} (primaryAssetId was {stack.get('primaryAssetId')})")

    if not orphaned:
        print("\nNo orphaned stacks found to delete. Nothing to do.")
        return

    print(f"\nFound {len(orphaned)} orphaned stack(s) (0 or 1 live assets):")
    for stack in orphaned:
        asset_ids = [a.get("id") for a in stack.get("assets", [])]
        print(f"  - stack {stack['id']}: {len(asset_ids)} asset(s) {asset_ids} (primaryAssetId {stack.get('primaryAssetId')})")

    if not args.apply:
        print(f"\nDry run: no changes made. Re-run with --apply to delete these {len(orphaned)} stack(s).")
        return

    orphaned_ids = [stack["id"] for stack in orphaned]
    try:
        _delete_stacks(server_url, api_key, orphaned_ids)
    except requests.RequestException as e:
        print(f"Error: Failed to delete orphaned stacks: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nDeleted {len(orphaned_ids)} orphaned stack(s).")
    print(
        "If duplicates are still visible in the mobile app, force a full resync "
        "(log out and back in, or clear local app data) so it drops its stale cache."
    )


if __name__ == "__main__":
    main()
