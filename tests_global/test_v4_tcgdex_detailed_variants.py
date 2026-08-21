from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_tcgdex_detailed_variants as detailed
from v4_tcgdex_source_pinned_finish import SourcePinnedFinishProof


def lot(*, language="English", name="Charizard", reference="4/102", series="Base Set"):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test-card",
        title=name,
        current_price=40.0,
        source_type="fixed",
        grader="PSA",
        grade="8",
        card_number=reference,
        card_set=series,
        language=language,
        body=(
            "Catégorie: Pokémon\n"
            f"Référence: #{reference}\n"
            f"Série: {series}\n"
            f"Langue: {language}\n"
            "Article Gradation Détails\n"
            "Société de gradation: PSA\n"
            "Note: 8\n"
        ),
    )


def tcgdex_card(*, variants_detailed=None):
    payload = {
        "id": "base1-4",
        "name": "Charizard",
        "localId": "4",
        "set": {
            "id": "base1",
            "name": "Base Set",
            "cardCount": {"official": 102, "total": 102},
        },
        "variants": {
            "normal": True,
            "holo": True,
            "reverse": False,
            "firstEdition": False,
        },
        "pricing": {"cardmarket": {"avg": 999}},
    }
    if variants_detailed is not None:
        payload["variants_detailed"] = variants_detailed
    return payload


def canonical_with(entries, *, state="USABLE", language="en", legacy=None):
    variants = dict(
        legacy
        or {"normal": True, "holo": True, "reverse": False, "firstEdition": False}
    )
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
        language_code=language,
        variants=variants,
        reason="TCGDEX_EXACT_NAME_LOCALID",
    )


class DetailedVariantSanitizerTests(unittest.TestCase):
    def test_real_shaped_holo_variant_is_usable(self):
        state, entries = detailed.sanitize_variants_detailed(
            [{"type": "holo", "size": "standard"}], language_code="en"
        )
        self.assertEqual(state, "USABLE")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "holo")

    def test_language_scoped_variant_must_match_exact_canonical_language(self):
        state, entries = detailed.sanitize_variants_detailed(
            [{"type": "holo", "languages": ["ja"]}], language_code="en"
        )
        self.assertEqual(state, "NO_LANGUAGE_VARIANT")
        self.assertEqual(entries, ())

    def test_unknown_type_or_malformed_shape_fails_closed(self):
        state, _ = detailed.sanitize_variants_detailed(
            [{"type": "future-superfoil"}], language_code="en"
        )
        self.assertEqual(state, "MALFORMED")
        state, _ = detailed.sanitize_variants_detailed("holo", language_code="en")
        self.assertEqual(state, "MALFORMED")

    def test_pricing_and_third_party_are_not_copied_into_identity_payload(self):
        state, entries = detailed.sanitize_variants_detailed(
            [
                {
                    "type": "holo",
                    "pricing": {"cardmarket": {"avg": 1000}},
                    "thirdParty": {"tcgplayer": 123},
                }
            ],
            language_code="en",
        )
        self.assertEqual(state, "USABLE")
        self.assertNotIn("pricing", entries[0])
        self.assertNotIn("thirdParty", entries[0])


