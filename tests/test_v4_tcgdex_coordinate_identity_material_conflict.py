import unittest

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target


class MaterialConflictTests(unittest.TestCase):
    def test_explicit_reverse_conflicts_with_holo_only_coordinate(self) -> None:
        lot = watcher.Lot(url="x", title="Dark Blastoise Reverse", current_price=1.0, source_type="fixed", grader="PSA", grade="10", card_set="Team Rocket", card_number="3/82", language="English", listing_text="Dark Blastoise Reverse")
        card = canonical.CanonicalCard("EXACT", card_id="base5-3", set_id="base5", set_name="Team Rocket", local_id="3", full_number="3/82", name="Dark Blastoise", language_code="en", variants={"holo": True, "normal": False, "reverse": False}, reason="TCGDEX_EXACT_SET_LOCALID")
        self.assertFalse(target._material_identity_is_resolved(lot, card))


if __name__ == "__main__":
    unittest.main()
