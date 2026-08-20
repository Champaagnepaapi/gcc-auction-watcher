from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_economic_confirmation as confirmation
from v4_global_economic_confirmation import (
    ExternalAggregate,
    evaluate_card,
    fetch_poketrace_external,
    install_global_external_market_stack,
    ppt_external,
    resolve_global_canonical,
    select_correlated_external,
)
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK, CommercialIdentity
from v4_global_ppt_confirmation import (
    PptSnapshot,
    _match,
    _match_canonical,
    reviewed_set_id,
)

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
IDENTITY = CommercialIdentity(
    name="Mewtwo",
    set_name="151",
    number="183/165",
    language="ja",
    grader="PSA",
    grade="10",
)
DYNAMIC_IDENTITY = CommercialIdentity(
    name="Raikou",
    set_name="VSTAR Universe",
    number="218/172",
    language="ja",
    grader="PSA",
    grade="10",
    finish="V",
    variant="Special Art Rare",
)
DYNAMIC_CANONICAL = multimarket.CanonicalCard(
    status="EXACT",
    card_id="s12a-218",
    set_id="s12a",
    set_name="VSTAR Universe",
    local_id="218",
    full_number="218/172",
    name="Raikou",
    language_code="ja",
    reason="TEST_EXACT",
)


def card(*, fair=100.0, offer=60.0, evidence=FIXED_ASK, all_in=True):
    return {
        "identity": {
            "name": IDENTITY.name,
            "set_name": IDENTITY.set_name,
            "number": IDENTITY.number,
            "language": IDENTITY.language,
            "grader": IDENTITY.grader,
            "grade": IDENTITY.grade,
            "edition": IDENTITY.edition,
            "finish": IDENTITY.finish,
            "variant": IDENTITY.variant,
        },
        "fair_value_eur": fair,
        "offers": [
            {
                "market": "fanatics",
                "evidence_type": evidence,
                "all_in_eur": offer if all_in else None,
                "raw_eur": offer,
                "source_url": "https://example.invalid/card",
            }
        ],
    }


class PptIdentityTests(unittest.TestCase):
    def test_reviewed_mapping_is_exact_and_small(self):
        self.assertEqual(reviewed_set_id(IDENTITY), "23599")
        self.assertIsNone(reviewed_set_id(DYNAMIC_IDENTITY))

    def test_exact_provider_set_number_matches(self):
        status, row = _match(
            IDENTITY,
            [{"setId": "23599", "cardNumber": "183", "language": "japanese", "tcgPlayerId": 1}],
            "23599",
        )
        self.assertEqual(status, "EXACT")
        self.assertIsNotNone(row)

    def test_explicit_wrong_language_is_rejected(self):
        status, row = _match(
            IDENTITY,
            [{"setId": "23599", "cardNumber": "183", "language": "english"}],
            "23599",
        )
        self.assertEqual(status, "CLEAN_NO_MATCH")
        self.assertIsNone(row)

    def test_sensitive_variant_requires_provider_claim(self):
        identity = CommercialIdentity(
            "Pikachu", "151", "025/165", "ja", "PSA", "10", variant="Master Ball Reverse"
        )
        status, _ = _match(
            identity,
            [{"setId": "23599", "cardNumber": "025", "language": "japanese", "name": "Pikachu"}],
            "23599",
        )
        self.assertEqual(status, "MICROVARIANT_UNPROVEN")

    def test_generic_external_catalog_id_is_exact_coordinate(self):
        status, row, proof = _match_canonical(
            DYNAMIC_IDENTITY,
            DYNAMIC_CANONICAL,
            [{
                "externalCatalogId": "s12a-218",
                "setId": "provider-777",
                "setName": "provider wording can differ",
                "cardNumber": "218",
                "language": "japanese",
                "name": "Raikou",
                "tcgPlayerId": 77,
            }],
        )
        self.assertEqual(status, "EXACT")
        self.assertIsNotNone(row)
        self.assertEqual(proof, "TCGDEX_EXTERNAL_CATALOG_ID")

    def test_present_conflicting_external_catalog_id_cannot_fallback(self):
        status, row, _ = _match_canonical(
            DYNAMIC_IDENTITY,
            DYNAMIC_CANONICAL,
            [{
                "externalCatalogId": "wrong-card-id",
                "setName": "VSTAR Universe",
                "cardNumber": "218",
                "language": "japanese",
                "name": "Raikou",
            }],
        )
        self.assertEqual(status, "CLEAN_NO_MATCH")
        self.assertIsNone(row)

    def test_exact_set_name_number_fallback_only_when_catalog_id_absent(self):
        status, row, proof = _match_canonical(
            DYNAMIC_IDENTITY,
            DYNAMIC_CANONICAL,
            [{
                "setId": "provider-777",
                "setName": "VSTAR Universe",
                "cardNumber": "218",
                "language": "japanese",
                "name": "Raikou",
            }],
        )
        self.assertEqual(status, "EXACT")
        self.assertIsNotNone(row)
        self.assertEqual(proof, "TCGDEX_SET_NAME_NUMBER_FALLBACK")

    def test_multiple_distinct_catalog_coordinate_rows_are_ambiguous(self):
        rows = [
            {
                "externalCatalogId": "s12a-218",
                "setId": "provider-777",
                "cardNumber": "218",
                "language": "japanese",
                "tcgPlayerId": 1,
            },
            {
                "externalCatalogId": "s12a-218",
                "setId": "provider-778",
                "cardNumber": "218",
                "language": "japanese",
                "tcgPlayerId": 2,
            },
        ]
        status, row, proof = _match_canonical(DYNAMIC_IDENTITY, DYNAMIC_CANONICAL, rows)
        self.assertEqual(status, "AMBIGUOUS")
        self.assertIsNone(row)
        self.assertEqual(proof, "TCGDEX_EXTERNAL_CATALOG_ID")

    def test_dynamic_coordinate_still_requires_sensitive_microvariant(self):
        identity = CommercialIdentity(
            "Raikou",
            "VSTAR Universe",
            "218/172",
            "ja",
            "PSA",
            "10",
            variant="Master Ball Reverse",
        )
        status, row, _ = _match_canonical(
            identity,
            DYNAMIC_CANONICAL,
            [{
                "externalCatalogId": "s12a-218",
                "cardNumber": "218",
                "language": "japanese",
                "name": "Raikou",
            }],
        )
        self.assertEqual(status, "MICROVARIANT_UNPROVEN")
        self.assertIsNone(row)


