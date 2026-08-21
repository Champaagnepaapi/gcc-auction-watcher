from __future__ import annotations

import unittest
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_marketplace_identity_dimension_hardening as dimensions
import v4_global_marketplace_poketrace_recall as recall
import v4_global_marketplace_tcgdex_source_alias_recovery as source_recovery
from v4_global_market_core import CommercialIdentity
import v4_poketrace_market_retrieval as retrieval
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as aliases


class GlobalMarketplaceGapRecoveryV2Tests(unittest.TestCase):
    @staticmethod
    def _alias(label: str) -> generalized.ExactSetAlias:
        matches = [alias for alias in aliases._ALIASES if alias.listing_set == label]
        if len(matches) != 1:
            raise AssertionError(f"expected one alias for {label!r}, got {len(matches)}")
        return matches[0]

    def test_new_source_pinned_set_aliases_match_only_exact_denominators(self):
        expected = {
            "Mega Symphonia": ("M1S", 63, "87/63"),
            "Mega Brave": ("M1L", 63, "64/63"),
            "Super Electric Breaker": ("SV8", 106, "112/106"),
        }
        for label, (set_id, count, reference) in expected.items():
            with self.subTest(label=label):
                alias = self._alias(label)
                self.assertEqual(alias.tcgdex_set_id, set_id)
                self.assertEqual(alias.tcgdex_official_count, count)
                self.assertTrue(alias.require_numeric_denominator)
                self.assertTrue(
                    generalized._validate_reference_for_alias(reference, alias)
                )
                left, right = reference.split("/", 1)
                self.assertFalse(
                    generalized._validate_reference_for_alias(
                        f"{left}/{int(right) + 1}", alias
                    )
                )

    def test_umbreon_gold_star_gap_is_still_not_fabricated(self):
        self.assertNotIn(
            "25th Anniversary Collection - Promo",
            {alias.listing_set for alias in aliases._ALIASES},
        )

    def test_source_alias_can_recover_measured_ambiguous_coordinate(self):
        lot = watcher.Lot(
            url="https://example.invalid/gardevoir",
            title="Mega Gardevoir Ex",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number="87/63",
            card_set="Mega Symphonia",
            language="Japanese",
        )
        original = multimarket.CanonicalCard(
            "AMBIGUOUS", reason="unique-coordinate denominator collision"
        )
        recovered = multimarket.CanonicalCard(
            "EXACT",
            card_id="M1S-087",
            set_id="M1S",
            set_name="Mega Symphonia",
            local_id="087",
            full_number="87/63",
            name="Mega Gardevoir Ex",
            language_code="ja",
            variants={"normal": False, "holo": True, "reverse": False},
            reason="TCGDEX_SOURCE_PINNED_SET_RECONCILED",
        )
        multimarket._DIAGNOSTICS = multimarket.MultiMarketDiagnostics()
        multimarket._DIAGNOSTICS.tcgdex_ambiguous = 1
        with mock.patch.object(
            source_recovery.reconciliation,
            "_recover_from_immutable_source",
            return_value=recovered,
        ) as source:
            result = source_recovery.recover_reviewed_source_alias(lot, original)

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.set_id, "M1S")
        self.assertEqual(result.reason, "TCGDEX_GLOBAL_SOURCE_ALIAS_RECOVERED")
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_ambiguous, 0)
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_exact, 1)
        source.assert_called_once()

    def test_gcc_attribute_mechanic_is_not_treated_as_finish(self):
        base = CommercialIdentity(
            name="Umbreon Ex",
            set_name="Terastal Fest Ex",
            number="217/187",
            language="ja",
            grader="PSA",
            grade="10",
            edition="Unlimited",
            finish="Ex",
            variant="Full Art | Special Illustration Rare",
        )
        with mock.patch.object(
            dimensions, "_ORIGINAL_GCC_IDENTITY", mock.Mock(return_value=base)
        ):
            result = dimensions.gcc_identity_from_row_semantic({})
        assert result is not None
        self.assertEqual(result.finish, "")
        self.assertEqual(result.name, "Umbreon Ex")

    def test_real_finish_is_canonicalized_and_kept(self):
        base = CommercialIdentity(
            name="Example",
            set_name="Example Set",
            number="1/100",
            language="en",
            grader="PSA",
            grade="10",
            finish="Holofoil",
        )
        with mock.patch.object(
            dimensions, "_ORIGINAL_GCC_IDENTITY", mock.Mock(return_value=base)
        ):
            result = dimensions.gcc_identity_from_row_semantic({})
        assert result is not None
        self.assertEqual(result.finish, "holo")

    def test_zero_candidate_primary_uses_bounded_contextual_recall(self):
        context = retrieval.PokeTraceRetrievalContext(
            search_name="Team Rocket's Meowth",
            card_number="109/098",
            game="pokemon-japanese",
            language_code="ja",
        )
        candidate = {
            "id": "pt-meowth",
            "name": "Team Rocket's Meowth (Japanese)",
            "cardNumber": "109/098",
        }
        fallback_calls = []

        def fallback(_budget, _url, *, params=None):
            fallback_calls.append(dict(params or {}))
            return 200, {"data": [candidate]}, {}

        token = retrieval._ACTIVE_CONTEXT.set(context)
        try:
            with mock.patch.object(
                recall, "_ORIGINAL_GET", mock.Mock(return_value=(200, {"data": []}, {}))
            ), mock.patch.object(
                retrieval, "_ORIGINAL_PACED_GET", side_effect=fallback
            ), mock.patch.object(
                retrieval, "_diagnostics_enabled", return_value=False
            ):
                response = recall._global_recall_paced_get(
                    multimarket.RequestBudget(),
                    f"{multimarket.POKETRACE_BASE_URL}/cards",
                    params={
                        "search": context.search_name,
                        "card_number": context.card_number,
                        "game": context.game,
                        "market": "US",
                        "limit": 20,
                        "product_type": "single",
                    },
                )
        finally:
            retrieval._ACTIVE_CONTEXT.reset(token)

        self.assertEqual(multimarket._extract_list_payload(response[1]), [candidate])
        self.assertEqual(len(fallback_calls), 1)
        self.assertEqual(
            fallback_calls[0]["search"],
            "Team Rocket's Meowth 109/098",
        )
        self.assertEqual(fallback_calls[0]["game"], "pokemon-japanese")
        self.assertNotIn("card_number", fallback_calls[0])

    def test_nonempty_primary_does_not_spend_recall_request(self):
        context = retrieval.PokeTraceRetrievalContext(
            search_name="Lapras",
            card_number="177/172",
            game="pokemon-japanese",
            language_code="ja",
        )
        candidate = {"id": "pt-lapras"}
        token = retrieval._ACTIVE_CONTEXT.set(context)
        try:
            with mock.patch.object(
                recall,
                "_ORIGINAL_GET",
                mock.Mock(return_value=(200, {"data": [candidate]}, {})),
            ), mock.patch.object(
                retrieval,
                "_ORIGINAL_PACED_GET",
                side_effect=AssertionError("no recall expected"),
            ):
                response = recall._global_recall_paced_get(
                    multimarket.RequestBudget(),
                    f"{multimarket.POKETRACE_BASE_URL}/cards",
                    params={"search": "Lapras"},
                )
        finally:
            retrieval._ACTIVE_CONTEXT.reset(token)
        self.assertEqual(multimarket._extract_list_payload(response[1]), [candidate])


if __name__ == "__main__":
    unittest.main()
