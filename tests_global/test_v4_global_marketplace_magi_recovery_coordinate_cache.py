from __future__ import annotations

import unittest
from unittest import mock

import v4_global_marketplace_magi_recovery_budget as budget


class MagiRecoveryCoordinateCacheTests(unittest.TestCase):
    def test_clean_200_set_coordinate_is_reused_without_new_budget(self):
        calls = []

        def parent_get(resolver, path, *, params=None):
            calls.append((path, params))
            resolver.requests_used += 1
            return 200, {"id": "SM-A-071"}

        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=5)
            try:
                first = resolver._get("sets/SM-A/071")
                second = resolver._get("sets/SM-A/071")
            finally:
                resolver.close()

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(resolver.requests_used, 1)
        self.assertEqual(resolver.request_breakdown["set_coordinate"], 1)
        self.assertEqual(resolver.cache_hits["set_coordinate"], 1)

    def test_clean_404_set_coordinate_is_reused_but_transient_is_not(self):
        calls = []
        statuses = [404, -1, -1]

        def parent_get(resolver, path, *, params=None):
            calls.append(path)
            resolver.requests_used += 1
            status = statuses.pop(0)
            return status, {}

        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=5)
            try:
                self.assertEqual(resolver._get("sets/SM-A/071")[0], 404)
                self.assertEqual(resolver._get("sets/SM-A/071")[0], 404)
                self.assertEqual(resolver._get("sets/SM-B/071")[0], -1)
                self.assertEqual(resolver._get("sets/SM-B/071")[0], -1)
            finally:
                resolver.close()

        self.assertEqual(calls.count("sets/SM-A/071"), 1)
        self.assertEqual(calls.count("sets/SM-B/071"), 2)
        self.assertEqual(resolver.cache_hits["set_coordinate"], 1)


if __name__ == "__main__":
    unittest.main()
