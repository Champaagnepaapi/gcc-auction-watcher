from __future__ import annotations

import unittest

import v4_canonical_multimarket as mm
import v4_tcgdex_detailed_variants as detailed


class DetailedVariantConflictTests(unittest.TestCase):
    def _card(self, raw, *, legacy=None):
        state, entries = detailed.sanitize_variants_detailed(raw, language_code="en")
        self.assertEqual(state, "USABLE")
        variants = dict(legacy or {"normal": False, "holo": True, "reverse": False})
        variants[detailed.DETAILED_SCHEMA_KEY] = detailed.DETAILED_SCHEMA_VERSION
        variants[detailed.DETAILED_STATE_KEY] = state
        variants[detailed.DETAILED_ENTRIES_KEY] = entries
        return mm.CanonicalCard(
            status="EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            variants=variants,
            reason="TCGDEX_EXACT_NAME_LOCALID",
        )

    def test_same_entry_unlimited_and_first_edition_fails_closed(self):
        card = self._card(
            [{"type": "holo", "subtype": ["unlimited"], "stamp": ["1st-edition"]}]
        )
        decision = detailed.detailed_variant_decision(card, {"finish": "holo"})
        self.assertFalse(decision.compatible)
        self.assertEqual(decision.status, "OPAQUE_MATERIAL_VARIANT")
        self.assertTrue(any(item.startswith("conflict:edition:") for item in decision.selected.opaque))

    def test_same_entry_pokeball_and_masterball_fails_closed(self):
        card = self._card(
            [{"type": "reverse", "foil": ["poke-ball", "master-ball"]}],
            legacy={"normal": False, "holo": False, "reverse": True},
        )
        decision = detailed.detailed_variant_decision(card, {"finish": "reverse"})
        self.assertFalse(decision.compatible)
        self.assertEqual(decision.status, "OPAQUE_MATERIAL_VARIANT")
        self.assertTrue(
            any(item.startswith("conflict:special_finish:") for item in decision.selected.opaque)
        )

    def test_repeated_identical_axis_value_remains_exact(self):
        card = self._card(
            [{"type": "reverse", "foil": ["master-ball", "master-ball"]}],
            legacy={"normal": False, "holo": False, "reverse": True},
        )
        decision = detailed.detailed_variant_decision(
            card, {"finish": "reverse", "special_finish": "master_ball"}
        )
        self.assertTrue(decision.compatible)
        self.assertEqual(decision.status, "EXACT")
        self.assertEqual(decision.selected.opaque, ())


if __name__ == "__main__":
    unittest.main()
