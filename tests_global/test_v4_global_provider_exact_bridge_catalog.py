from __future__ import annotations

import unittest

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_provider_exact_bridge as bridge


class CatalogApplicabilityBridgeTests(unittest.TestCase):
    def test_unlimited_is_non_material_only_when_exact_catalog_says_no_first_edition(self):
        lot = watcher.Lot(
            url="https://example.invalid/read-only",
            title="Mewtwo",
            current_price=1.0,
            source_type="FIXED_PRICE",
            grader="PSA",
            grade="10",
            listing_text="Mewtwo",
            card_set="151",
            card_number="183/165",
            language="Japanese",
            variant="Unlimited Full Art | Art Rare",
        )
        canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="SV2a-183",
            set_id="SV2a",
            set_name="151",
            local_id="183",
            full_number="183/165",
            name="Mewtwo",
            language_code="ja",
            variants={
                "firstEdition": False,
                "holo": True,
                "normal": False,
                "reverse": False,
            },
            reason="PINNED_TEST",
        )
        candidate = {
            "name": "Mewtwo (Japanese)",
            "cardNumber": "183/165",
            "game": "pokemon-japanese",
            "productType": "single",
            "set": {"name": "SV2a: Pokemon Card 151"},
            "variant": "Holofoil",
            "rarity": "Art Rare",
        }
        self.assertTrue(bridge._sensitive_dimensions_compatible(lot, canonical, candidate))
        self.assertTrue(bridge.global_candidate_exact_for_canonical(lot, canonical, candidate))


if __name__ == "__main__":
    unittest.main()
