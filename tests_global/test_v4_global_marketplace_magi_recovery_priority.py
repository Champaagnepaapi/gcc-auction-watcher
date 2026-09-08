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
                search = resolver._get(
                    "cards",
                    params={"name": "eq:test", "rarity": "eq:Ultra Rare"},
                )
                detail = resolver._get("cards/CARD-test")
            finally:
                resolver.close()

        self.assertEqual(reserved[0], 0)
        self.assertEqual(search[0], 200)
        self.assertEqual(detail[0], 200)
        self.assertEqual(resolver.requests_used, 4)
        self.assertEqual(resolver._nonpriority_requests_used, 2)
        self.assertEqual(resolver.reserved_breakdown, {"set_coordinate": 1})
        self.assertEqual(
            resolver.request_breakdown,
            {"sets_catalog": 1, "set_coordinate": 1, "card_search": 1, "card_detail": 1},
        )
        self.assertEqual(resolver.exhausted_breakdown, {})

    def test_measured_post_classic_live_shape_has_bounded_room_for_late_recovery(self):
        """Regression for the five BUDGET_EXHAUSTED rows seen at 36/36.

        The measured live shape had 27 broad calls plus nine exact-card calls,
        followed by two filtered-set attempts and three exact card searches that
        could each need one detail read. All of that fits below the new 48-call
        ceiling without changing any identity gate.
        """
        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=self._fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=48)
            try:
                for index in range(27):
                    self.assertEqual(resolver._get(f"sets/LIVE/{index}")[0], 200)

                # Current successful exact-card traffic: 5 searches / 4 details.
                for index in range(4):
                    self.assertEqual(
                        resolver._get(
                            "cards",
                            params={"name": f"eq:existing-{index}", "rarity": "eq:Ultra Rare"},
                        )[0],
                        200,
                    )
                    self.assertEqual(resolver._get(f"cards/CARD-existing-{index}")[0], 200)
                self.assertEqual(
                    resolver._get(
                        "cards",
                        params={"name": "eq:existing-search-only", "rarity": "eq:Ultra Rare"},
                    )[0],
                    200,
                )

                # The five previously exhausted request sites: two filtered-set
                # reads plus three exact searches, conservatively allowing one
                # exact detail read after every recovered search.
                self.assertEqual(
                    resolver._get("sets", params={"cardCount.official": "eq:62"})[0],
                    200,
                )
                self.assertEqual(
                    resolver._get("sets", params={"cardCount.official": "eq:63"})[0],
                    200,
                )
                for index in range(3):
                    self.assertEqual(
                        resolver._get(
                            "cards",
                            params={"name": f"eq:late-{index}", "rarity": "eq:Ultra Rare"},
                        )[0],
                        200,
                    )
                    self.assertEqual(resolver._get(f"cards/CARD-late-{index}")[0], 200)
            finally:
                resolver.close()

        self.assertEqual(resolver.requests_used, 44)
        self.assertEqual(resolver._card_identity_reserve, 18)
        self.assertEqual(resolver._nonpriority_request_cap, 30)
        self.assertEqual(resolver._nonpriority_requests_used, 29)
        self.assertEqual(resolver.reserved_breakdown, {})
        self.assertEqual(resolver.exhausted_breakdown, {})

    def test_production_broad_cap_is_independent_and_total_ceiling_remains_hard(self):
        with mock.patch.object(
            budget.retrieval_v3.TCGdexJapaneseProofResolver,
            "_get",
            new=self._fake_parent_get,
        ):
            resolver = budget.CachedRecoveryResolver(max_requests=48)
            try:
                # Exact proof may happen before broad traffic without shrinking
                # the independent 30-call broad allowance.
                for index in range(4):
                    self.assertEqual(
                        resolver._get(
                            "cards",
                            params={"name": f"eq:early-{index}", "rarity": "eq:Ultra Rare"},
                        )[0],
                        200,
                    )
                    self.assertEqual(resolver._get(f"cards/CARD-early-{index}")[0], 200)

                for index in range(30):
                    self.assertEqual(resolver._get(f"sets/SET/{index}")[0], 200)
                reserved = resolver._get("sets/SET/30")

                # The remaining exact-card reserve can still be consumed up to
                # the hard total ceiling, after which another exact request is
                # visibly exhausted rather than silently accepted.
                for index in range(5):
                    self.assertEqual(
                        resolver._get(
                            "cards",
                            params={"name": f"eq:late-{index}", "rarity": "eq:Ultra Rare"},
                        )[0],
                        200,
                    )
                    self.assertEqual(resolver._get(f"cards/CARD-late-{index}")[0], 200)
                exhausted = resolver._get(
                    "cards",
                    params={"name": "eq:overflow", "rarity": "eq:Ultra Rare"},
                )
            finally:
                resolver.close()

        self.assertEqual(resolver._card_identity_reserve, 18)
        self.assertEqual(resolver._nonpriority_request_cap, 30)
        self.assertEqual(resolver._nonpriority_requests_used, 30)
        self.assertEqual(reserved[0], 0)
        self.assertEqual(exhausted[0], 0)
        self.assertEqual(resolver.requests_used, 48)
        self.assertEqual(resolver.reserved_breakdown, {"set_coordinate": 1})
        self.assertEqual(
            resolver.request_breakdown,
            {"set_coordinate": 30, "card_search": 9, "card_detail": 9},
        )
        self.assertEqual(resolver.exhausted_breakdown, {"card_search": 1})

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
