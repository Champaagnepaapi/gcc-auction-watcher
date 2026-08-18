from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety
import v4_tcgdex_source_pinned_finish as source_finish


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class SourcePinnedFinishTests(unittest.TestCase):
    def setUp(self) -> None:
        source_finish.clear_source_finish_runtime_state()

    def _card(self, **overrides):
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

    def _lot(self, *, number: str = "174/172"):
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/source-pinned-card",
            title="Kricketune",
            current_price=30.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number=number,
            card_set="VSTAR Universe",
            language="Japanese",
            body=(
                "Catégorie: Pokémon\n"
                f"Référence: #{number}\n"
                "Série: VSTAR Universe\n"
                "Langue: Japanese\n"
                "Société de gradation: PSA\n"
                "Note: 10\n"
            ),
        )

    def _candidate(self, *, number: str = "174/172", variant: str = "Holofoil"):
        return {
            "id": "poketrace-card-ja",
            "name": "Kricketune (Japanese)",
            "cardNumber": number,
            "set": {"name": "S12a: VSTAR Universe", "slug": "s12a-vstar-universe"},
            "variant": variant,
            "productType": "single",
            "game": "pokemon-japanese",
        }

    @staticmethod
    def _source(set_id: str, *finishes: str) -> str:
        variants = "\n".join(
            f'        {{ type: "{finish}", thirdParty: {{ cardmarket: 1 }} }},'
            for finish in finishes
        )
        return (
            'import { Card } from "../../../interfaces";\n'
            f'import Set from "../{set_id}";\n'
            "const card: Card = {\n"
            '    abilities: [{ type: "Ability", name: { ja: "x" } }],\n'
            "    variants: [\n"
            f"{variants}\n"
            "    ],\n"
            "};\n"
            "export default card;\n"
        )

    def test_source_paths_are_generic_for_s_and_sv_eras(self):
        self.assertEqual(
            source_finish._source_paths_for_card(self._card()),
            ("data-asia/S/S12a/174.ts",),
        )
        zoroa = self._card(
            card_id="SV6a-072",
            set_id="SV6a",
            set_name="Night Wanderer",
            local_id="072",
            full_number="072/064",
            name="Zorua",
        )
        self.assertEqual(
            source_finish._source_paths_for_card(zoroa),
            ("data-asia/SV/SV6a/072.ts",),
        )

    def test_parser_reads_only_variants_block(self):
        proof = source_finish._parse_source_finish_proof(
            self._source("S12a", "holo"),
            set_id="S12a",
            source_path="data-asia/S/S12a/174.ts",
        )
        self.assertIsNotNone(proof)
        self.assertEqual(proof.finishes, ("holo",))

    def test_generic_source_proof_corrects_kricketune_finish_only(self):
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12a", "holo")),
        ) as get:
            corrected = source_finish.apply_source_pinned_finish(self._card())

        self.assertEqual(get.call_count, 1)
        self.assertIn("/data-asia/S/S12a/174.ts", get.call_args.args[0])
        self.assertFalse(corrected.variants["normal"])
        self.assertTrue(corrected.variants["holo"])
        self.assertFalse(corrected.variants["reverse"])
        self.assertFalse(corrected.variants["firstEdition"])
        self.assertTrue(corrected.variants["wPromo"])

    def test_generic_source_proof_also_corrects_toxtricity_without_new_registry_entry(self):
        toxtricity = self._card(
            card_id="S12a-181",
            local_id="181",
            full_number="181/172",
            name="Toxtricity",
        )
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12a", "holo")),
        ) as get:
            corrected = source_finish.apply_source_pinned_finish(toxtricity)

        self.assertEqual(get.call_count, 1)
        self.assertIn("/data-asia/S/S12a/181.ts", get.call_args.args[0])
        self.assertFalse(corrected.variants["normal"])
        self.assertTrue(corrected.variants["holo"])

    def test_source_can_prove_multiple_finishes_without_inventing_uniqueness(self):
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12a", "normal", "reverse")),
        ):
            corrected = source_finish.apply_source_pinned_finish(self._card())

        self.assertTrue(corrected.variants["normal"])
        self.assertFalse(corrected.variants["holo"])
        self.assertTrue(corrected.variants["reverse"])

    def test_source_pin_requires_exact_catalog_identity_and_japanese_language(self):
        for override in (
            {"status": "AMBIGUOUS"},
            {"card_id": "S12a-175"},
            {"set_id": "S12"},
            {"local_id": "175"},
            {"language_code": "en"},
        ):
            with self.subTest(override=override), patch.object(
                source_finish._SESSION, "get"
            ) as get:
                original = self._card(**override)
                self.assertIs(source_finish.apply_source_pinned_finish(original), original)
                get.assert_not_called()

    def test_missing_or_malformed_source_fails_closed(self):
        original = self._card()
        with patch.object(
            source_finish._SESSION, "get", return_value=_Response(404, "")
        ):
            self.assertIs(source_finish.apply_source_pinned_finish(original), original)

        source_finish.clear_source_finish_runtime_state()
        malformed = self._source("S12a", "cosmos")
        with patch.object(
            source_finish._SESSION, "get", return_value=_Response(200, malformed)
        ):
            self.assertIs(source_finish.apply_source_pinned_finish(original), original)

    def test_wrong_set_import_fails_closed(self):
        original = self._card()
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S11a", "holo")),
        ):
            self.assertIs(source_finish.apply_source_pinned_finish(original), original)

    def test_source_proof_is_cached_by_immutable_path(self):
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12a", "holo")),
        ) as get:
            first = source_finish.apply_source_pinned_finish(self._card())
            second = source_finish.apply_source_pinned_finish(self._card())
        self.assertEqual(get.call_count, 1)
        self.assertEqual(first.variants, second.variants)

    def test_kricketune_live_shape_passes_after_generic_source_proof(self):
        original = self._card()
        lot = self._lot()
        candidate = self._candidate()
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(lot, original, candidate)
        )

        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12a", "holo")),
        ):
            corrected = source_finish.apply_source_pinned_finish(original)
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(lot, corrected, candidate)
        )

    def test_provider_finish_cannot_override_conflicting_pinned_source(self):
        other = self._card(
            card_id="S12a-175",
            local_id="175",
            full_number="175/172",
        )
        lot = self._lot(number="175/172")
        candidate = self._candidate(number="175/172", variant="Holofoil")
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12a", "normal")),
        ):
            corrected = source_finish.apply_source_pinned_finish(other)

        self.assertTrue(corrected.variants["normal"])
        self.assertFalse(corrected.variants["holo"])
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(lot, corrected, candidate)
        )


if __name__ == "__main__":
    unittest.main()
