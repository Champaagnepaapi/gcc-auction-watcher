from __future__ import annotations

import unittest

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety


class PokeTracePost129LiveShapeTests(unittest.TestCase):
    def test_charizard_vstar_s9_star_birth_shape_passes_existing_exact_prefix_bridge(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/post129-charizard",
            title="Charizard VStar",
            current_price=30.0,
            source_type="fixed",
            grader="SFG",
            grade="9.5",
            card_number="015/100",
            card_set="Brilliant Stars",
            language="Japanese",
            body=(
                "Catégorie: Pokémon\n"
                "Référence: #015/100\n"
                "Série: Brilliant Stars\n"
                "Langue: Japanese\n"
                "Société de gradation: SFG\n"
                "Note: 9.5\n"
            ),
        )
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="S9-015",
            set_id="S9",
            set_name="Brilliant Stars",
            local_id="015",
            full_number="015/100",
            name="Charizard VStar",
            language_code="ja",
            variants={"normal": False, "holo": True, "reverse": False},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        candidate = {
            "id": "poketrace-charizard-vstar-ja",
            "name": "Charizard VSTAR (Japanese)",
            "cardNumber": "015/100",
            "set": {"name": "S9: Star Birth", "slug": "s9-star-birth"},
            "variant": "Holofoil",
            "productType": "single",
            "game": "pokemon-japanese",
        }
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(lot, canonical, candidate)
        )

    def test_explicit_provider_namespace_conflict_remains_blocked(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/post129-zorua",
            title="Zorua",
            current_price=25.0,
            source_type="fixed",
            grader="CA",
            grade="9.5",
            card_number="072/064",
            card_set="Night Wanderer",
            language="Japanese",
        )
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="SV7a-072",
            set_id="SV7a",
            set_name="Night Wanderer",
            local_id="072",
            full_number="072/064",
            name="Zorua",
            language_code="ja",
            variants={"holo": True},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        candidate = {
            "id": "poketrace-zorua-ja",
            "name": "Zorua (Japanese)",
            "cardNumber": "072/064",
            "set": {"name": "SV6a: Night Wanderer", "slug": "sv6a-night-wanderer"},
            "variant": "Holofoil",
            "productType": "single",
            "game": "pokemon-japanese",
        }
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(lot, canonical, candidate)
        )


if __name__ == "__main__":
    unittest.main()
