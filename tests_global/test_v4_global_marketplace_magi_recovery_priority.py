from __future__ import annotations

import unittest
from unittest import mock

import v4_global_marketplace_magi_recovery_budget as budget


class MagiRecoveryPriorityTests(unittest.TestCase):
    def test_last_two_calls_are_reserved_for_exact_card_search_and_detail(self):
        def fake_parent_get(resolver, path, *, params=None):
            if resolver.requests_used >= resolver.max_requests:
                return 0, {"error": "budget_exhausted"}
            resolver.requests_used += 1
            if path == "cards":
                return 200, [{"id": "SM11b-063"}]
            if path == "cards/SM11b-063":
                return 200, {"id": "SM11b-063"}
            return 200, []

        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=4)
            try:
                self.assertEqual(resolver._get("sets"), (200, []))
                self.assertEqual(resolver._get("sets/SV2a/151"), (200, []))
                reserved = resolver._get("sets/SV2a/152")
                search = resolver._get(
                    "cards",
                    params={"name": "eq:test", "rarity": "eq:Ultra Rare"},
                )
                detail = resolver._get("cards/SM11b-063")
            finally:
                resolver.close()

        self.assertEqual(reserved[0], 0)
        self.assertEqual(search[0], 200)
        self.assertEqual(detail[0], 200)
        self.assertEqual(resolver.requests_used, 4)
        self.assertEqual(resolver.reserved_breakdown, {"set_coordinate": 1})
        self.assertEqual(
            resolver.request_breakdown,
            {"sets_catalog": 1, "set_coordinate": 1, "card_search": 1, "card_detail": 1},
        )
        self.assertEqual(resolver.exhausted_breakdown, {})

    def test_production_budget_reserves_four_exact_search_detail_pairs(self):
        def fake_parent_get(resolver, path, *, params=None):
            if resolver.requests_used >= resolver.max_requests:
                return 0, {"error": "budget_exhausted"}
            resolver.requests_used += 1
            if path == "cards":
                name = str((params or {}).get("name") or "eq:test")
                suffix = name.rsplit(":", 1)[-1]
                return 200, [{"id": f"CARD-{suffix}"}]
            if path.startswith("cards/"):
                return 200, {"id": path.split("/", 1)[1]}
            return 200, []

        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=36)
            try:
                for index in range(28):
                    self.assertEqual(resolver._get(f"sets/SET/{index}")[0], 200)
                reserved = resolver._get("sets/SET/28")
                for index in range(4):
                    search = resolver._get(
                        "cards",
                        params={
                            "name": f"eq:name-{index}",
                            "rarity": "eq:Ultra Rare",
                        },
                    )
                    detail = resolver._get(f"cards/CARD-name-{index}")
                    self.assertEqual(search[0], 200)
                    self.assertEqual(detail[0], 200)
            finally:
                resolver.close()

        self.assertEqual(resolver._card_identity_reserve, 8)
        self.assertEqual(reserved[0], 0)
        self.assertEqual(resolver.requests_used, 36)
        self.assertEqual(resolver.reserved_breakdown, {"set_coordinate": 1})
        self.assertEqual(
            resolver.request_breakdown,
            {"set_coordinate": 28, "card_search": 4, "card_detail": 4},
        )
        self.assertEqual(resolver.exhausted_breakdown, {})

    def test_tiny_test_budget_keeps_existing_semantics(self):
        def fake_parent_get(resolver, path, *, params=None):
            if resolver.requests_used >= resolver.max_requests:
                return 0, {"error": "budget_exhausted"}
            resolver.requests_used += 1
            return 200, []

        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=1)
            try:
                self.assertEqual(resolver._get("sets"), (200, []))
                self.assertEqual(resolver._get("cards/test")[0], 0)
            finally:
                resolver.close()

        self.assertEqual(resolver.requests_used, 1)
        self.assertEqual(resolver.reserved_breakdown, {})
        self.assertEqual(resolver.exhausted_breakdown, {"card_detail": 1})


if __name__ == "__main__":
    unittest.main()
