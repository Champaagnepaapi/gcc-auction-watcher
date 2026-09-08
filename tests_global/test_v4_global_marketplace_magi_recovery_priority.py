from __future__ import annotations

import unittest
from unittest import mock

import v4_global_marketplace_magi_recovery_budget as budget


class MagiRecoveryPriorityTests(unittest.TestCase):
    @staticmethod
    def _fake_parent_get(resolver, path, *, params=None):
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

    def test_last_two_calls_are_reserved_for_exact_card_search_and_detail(self):
        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=self._fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=4)
            try:
                self.assertEqual(resolver._get("sets"), (200, []))
                self.assertEqual(resolver._get("sets/SV2a/151"), (200, []))
                reserved = resolver._get("sets/SV2a/152")
                search = resolver._get("cards", params={"name": "eq:test", "rarity": "eq:Ultra Rare"})
                detail = resolver._get("cards/CARD-test")
            finally:
                resolver.close()
        self.assertEqual(reserved[0], 0)
        self.assertEqual(search[0], 200)
        self.assertEqual(detail[0], 200)
        self.assertEqual(resolver.requests_used, 4)
        self.assertEqual(resolver._nonpriority_requests_used, 2)
        self.assertEqual(resolver.reserved_breakdown, {"set_coordinate": 1})
        self.assertEqual(resolver.exhausted_breakdown, {})

    def test_measured_live_shape_releases_one_final_broad_call_and_keeps_two_exact_slots(self):
        """Regression for 033e live: 13 exact + 33 broad left one BUDGET row."""
        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=self._fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=49)
            try:
                for index in range(33):
                    self.assertEqual(resolver._get(f"sets/LIVE/{index}")[0], 200)
                for index in range(6):
                    self.assertEqual(resolver._get("cards", params={"name": f"eq:existing-{index}"})[0], 200)
                    self.assertEqual(resolver._get(f"cards/CARD-existing-{index}")[0], 200)
                self.assertEqual(resolver._get("cards", params={"name": "eq:search-only"})[0], 200)

                # The one row reserved on the 48-call live now gets one bounded
                # broad slot, while two exact-card calls still fit afterwards.
                self.assertEqual(resolver._get("sets/LATE/final")[0], 200)
                self.assertEqual(resolver._get("cards", params={"name": "eq:late"})[0], 200)
                self.assertEqual(resolver._get("cards/CARD-late")[0], 200)
                reserved = resolver._get("sets/LATE/overflow")
            finally:
                resolver.close()

        self.assertEqual(resolver.requests_used, 49)
        self.assertEqual(resolver._card_identity_reserve, 15)
        self.assertEqual(resolver._nonpriority_request_cap, 34)
        self.assertEqual(resolver._nonpriority_requests_used, 34)
        self.assertEqual(reserved[0], 0)
        self.assertEqual(resolver.reserved_breakdown, {"set_coordinate": 1})
        self.assertEqual(resolver.exhausted_breakdown, {})

    def test_production_broad_cap_and_total_ceiling_remain_hard(self):
        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=self._fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=49)
            try:
                for index in range(34):
                    self.assertEqual(resolver._get(f"sets/SET/{index}")[0], 200)
                reserved = resolver._get("sets/SET/34")
                for index in range(7):
                    self.assertEqual(resolver._get("cards", params={"name": f"eq:late-{index}"})[0], 200)
                    self.assertEqual(resolver._get(f"cards/CARD-late-{index}")[0], 200)
                self.assertEqual(resolver._get("cards", params={"name": "eq:last"})[0], 200)
                exhausted = resolver._get("cards/CARD-last")
            finally:
                resolver.close()

        self.assertEqual(resolver._card_identity_reserve, 15)
        self.assertEqual(resolver._nonpriority_request_cap, 34)
        self.assertEqual(resolver._nonpriority_requests_used, 34)
        self.assertEqual(reserved[0], 0)
        self.assertEqual(resolver.requests_used, 49)
        self.assertEqual(exhausted[0], 0)
        self.assertEqual(resolver.exhausted_breakdown, {"card_detail": 1})

    def test_tiny_test_budget_keeps_existing_semantics(self):
        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=self._fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=1)
            try:
                self.assertEqual(resolver._get("sets"), (200, []))
                self.assertEqual(resolver._get("cards/test")[0], 0)
            finally:
                resolver.close()
        self.assertEqual(resolver.requests_used, 1)
        self.assertEqual(resolver._nonpriority_requests_used, 1)
        self.assertEqual(resolver.reserved_breakdown, {})
        self.assertEqual(resolver.exhausted_breakdown, {"card_detail": 1})


if __name__ == "__main__":
    unittest.main()
