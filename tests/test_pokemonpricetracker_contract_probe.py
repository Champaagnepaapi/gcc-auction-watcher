from __future__ import annotations

import unittest

from v5 import pokemonpricetracker_contract_probe as probe
from v5.pokemonpricetracker_adapter import CanonicalPptIdentity, match_macro_identity


class PokemonPriceTrackerContractProbeTests(unittest.TestCase):
    def test_budget_is_tiny(self) -> None:
        self.assertEqual(probe.CALL_CAP, 6)
        self.assertEqual(len(probe.SENTINELS), 3)
        self.assertGreaterEqual(probe.INTERVAL_SECONDS, 2.2)

    def test_rows_support_list_and_single_object_data(self) -> None:
        self.assertEqual(len(probe.payload_rows({"data": [{"name": "A"}]})), 1)
        self.assertEqual(len(probe.payload_rows({"data": {"name": "A"}})), 1)

    def test_external_catalog_id_is_strongest_macro_match(self) -> None:
        card = CanonicalPptIdentity("swsh7-215", "Umbreon VMAX", "Evolving Skies", "215")
        rows = [{
            "name": "Umbreon VMAX (Alternate Art Secret)",
            "setName": "SWSH07: Evolving Skies",
            "cardNumber": "215/203",
            "externalCatalogId": "swsh7-215",
            "tcgPlayerId": "123",
        }]
        match = match_macro_identity(card, rows)
        self.assertEqual(match.status, "EXACT")
        self.assertEqual(match.proof, "EXTERNAL_CATALOG_ID")

    def test_set_number_fallback_tolerates_provider_name_descriptor(self) -> None:
        card = CanonicalPptIdentity("swsh7-215", "Umbreon VMAX", "Evolving Skies", "215")
        rows = [{
            "name": "Umbreon VMAX (Alternate Art Secret)",
            "setName": "SWSH07: Evolving Skies",
            "cardNumber": "215/203",
            "tcgPlayerId": "123",
        }]
        match = match_macro_identity(card, rows)
        self.assertEqual(match.status, "EXACT")
        self.assertEqual(match.proof, "SET_NUMBER")

    def test_quota_headers_never_copy_authorization(self) -> None:
        headers = {
            "X-API-Calls-Consumed": "2",
            "X-RateLimit-Remaining": "19000",
            "Authorization": "secret",
        }
        kept = probe.quota_headers(headers)
        self.assertIn("X-API-Calls-Consumed", kept)
        self.assertIn("X-RateLimit-Remaining", kept)
        self.assertNotIn("Authorization", kept)


if __name__ == "__main__":
    unittest.main()
