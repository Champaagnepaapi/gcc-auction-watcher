from __future__ import annotations

import unittest

import v4_global_marketplace_magi_standard_source_proof as source_proof
import v4_global_retrieval_hardening_v3 as retrieval_v3


SET_TEXT = '''
import { Set } from '../../interfaces'
import serie from '../SM'
const set: Set = {
  id: 'SM11b',
  name: { ja: 'ドリームリーグ' },
  serie: serie,
  cardCount: { official: 49 },
}
export default set
'''

CARD_TEXT = '''
import { Card } from "../../../interfaces";
import Set from "../SM11b";
const card: Card = {
  set: Set,
  name: { ja: "ソルガレオ&ルナアーラGX" },
  illustrator: "Hideki Ishikawa",
};
export default card;
'''


def exact_source_proof():
    return retrieval_v3.JapaneseCatalogProof(
        status="EXACT",
        reason="TCGDEX_SOURCE_PINNED_STANDARD_COORDINATE_EXACT",
        card_id="SM11b-063",
        set_id="SM11b",
        name_ja="ソルガレオ&ルナアーラGX",
        set_name_ja="ドリームリーグ",
        local_id="063",
        official_count="49",
    )


class MagiStandardSourceProofTests(unittest.TestCase):
    def _source(self, path: str):
        mapping = {
            "data-asia/SM/SM11b.ts": SET_TEXT,
            "data-asia/SM/SM11b/063.ts": CARD_TEXT,
        }
        return mapping.get(path)

    def test_exact_set_count_card_import_and_name_prove_coordinate(self):
        proof = source_proof.source_pinned_standard_proof(
            full_number="63/49",
            set_code="SM11b",
            source_text_get=self._source,
        )
        self.assertIsNotNone(proof)
        assert proof is not None
        self.assertEqual(proof.status, "EXACT")
        self.assertEqual(proof.card_id, "SM11b-063")
        self.assertEqual(proof.set_id, "SM11b")
        self.assertEqual(proof.local_id, "063")
        self.assertEqual(proof.official_count, "49")
        self.assertEqual(proof.name_ja, "ソルガレオ&ルナアーラGX")
        self.assertEqual(proof.set_name_ja, "ドリームリーグ")

    def test_wrong_printed_denominator_fails_closed(self):
        self.assertIsNone(
            source_proof.source_pinned_standard_proof(
                full_number="63/48",
                set_code="SM11b",
                source_text_get=self._source,
            )
        )

    def test_wrong_card_set_import_fails_closed(self):
        def source(path: str):
            if path == "data-asia/SM/SM11b.ts":
                return SET_TEXT
            if path == "data-asia/SM/SM11b/063.ts":
                return CARD_TEXT.replace('../SM11b', '../SM12a')
            return None

        self.assertIsNone(
            source_proof.source_pinned_standard_proof(
                full_number="63/49",
                set_code="SM11b",
                source_text_get=source,
            )
        )

    def test_transient_rest_failure_and_clean_no_match_can_recover(self):
        original = source_proof._ORIGINAL_PROOF
        old_source = source_proof.source_pinned_standard_proof
        try:
            source_proof.source_pinned_standard_proof = lambda **kwargs: exact_source_proof()

            source_proof._ORIGINAL_PROOF = lambda *args, **kwargs: retrieval_v3.JapaneseCatalogProof(
                "ERROR", reason="TCGDEX_HTTP_-1"
            )
            cache = {}
            recovered = source_proof._proof_with_standard_source_fallback(
                object(), full_number="63/49", set_code="SM11b", cache=cache
            )
            self.assertEqual(recovered.status, "EXACT")
            self.assertIn(("sm11b", "63/49"), cache)

            source_proof._ORIGINAL_PROOF = lambda *args, **kwargs: retrieval_v3.JapaneseCatalogProof(
                "NO_MATCH", reason="TCGDEX_NO_CARD_FOR_FULL_NUMBER"
            )
            clean_cache = {}
            clean = source_proof._proof_with_standard_source_fallback(
                object(), full_number="63/49", set_code="SM11b", cache=clean_cache
            )
            self.assertEqual(clean.status, "EXACT")
            self.assertIn(("sm11b", "63/49"), clean_cache)
        finally:
            source_proof._ORIGINAL_PROOF = original
            source_proof.source_pinned_standard_proof = old_source

    def test_ambiguous_rest_result_is_never_overridden(self):
        original = source_proof._ORIGINAL_PROOF
        old_source = source_proof.source_pinned_standard_proof
        called = []
        try:
            source_proof._ORIGINAL_PROOF = lambda *args, **kwargs: retrieval_v3.JapaneseCatalogProof(
                "AMBIGUOUS", reason="TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER"
            )
            source_proof.source_pinned_standard_proof = lambda **kwargs: called.append(kwargs) or exact_source_proof()
            result = source_proof._proof_with_standard_source_fallback(
                object(), full_number="63/49", set_code="SM11b", cache={}
            )
            self.assertEqual(result.status, "AMBIGUOUS")
            self.assertEqual(called, [])
        finally:
            source_proof._ORIGINAL_PROOF = original
            source_proof.source_pinned_standard_proof = old_source


if __name__ == "__main__":
    unittest.main()
