from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import v4_global_marketplace_discovery as discovery
import v4_global_marketplace_hardening as hardening
import v4_global_marketplace_notify as marketplace
from v4_global_market_core import FIXED_ASK, CommercialIdentity


NOW = datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)


def _gcc_row(title="PSA 9 Dark Ampharos", language="Japanese", grade="9"):
    return {
        "id": "gcc-1",
        "status": "ON_SALE",
        "sellingTypeGroup": "FIXED_PRICE",
        "priceInCents": 5000,
        "item": {
            "title": title,
            "gradingCompany": "PSA",
            "grade": grade,
            "collectible": {
                "category": "Pokemon",
                "type": "Cards",
                "language": language,
                "character": {"englishName": "Trainer"},
                "set": "Rocket Gang Strikes Back",
                "reference": "39/84",
                "yearOfDistribution": 2004,
                "edition": "1st Edition",
                "attribute": "Dark",
            },
        },
    }


class MarketplaceHardeningTests(unittest.TestCase):
    def setUp(self):
        hardening.install_marketplace_first_hardening()

    def test_gcc_title_name_overrides_generic_character_without_relaxing_coordinate(self):
        identity = hardening.gcc_identity_from_row_hardened(_gcc_row())
        self.assertIsNotNone(identity)
        self.assertEqual(identity.name, "Dark Ampharos")
        self.assertEqual(identity.set_name, "Rocket Gang Strikes Back")
        self.assertEqual(identity.number, "39/84")
        self.assertEqual(identity.language, "ja")
        self.assertEqual(identity.grade, "9")

    def test_gcc_listing_keeps_vault_basis_and_never_calls_ask_sold(self):
        listing = hardening.gcc_listing_from_row_hardened(_gcc_row(), observed_at=NOW)
        self.assertIsNotNone(listing)
        self.assertEqual(listing.identity.name, "Dark Ampharos")
        self.assertEqual(listing.evidence_type, FIXED_ASK)
        self.assertEqual(listing.buyer_fee_rate, 0.0)
        self.assertIn("Vault acquisition basis", listing.note)
        self.assertIn("not SOLD", listing.note)

    def test_ppt_language_gate_accepts_exact_english_and_rejects_cross_language(self):
        identity = CommercialIdentity("Meloetta EX", "Radiant Collection", "RC25/RC25", "en", "PSA", "9")
        self.assertTrue(hardening._row_language_compatible(identity, {"language": "english"}))
        self.assertFalse(hardening._row_language_compatible(identity, {"language": "japanese"}))

    def test_ppt_generalized_scope_accepts_all_v4_psa_grades_before_network(self):
        for grade in ("8", "8.5", "9", "10"):
            identity = CommercialIdentity("Pikachu", "151", "173/165", "en", "PSA", grade)
            budget = SimpleNamespace()
            canonical = SimpleNamespace(status="NO_MATCH")
            snapshot = hardening.fetch_ppt_snapshot_generalized(
                identity,
                api_key="present",
                budget=budget,
                session=SimpleNamespace(),
                fx=SimpleNamespace(),
                canonical=canonical,
                now=NOW,
            )
            self.assertEqual(snapshot.status, "TCGDEX_UNRESOLVED")

    def test_transient_sibling_keeps_listing_pending(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "PENDING_BUDGET"},
                "poketrace": {"status": "CLEAN_NO_MATCH"},
            }
        }
        self.assertFalse(hardening.evaluation_complete_hardened(card))

    def test_matched_sibling_can_complete_even_if_other_provider_is_retryable(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "PENDING_BUDGET"},
                "poketrace": {"status": "MATCHED"},
            }
        }
        self.assertTrue(hardening.evaluation_complete_hardened(card))

    def test_pending_selection_prioritizes_known_discount_over_api_order(self):
        identity_a = CommercialIdentity("A", "Set", "1/10", "en", "PSA", "10")
        identity_b = CommercialIdentity("B", "Set", "2/10", "en", "PSA", "10")
        a = discovery.MarketplaceListing("gcc", "a", "https://x/a", "A", identity_a, FIXED_ASK, 90, "EUR", NOW, True)
        b = discovery.MarketplaceListing("gcc", "b", "https://x/b", "B", identity_b, FIXED_ASK, 40, "EUR", NOW, True)
        current = {a.stable_key: a, b.stable_key: b}
        state = {"pending": [a.stable_key, b.stable_key]}
        hardening._LAST_FAIR = {identity_a.strict_key: 100.0, identity_b.strict_key: 100.0}
        selected, keys = hardening.select_pending_prioritized(state, current, limit=1)
        self.assertEqual(selected[0].source_id, "b")
        self.assertEqual(keys, [b.stable_key])

    def test_sold_catalog_never_accepts_non_sold_row_as_sale(self):
        # Contract-level guard: the live listing parser itself does not create
        # SOLD evidence; SOLD ingestion is isolated in the history catalogue.
        listing = hardening.gcc_listing_from_row_hardened(_gcc_row(), observed_at=NOW)
        self.assertNotEqual(listing.evidence_type, "SOLD_EXACT")


if __name__ == "__main__":
    unittest.main()
