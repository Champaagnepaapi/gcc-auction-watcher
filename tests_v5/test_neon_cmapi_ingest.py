from __future__ import annotations

import unittest

from v5 import neon_cmapi_ingest as ingest


class CmapiNeonIdentityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.card = {
            "name": "Umbreon VMAX",
            "set": "Evolving Skies",
            "number": "215",
        }

    def test_accepts_structured_psa10_exact_title(self) -> None:
        offer = {
            "title": "Umbreon VMAX 215/203 Evolving Skies Alt Art Moonbreon Pokemon",
            "company": "PSA",
            "grade": "10",
        }
        self.assertTrue(ingest._sale_offer_matches_card(self.card, offer))

    def test_accepts_hash_number_when_set_and_name_match(self) -> None:
        offer = {
            "title": "POKEMON FA/UMBREON VMAX 2021 SWSH EVOLVING SKIES-SECRET #215 PSA 10",
            "company": "PSA",
            "grade": "10",
        }
        self.assertTrue(ingest._sale_offer_matches_card(self.card, offer))

    def test_rejects_wrong_set(self) -> None:
        offer = {
            "title": "Umbreon VMAX 215 Lost Origin PSA 10",
            "company": "PSA",
            "grade": "10",
        }
        self.assertFalse(ingest._sale_offer_matches_card(self.card, offer))

    def test_rejects_wrong_grade(self) -> None:
        offer = {
            "title": "Umbreon VMAX 215 Evolving Skies PSA 9",
            "company": "PSA",
            "grade": "9",
        }
        self.assertFalse(ingest._sale_offer_matches_card(self.card, offer))


if __name__ == "__main__":
    unittest.main()
