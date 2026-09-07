import unittest

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target


class FinishDiscriminatorTests(unittest.TestCase):
    def _lot(self, title: str) -> watcher.Lot:
        return watcher.Lot(url="x", title=title, current_price=1.0, source_type="fixed", grader="PSA", grade="10", card_set="Legendary Collection", card_number="4/110", language="English", listing_text=title)

    def test_single_finish_does_not_require_redundant_word(self) -> None:
        card = canonical.CanonicalCard("EXACT", card_id="x", set_id="s", set_name="x", local_id="4", full_number="4/110", name="Dark Blastoise", language_code="en", variants={"holo": True, "normal": False, "reverse": False}, reason="TCGDEX_EXACT_SET_LOCALID")
        self.assertTrue(target._material_identity_is_resolved(self._lot("Dark Blastoise"), card))

    def test_multiple_finishes_require_discriminator(self) -> None:
        card = canonical.CanonicalCard("EXACT", card_id="x", set_id="s", set_name="x", local_id="4", full_number="4/110", name="Dark Blastoise", language_code="en", variants={"holo": True, "normal": False, "reverse": True}, reason="TCGDEX_EXACT_SET_LOCALID")
        self.assertFalse(target._material_identity_is_resolved(self._lot("Dark Blastoise"), card))


if __name__ == "__main__":
    unittest.main()
