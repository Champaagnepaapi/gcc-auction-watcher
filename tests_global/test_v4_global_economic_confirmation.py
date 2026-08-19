from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
from v4_global_economic_confirmation import (
    ExternalAggregate,
    evaluate_card,
    fetch_poketrace_external,
    ppt_external,
    select_correlated_external,
)
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK, CommercialIdentity
from v4_global_ppt_confirmation import PptSnapshot, _match, reviewed_set_id

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
IDENTITY = CommercialIdentity(
    name="Mewtwo",
    set_name="151",
    number="183/165",
    language="ja",
    grader="PSA",
    grade="10",
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
        other = CommercialIdentity("Mewtwo", "VSTAR Universe", "183/165", "ja", "PSA", "10")
        self.assertIsNone(reviewed_set_id(other))

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
    def test_poketrace_reuses_existing_exact_gate(self, evidence_mock):
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
        self.assertEqual(args[1].set_name, "151")
        self.assertEqual(args[1].full_number, "183/165")
        self.assertEqual(args[1].language_code, "ja")


if __name__ == "__main__":
    unittest.main()
