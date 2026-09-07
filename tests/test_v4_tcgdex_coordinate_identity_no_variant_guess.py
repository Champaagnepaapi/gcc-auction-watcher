import unittest

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target
import v4_tcgdex_rainbow_variant_recovery as rainbow


class NoVariantGuessTests(unittest.TestCase):
    def test_rainbow_word_cannot_be_proved_by_holo_boolean_alone(self) -> None:
        rainbow._install_rainbow_dimension_support()
        lot = watcher.Lot(url="x", title="Palkia Rainbow", current_price=1.0, source_type="fixed", grader="PSA", grade="10", card_set="Ultra Prism", card_number="165/156", language="English", listing_text="Palkia Rainbow #165/156")
        card = canonical.CanonicalCard("EXACT", card_id="sm5-165", set_id="sm5", set_name="Ultra Prism", local_id="165", full_number="165/156", name="Palkia-GX", language_code="en", variants={"holo": True, "normal": False, "reverse": False}, reason="TCGDEX_EXACT_SET_LOCALID")
        self.assertFalse(target._material_identity_is_resolved(lot, card))


if __name__ == "__main__":
    unittest.main()
