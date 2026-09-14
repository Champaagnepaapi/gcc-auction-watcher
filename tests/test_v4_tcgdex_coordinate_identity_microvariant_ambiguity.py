import unittest

import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target
import v4_tcgdex_detailed_variants as detailed


class MicrovariantAmbiguityTests(unittest.TestCase):
    def test_two_legacy_finishes_without_listing_finish_are_not_resolved(self) -> None:
        card = canonical.CanonicalCard(
            "EXACT",
            card_id="base6-4",
            set_id="base6",
            set_name="Legendary Collection",
            local_id="4",
            full_number="4/110",
            name="Dark Blastoise",
            language_code="en",
            variants={"normal": False, "holo": True, "reverse": True},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        import watcher
        lot = watcher.Lot(
            url="x",
            title="Dark Blastoise",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Legendary Collection",
            card_number="4/110",
            language="English",
        )
        self.assertFalse(target._material_identity_is_resolved(lot, card))


if __name__ == "__main__":
    unittest.main()
