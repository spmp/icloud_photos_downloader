"""Tests for the orphaned-stack cleanup script."""

import unittest
from unittest.mock import Mock, patch

from plugins.immich.scripts.dedupe_favorite_stacks import (
    API_KEY_ENV_VAR,
    _delete_stacks,
    _get_all_stacks,
    find_orphaned_stacks,
    find_unverifiable_orphans,
    resolve_api_key,
)


class TestFindOrphanedStacks(unittest.TestCase):
    """Test the pure orphan-detection logic."""

    def test_no_stacks(self):
        self.assertEqual(find_orphaned_stacks([]), [])

    def test_stack_with_assets_is_not_orphaned(self):
        stacks = [
            {"id": "stack-1", "primaryAssetId": "asset-1", "assets": [{"id": "asset-1"}, {"id": "asset-2"}]},
        ]
        self.assertEqual(find_orphaned_stacks(stacks), [])

    def test_stack_with_no_assets_is_orphaned(self):
        stacks = [
            {"id": "stack-1", "primaryAssetId": "asset-1", "assets": []},
        ]
        self.assertEqual(find_orphaned_stacks(stacks), stacks)

    def test_mixed_stacks_only_returns_orphans(self):
        healthy = {"id": "stack-1", "primaryAssetId": "asset-1", "assets": [{"id": "asset-1"}, {"id": "asset-2"}]}
        orphan = {"id": "stack-2", "primaryAssetId": "asset-3", "assets": []}
        result = find_orphaned_stacks([healthy, orphan])
        self.assertEqual(result, [orphan])

    def test_stack_with_single_remaining_asset_is_orphaned(self):
        # This is the realistic shape of the bug's leftover: the old primary
        # asset is never reassigned away (it was never in the new create()
        # call), so it's left alone in a stack that used to have more members.
        # Immich's create API requires >=2 assets, so a live 1-asset stack can
        # only be this kind of leftover, never something created on purpose.
        stacks = [
            {"id": "stack-1", "primaryAssetId": "asset-1", "assets": [{"id": "asset-1"}]},
        ]
        self.assertEqual(find_orphaned_stacks(stacks), stacks)

    def test_stack_with_two_remaining_assets_is_not_orphaned(self):
        stacks = [
            {"id": "stack-1", "primaryAssetId": "asset-1", "assets": [{"id": "asset-1"}, {"id": "asset-2"}]},
        ]
        self.assertEqual(find_orphaned_stacks(stacks), [])


class TestLibraryScoping(unittest.TestCase):
    """Test client-side library filtering, since Immich's stacks API has no
    server-side library filter (stacks are account-wide, not per-library)."""

    def test_no_library_id_returns_all_thin_stacks(self):
        stacks = [
            {"id": "stack-1", "primaryAssetId": "a1", "assets": [{"id": "a1", "libraryId": "lib-A"}]},
            {"id": "stack-2", "primaryAssetId": "a2", "assets": [{"id": "a2", "libraryId": "lib-B"}]},
        ]
        self.assertEqual(find_orphaned_stacks(stacks), stacks)

    def test_library_id_filters_to_matching_asset(self):
        matching = {"id": "stack-1", "primaryAssetId": "a1", "assets": [{"id": "a1", "libraryId": "lib-A"}]}
        other_library = {"id": "stack-2", "primaryAssetId": "a2", "assets": [{"id": "a2", "libraryId": "lib-B"}]}
        result = find_orphaned_stacks([matching, other_library], library_id="lib-A")
        self.assertEqual(result, [matching])

    def test_library_id_excludes_empty_stacks_from_deletion_list(self):
        empty = {"id": "stack-1", "primaryAssetId": "a1", "assets": []}
        result = find_orphaned_stacks([empty], library_id="lib-A")
        self.assertEqual(result, [])

    def test_find_unverifiable_orphans_empty_when_no_library_scope(self):
        empty = {"id": "stack-1", "primaryAssetId": "a1", "assets": []}
        self.assertEqual(find_unverifiable_orphans([empty], library_id=None), [])

    def test_find_unverifiable_orphans_surfaces_empty_stacks_when_scoped(self):
        empty = {"id": "stack-1", "primaryAssetId": "a1", "assets": []}
        healthy = {"id": "stack-2", "primaryAssetId": "a2", "assets": [{"id": "a2"}, {"id": "a3"}]}
        result = find_unverifiable_orphans([empty, healthy], library_id="lib-A")
        self.assertEqual(result, [empty])


class TestResolveApiKey(unittest.TestCase):
    """Test API key resolution: --api-key argument takes precedence over the env var."""

    def test_env_var_used_when_cli_value_missing(self):
        env = {API_KEY_ENV_VAR: "env-key"}
        self.assertEqual(resolve_api_key(None, env), "env-key")

    def test_none_when_neither_provided(self):
        self.assertIsNone(resolve_api_key(None, {}))

    def test_cli_value_wins_even_if_env_var_also_set(self):
        env = {API_KEY_ENV_VAR: "env-key"}
        self.assertEqual(resolve_api_key("cli-key", env), "cli-key")


class TestApiCalls(unittest.TestCase):
    """Test the thin API wrapper functions."""

    @patch("plugins.immich.scripts.dedupe_favorite_stacks.requests.get")
    def test_get_all_stacks(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [{"id": "stack-1", "primaryAssetId": "a", "assets": []}]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = _get_all_stacks("http://localhost:2283", "test-key")

        mock_get.assert_called_once_with(
            "http://localhost:2283/api/stacks",
            headers={"x-api-key": "test-key"},
            timeout=30,
        )
        self.assertEqual(result, [{"id": "stack-1", "primaryAssetId": "a", "assets": []}])

    @patch("plugins.immich.scripts.dedupe_favorite_stacks.requests.delete")
    def test_delete_stacks(self, mock_delete):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_delete.return_value = mock_response

        _delete_stacks("http://localhost:2283", "test-key", ["stack-1", "stack-2"])

        mock_delete.assert_called_once_with(
            "http://localhost:2283/api/stacks",
            headers={"x-api-key": "test-key"},
            json={"ids": ["stack-1", "stack-2"]},
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
