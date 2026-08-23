from __future__ import annotations

import unittest

import v4_global_marketplace_magi_promo_source_proof as promo


SOURCE_324 = '''
import { Card } from "../../../interfaces";
import Set from "../S-P";
const card: Card = {
  set: Set,
  name: { ja: "ルギアV" },
  illustrator: "Mitsuhiro Arita",
  variants: [{ type: "normal" }],
};
export default card;
'''


class MagiPromoSourceProofTests(unittest.TestCase):
    def test_exact_s_p_coordinate_recovers_from_immutable_source(self):
        calls = []

        def get(path):
            calls.append(path)
            return SOURCE_324 if path.endswith("/324.ts") else None

        proof = promo.source_pinned_s_p_proof(
            full_number="324/S-P",
            set_code="S-P",
            source_text_get=get,
        )
        self.assertIsNotNone(proof)
        self.assertEqual(proof.status, "EXACT")
        self.assertEqual(proof.card_id, "S-P-324")
        self.assertEqual(proof.set_id, "S-P")
        self.assertEqual(proof.local_id, "324")
        self.assertEqual(proof.name_ja, "ルギアV")
        self.assertEqual(proof.reason, "TCGDEX_SOURCE_PINNED_S_P_PROMO_EXACT")
        self.assertEqual(calls, ["data-asia/S/S-P/324.ts"])

    def test_wrong_source_set_import_stays_blocked(self):
        bad = SOURCE_324.replace('../S-P', '../SV-P')
        proof = promo.source_pinned_s_p_proof(
            full_number="324/S-P",
            set_code="S-P",
            source_text_get=lambda _path: bad,
        )
        self.assertIsNone(proof)

    def test_non_s_p_promo_is_not_recovered(self):
        proof = promo.source_pinned_s_p_proof(
            full_number="242/SV-P",
            set_code="SV-P",
            source_text_get=lambda _path: SOURCE_324,
        )
        self.assertIsNone(proof)

    def test_denominator_must_equal_exact_set_code(self):
        proof = promo.source_pinned_s_p_proof(
            full_number="324/S-P",
            set_code="SV-P",
            source_text_get=lambda _path: SOURCE_324,
        )
        self.assertIsNone(proof)

    def test_numeric_set_card_is_not_recovered(self):
        proof = promo.source_pinned_s_p_proof(
            full_number="209/187",
            set_code="SV8a",
            source_text_get=lambda _path: SOURCE_324,
        )
        self.assertIsNone(proof)


if __name__ == "__main__":
    unittest.main()
