from __future__ import annotations

import unittest

from v5 import source_scout_ebay_asp_rapidapi_probe as probe


class EbayAspRapidApiProbeTests(unittest.TestCase):
    def test_call_budget_is_small_and_hard_limited(self) -> None:
        self.assertEqual(probe.CALL_CAP, 6)
        self.assertEqual(set(probe.SITES), {"US", "UK", "FR"})

    def test_strict_match_accepts_exact_psa10(self) -> None:
        card = probe.CARDS[0]
        product = {"title": "2021 Pokemon Evolving Skies Umbreon VMAX 215/203 PSA 10 GEM MINT"}
        self.assertTrue(probe.strict_card_match(card, product))

    def test_strict_match_accepts_unique_name_and_numerator(self) -> None:
        card = probe.CARDS[1]
        product = {"title": "Pokemon Gengar VMAX #271 PSA 10 Gem Mint"}
        self.assertTrue(probe.strict_card_match(card, product))

    def test_strict_match_rejects_signed(self) -> None:
        card = probe.CARDS[1]
        product = {"title": "Gengar VMAX 271/264 PSA 10 Signed AUTO 10"}
        self.assertFalse(probe.strict_card_match(card, product))

    def test_strict_match_rejects_wrong_denominator(self) -> None:
        card = probe.CARDS[0]
        product = {"title": "Umbreon VMAX 215/264 PSA 10"}
        self.assertFalse(probe.strict_card_match(card, product))

    def test_strict_match_rejects_wrong_grade(self) -> None:
        card = probe.CARDS[0]
        product = {"title": "Umbreon VMAX 215/203 PSA 9"}
        self.assertFalse(probe.strict_card_match(card, product))


if __name__ == "__main__":
    unittest.main()
