import unittest

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target


class ExplicitFinishProofTests(unittest.TestCase):
    def test_explicit_reverse_cannot_be_backed_by_holo_only_legacy_card(self) -> None:
        lot = watcher.Lot(
            url="x",
            title="Dark Blastoise Reverse",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Legendary Collection",
            card_number="4/110",
            language="English",
            listing_text="Dark Blastoise Reverse #4/110",
        )
        card = canonical.CanonicalCard(
            "EXACT",
            card_id="base6-4",
            set_id="base6",
            set_name="Legendary Collection",
            local_id="4",
            full_number="4/110",
            name="Dark Blastoise",
            language_code="en",
            variants={"normal": False, "holo": True, "reverse": False},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        self.assertFalse(target._material_identity_is_resolved(lot, card))


if __name__ == "__main__":
    unittest.main()
