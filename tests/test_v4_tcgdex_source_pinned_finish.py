from __future__ import annotations

import unittest

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety
import v4_tcgdex_source_pinned_finish as source_finish


class SourcePinnedFinishTests(unittest.TestCase):
    def _kricketune(self, **overrides):
        values = {
            "status": "EXACT",
            "card_id": "S12a-174",
            "set_id": "S12a",
            "set_name": "VSTAR Universe",
            "local_id": "174",
            "full_number": "174/172",
            "name": "Kricketune",
            "language_code": "ja",
            "variants": {
                "normal": True,
                "holo": False,
                "reverse": False,
                "firstEdition": False,
                "wPromo": True,
            },
            "reason": "TCGDEX_EXACT_SET_LOCALID",
        }
        values.update(overrides)
        return mm.CanonicalCard(**values)

    def _lot(self):
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/source-pinned-kricketune",
            title="Kricketune",
            current_price=30.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number="174/172",
            card_set="VSTAR Universe",
            language="Japanese",
            body=(
                "Catégorie: Pokémon\n"
                "Référence: #174/172\n"
                "Série: VSTAR Universe\n"
                "Langue: Japanese\n"
                "Société de gradation: PSA\n"
                "Note: 10\n"
            ),
        )

    def _candidate(self):
        return {
            "id": "poketrace-kricketune-ja",
            "name": "Kricketune (Japanese)",
            "cardNumber": "174/172",
            "set": {"name": "S12a: VSTAR Universe", "slug": "s12a-vstar-universe"},
            "variant": "Holofoil",
            "productType": "single",
            "game": "pokemon-japanese",
        }

    def test_exact_source_pin_corrects_only_finish_flags(self):
        corrected = source_finish.apply_source_pinned_finish(self._kricketune())
        self.assertFalse(corrected.variants["normal"])
        self.assertTrue(corrected.variants["holo"])
        self.assertFalse(corrected.variants["reverse"])
        self.assertFalse(corrected.variants["firstEdition"])
        self.assertTrue(corrected.variants["wPromo"])

    def test_source_pin_requires_exact_catalog_identity(self):
        for override in (
            {"card_id": "S12a-175"},
            {"set_id": "S12"},
            {"local_id": "175"},
            {"language_code": "en"},
        ):
            with self.subTest(override=override):
                original = self._kricketune(**override)
                self.assertIs(source_finish.apply_source_pinned_finish(original), original)

    def test_non_exact_identity_is_never_overridden(self):
        original = self._kricketune(status="AMBIGUOUS")
        self.assertIs(source_finish.apply_source_pinned_finish(original), original)

    def test_kricketune_live_shape_passes_only_after_source_pinned_finish(self):
        original = self._kricketune()
        lot = self._lot()
        candidate = self._candidate()
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(lot, original, candidate)
        )

        corrected = source_finish.apply_source_pinned_finish(original)
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(lot, corrected, candidate)
        )

    def test_provider_finish_cannot_trigger_override_for_other_card(self):
        other = self._kricketune(card_id="S12a-175", local_id="175", full_number="175/172")
        candidate = self._candidate()
        candidate["cardNumber"] = "175/172"
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(self._lot(), other, candidate)
        )
        self.assertIs(source_finish.apply_source_pinned_finish(other), other)


if __name__ == "__main__":
    unittest.main()