class ConfirmationTests(unittest.TestCase):
    def strong_ppt(self, value=95.0):
        return ExternalAggregate(
            "PokemonPriceTracker",
            "MATCHED",
            value,
            20,
            NOW - timedelta(days=3),
            "STRONG",
        )

    def strong_pt(self, value=96.0):
        return ExternalAggregate(
            "PokeTrace/eBay SOLD",
            "MATCHED",
            value,
            12,
            None,
            watcher.EVIDENCE_STRONG,
        )

    def test_global_external_stack_reuses_production_order_idempotently(self):
        names = [
            "install_v4_tcgdex_exact_coordinate_recovery",
            "install_v4_tcgdex_run1054_set_aliases",
            "install_v4_tcgdex_japanese_set_aliases",
            "install_v4_tcgdex_generalized_coordinate_recovery",
            "install_v4_tcgdex_two_of_three_backport",
            "install_v4_tcgdex_unique_coordinate_fallback",
            "install_v4_tcgdex_source_pinned_finish",
            "install_v4_poketrace_market_retrieval",
            "install_multimarket_safety_hardening",
        ]
        calls = []
        patchers = [
            mock.patch.object(
                confirmation,
                name,
                side_effect=(lambda name=name: calls.append(name)),
            )
            for name in names
        ]
        old_installed = confirmation._GLOBAL_EXTERNAL_STACK_INSTALLED
        confirmation._GLOBAL_EXTERNAL_STACK_INSTALLED = False
        for patcher in patchers:
            patcher.start()
        try:
            install_global_external_market_stack()
            install_global_external_market_stack()
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
            confirmation._GLOBAL_EXTERNAL_STACK_INSTALLED = old_installed
        self.assertEqual(calls, names)

    def test_recent_ppt_snapshot_becomes_strong_external(self):
        external = ppt_external(
            PptSnapshot("MATCHED", 95.0, 10, NOW - timedelta(days=5)),
            now=NOW,
        )
        self.assertTrue(external.usable_center)
        self.assertEqual(external.evidence_strength, "STRONG")

    def test_stale_ppt_does_not_confirm(self):
        external = ppt_external(
            PptSnapshot("MATCHED", 95.0, 10, NOW - timedelta(days=120)),
            now=NOW,
        )
        self.assertFalse(external.usable_center)
        self.assertEqual(external.status, "STALE_OR_UNDATED")

    def test_ppt_and_poketrace_count_once_ppt_primary(self):
        selected, note = select_correlated_external(self.strong_ppt(95), self.strong_pt(97))
        self.assertIsNotNone(selected)
        self.assertEqual(selected.provider, "PokemonPriceTracker")
        self.assertIn("CORRELATED", note)

    def test_correlated_family_material_conflict_blocks(self):
        selected, note = select_correlated_external(self.strong_ppt(70), self.strong_pt(110))
        self.assertIsNone(selected)
        self.assertTrue(note.startswith("CORRELATED_PROVIDER_CONFLICT"))

    def test_confirmed_edge_uses_lower_fair_value(self):
        decision = evaluate_card(
            card(fair=100, offer=60),
            ppt=self.strong_ppt(90),
            poketrace=self.strong_pt(92),
            min_discount=30,
        )
        self.assertEqual(decision.status, "MULTIMARKET_CONFIRMED")
        self.assertTrue(decision.would_notify)
        self.assertEqual(decision.confirmed_fair_eur, 90.0)
        self.assertAlmostEqual(decision.discount_pct, 33.3, places=1)

    def test_external_disagreement_with_gcc_blocks(self):
        decision = evaluate_card(
            card(fair=100, offer=50),
            ppt=self.strong_ppt(75),
            poketrace=ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.status, "MARKET_CONFLICT_BLOCKED")
        self.assertFalse(decision.would_notify)

    def test_no_external_confirmation_never_notifies(self):
        unavailable = ExternalAggregate("PokemonPriceTracker", "CLEAN_NO_MATCH")
        decision = evaluate_card(
            card(fair=100, offer=40),
            ppt=unavailable,
            poketrace=ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.status, "NO_EXTERNAL_CONFIRMATION")
        self.assertFalse(decision.would_notify)

    def test_active_auction_is_never_actionable(self):
        decision = evaluate_card(
            card(fair=100, offer=40, evidence=ACTIVE_AUCTION),
            ppt=self.strong_ppt(),
            poketrace=self.strong_pt(),
        )
        self.assertEqual(decision.status, "NO_ACTIONABLE_ALL_IN_OFFER")
        self.assertFalse(decision.would_notify)

    def test_unknown_all_in_is_never_actionable(self):
        decision = evaluate_card(
            card(fair=100, offer=40, all_in=False),
            ppt=self.strong_ppt(),
            poketrace=self.strong_pt(),
        )
        self.assertEqual(decision.status, "NO_ACTIONABLE_ALL_IN_OFFER")

    @mock.patch("v4_global_economic_confirmation.multimarket._poketrace_evidence")
    @mock.patch("v4_global_economic_confirmation.multimarket.resolve_tcgdex_card")
    def test_poketrace_reuses_real_tcgdex_exact_gate(self, resolve_mock, evidence_mock):
        canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="sv2a-183",
            set_id="sv2a",
            set_name="151",
            local_id="183",
            full_number="183/165",
            name="Mewtwo",
            language_code="ja",
            reason="TEST",
        )
        resolve_mock.return_value = canonical
        evidence_mock.return_value = SimpleNamespace(
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            estimate=SimpleNamespace(central=96.0, exact_grade_count=8),
            note="exact",
        )
        result = fetch_poketrace_external(
            IDENTITY,
            budget=multimarket.RequestBudget(),
            now=NOW,
        )
        self.assertEqual(result.status, "MATCHED")
        self.assertEqual(result.fair_eur, 96.0)
        self.assertEqual(result.sold_count, 8)
        args = evidence_mock.call_args.args
        self.assertEqual(args[0].card_set, "151")
        self.assertEqual(args[0].card_number, "183/165")
        self.assertEqual(args[0].language, "Japanese")
        self.assertEqual(args[1].card_id, "sv2a-183")
        self.assertEqual(args[1].set_id, "sv2a")
        self.assertEqual(args[1].full_number, "183/165")
        self.assertEqual(args[1].language_code, "ja")

    @mock.patch("v4_global_economic_confirmation.multimarket._poketrace_evidence")
    @mock.patch("v4_global_economic_confirmation.multimarket.resolve_tcgdex_card")
    def test_poketrace_never_runs_when_tcgdex_is_unresolved(self, resolve_mock, evidence_mock):
        resolve_mock.return_value = multimarket.CanonicalCard(
            "AMBIGUOUS", reason="multiple exact macro candidates"
        )
        result = fetch_poketrace_external(
            IDENTITY,
            budget=multimarket.RequestBudget(),
            now=NOW,
        )
        self.assertEqual(result.status, "TCGDEX_AMBIGUOUS")
        evidence_mock.assert_not_called()

    @mock.patch("v4_global_economic_confirmation.multimarket.resolve_tcgdex_card")
    def test_global_canonical_language_conflict_fails_closed(self, resolve_mock):
        resolve_mock.return_value = multimarket.CanonicalCard(
            status="EXACT",
            card_id="sv2a-183",
            set_id="sv2a",
            set_name="151",
            local_id="183",
            full_number="183/165",
            name="Mewtwo",
            language_code="en",
        )
        _, canonical = resolve_global_canonical(IDENTITY)
        self.assertEqual(canonical.status, "AMBIGUOUS")
        self.assertEqual(canonical.reason, "GLOBAL_TCGDEX_LANGUAGE_CONFLICT")


if __name__ == "__main__":
    unittest.main()
