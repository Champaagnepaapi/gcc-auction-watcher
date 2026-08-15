from __future__ import annotations

import unittest

from v5.microvariants import tcgdex_microvariant_applicability
from v5.models import CardIdentity
from v5.variant_semantics import tcgdex_variant_supports_identity


class TCGdexWPromoSemanticsTests(unittest.TestCase):
    def test_black_star_promo_is_not_rejected_when_wpromo_is_false(self):
        identity = CardIdentity(
            game="Pokémon TCG",
            card_name="Charizard G",
            set="DP Black Star Promos",
            card_number="DP045",
            language="English",
            rarity="Promo",
            finish="Holo",
        )
        card = {
            "variants": {
                "firstEdition": False,
                "holo": True,
                "normal": False,
                "reverse": False,
                "wPromo": False,
            }
        }

        self.assertTrue(tcgdex_variant_supports_identity(identity, card))

    def test_wpromo_true_does_not_prove_generic_promo_or_finish(self):
        applicability = tcgdex_microvariant_applicability(
            {
                "variants": {
                    "firstEdition": False,
                    "holo": False,
                    "normal": False,
                    "reverse": False,
                    "wPromo": True,
                }
            }
        )
        self.assertFalse(applicability.promo_proven_single)
        self.assertIsNone(applicability.single_promo)
        self.assertFalse(applicability.finish_proven_single)
        self.assertFalse(applicability.finish_multiple_variants)

    def test_finish_conflict_remains_blocking_independent_of_wpromo(self):
        identity = CardIdentity(
            game="Pokémon TCG",
            card_name="Charizard G",
            set="DP Black Star Promos",
            card_number="DP045",
            language="English",
            rarity="Promo",
            finish="Normal",
        )
        card = {
            "variants": {
                "firstEdition": False,
                "holo": True,
                "normal": False,
                "reverse": False,
                "wPromo": False,
            }
        }

        self.assertFalse(tcgdex_variant_supports_identity(identity, card))

    def test_first_edition_conflict_remains_blocking(self):
        identity = CardIdentity(
            game="Pokémon TCG",
            card_name="Charizard G",
            set="DP Black Star Promos",
            card_number="DP045",
            language="English",
            rarity="Promo",
            finish="Holo",
            edition="1st Edition",
        )
        card = {
            "variants": {
                "firstEdition": False,
                "holo": True,
                "normal": False,
                "reverse": False,
                "wPromo": False,
            }
        }

        self.assertFalse(tcgdex_variant_supports_identity(identity, card))


if __name__ == "__main__":
    unittest.main()