class DetailedVariantDecisionTests(unittest.TestCase):
    def _entries(self, raw):
        state, entries = detailed.sanitize_variants_detailed(raw, language_code="en")
        self.assertEqual(state, "USABLE")
        return entries

    def test_unique_detailed_finish_can_narrow_legacy_multi_finish_for_provider_gate(self):
        card = canonical_with(self._entries([{"type": "holo"}]))
        decision = detailed.detailed_variant_decision(card, {})
        self.assertTrue(decision.compatible)
        self.assertEqual(decision.status, "EXACT")
        effective = detailed._effective_canonical(card, decision)
        self.assertTrue(effective.variants["holo"])
        self.assertFalse(effective.variants["normal"])

    def test_multiple_finishes_block_without_listing_finish(self):
        card = canonical_with(
            self._entries([{"type": "normal"}, {"type": "holo"}])
        )
        decision = detailed.detailed_variant_decision(card, {})
        self.assertFalse(decision.compatible)
        self.assertEqual(decision.status, "AMBIGUOUS")

    def test_listing_finish_can_select_one_detailed_variant(self):
        card = canonical_with(
            self._entries([{"type": "normal"}, {"type": "holo"}])
        )
        decision = detailed.detailed_variant_decision(card, {"finish": "holo"})
        self.assertTrue(decision.compatible)
        self.assertEqual(decision.selected.dimension_map()["finish"], "holo")

    def test_masterball_vs_pokeball_requires_special_finish_proof(self):
        card = canonical_with(
            self._entries(
                [
                    {"type": "reverse", "foil": "master-ball"},
                    {"type": "reverse", "foil": "poke-ball"},
                ]
            ),
            legacy={"normal": False, "holo": False, "reverse": True},
        )
        blocked = detailed.detailed_variant_decision(card, {"finish": "reverse"})
        self.assertFalse(blocked.compatible)
        self.assertEqual(blocked.status, "AMBIGUOUS")
        exact = detailed.detailed_variant_decision(
            card, {"finish": "reverse", "special_finish": "master_ball"}
        )
        self.assertTrue(exact.compatible)
        self.assertEqual(
            exact.selected.dimension_map()["special_finish"], "master_ball"
        )

    def test_first_edition_and_unlimited_do_not_collapse(self):
        card = canonical_with(
            self._entries(
                [
                    {"type": "holo", "stamp": ["1st-edition"]},
                    {"type": "holo", "subtype": "unlimited"},
                ]
            ),
            legacy={"normal": False, "holo": True, "reverse": False, "firstEdition": True},
        )
        blocked = detailed.detailed_variant_decision(card, {"finish": "holo"})
        self.assertFalse(blocked.compatible)
        selected = detailed.detailed_variant_decision(
            card, {"finish": "holo", "edition": "first_edition"}
        )
        self.assertTrue(selected.compatible)

    def test_jumbo_or_unknown_material_axis_is_not_silently_accepted(self):
        jumbo = canonical_with(self._entries([{"type": "holo", "size": "jumbo"}]))
        self.assertEqual(
            detailed.detailed_variant_decision(jumbo, {}).status,
            "OPAQUE_MATERIAL_VARIANT",
        )
        unknown_foil = canonical_with(
            self._entries([{"type": "holo", "foil": "future-foil"}])
        )
        self.assertEqual(
            detailed.detailed_variant_decision(unknown_foil, {}).status,
            "OPAQUE_MATERIAL_VARIANT",
        )

    def test_source_pinned_japanese_finish_remains_authoritative(self):
        entries = self._entries([{"type": "holo"}])
        card = canonical_with(
            entries,
            language="ja",
            legacy={"normal": False, "holo": False, "reverse": True},
        )
        proof = SourcePinnedFinishProof(
            finishes=("reverse",), source_path="data-asia/X/X/004.ts"
        )
        with patch(
            "v4_tcgdex_source_pinned_finish.source_pinned_finish_proof",
            return_value=proof,
        ):
            decision = detailed.detailed_variant_decision(card, {})
        self.assertFalse(decision.compatible)
        self.assertEqual(decision.status, "CONFLICT")

    def test_absent_detailed_data_preserves_existing_fallback(self):
        card = mm.CanonicalCard(
            status="EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            variants={"normal": False, "holo": True, "reverse": False},
            reason="TCGDEX_EXACT_NAME_LOCALID",
        )
        decision = detailed.detailed_variant_decision(card, {})
        self.assertTrue(decision.compatible)
        self.assertEqual(decision.status, "ABSENT")


class DetailedVariantCanonicalAttachmentTests(unittest.TestCase):
    def test_exact_validator_attaches_detail_without_replacing_pricing(self):
        target = lot()
        payload = tcgdex_card(
            variants_detailed=[
                {
                    "type": "holo",
                    "pricing": {"cardmarket": {"avg": 1}},
                    "thirdParty": {"tcgplayer": 999},
                }
            ]
        )
        result = detailed._validate_with_detailed_variants(
            target,
            payload,
            language_code="en",
            unique_name_number=True,
            reason="TCGDEX_EXACT_NAME_LOCALID",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.pricing, payload["pricing"])
        self.assertEqual(result.variants[detailed.DETAILED_STATE_KEY], "USABLE")
        stored = result.variants[detailed.DETAILED_ENTRIES_KEY][0]
        self.assertNotIn("pricing", stored)
        self.assertNotIn("thirdParty", stored)

    def test_runtime_entrypoints_install_after_final_provider_gates(self):
        v4 = Path("run_watcher_multimarket.py").read_text(encoding="utf-8")
        global_runner = Path("v4_global_marketplace_notify_resilient.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("install_v4_tcgdex_detailed_variants()", v4)
        self.assertGreater(
            v4.index("install_v4_tcgdex_detailed_variants()"),
            v4.index("install_multimarket_safety_hardening()"),
        )
        self.assertIn("install_v4_tcgdex_detailed_variants()", global_runner)
        self.assertGreater(
            global_runner.index("install_v4_tcgdex_detailed_variants()"),
            global_runner.index("install_global_provider_exact_bridge()"),
        )


if __name__ == "__main__":
    unittest.main()
