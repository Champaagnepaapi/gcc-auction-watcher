import unittest

import japan_edge_hunter as japan
import v4_global_retrieval_hardening_v3 as retrieval_v3
from v4_global_magi_target_hardening_v2 import (
    SameCardIdTargetBridge,
    _target_set_compatible,
)


PERSIAN = japan.Identity(
    name="Persian",
    set_name="Night Wanderer",
    number="75/64",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2024,
)

MEWTWO = japan.Identity(
    name="Mewtwo",
    set_name="151",
    number="183/165",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2023,
)


def en_card(card_id, local_id, name, set_id, set_name):
    return {
        "id": card_id,
        "localId": local_id,
        "name": name,
        "set": {"id": set_id, "name": set_name},
    }


class FakeBridge(SameCardIdTargetBridge):
    def __init__(self, responses):
        super().__init__(max_requests=20)
        self.responses = responses

    def _get(self, card_id):
        self.requests_used += 1
        return self.responses.get(card_id, (404, {}))


class MagiTargetHardeningV2Tests(unittest.TestCase):
    def test_target_set_wrapper_is_bounded(self):
        self.assertTrue(_target_set_compatible("151", "Pokemon Card 151"))
        self.assertTrue(_target_set_compatible("M-P Promotional", "M-P Promotional cards"))
        self.assertFalse(_target_set_compatible("151", "151 Anniversary Collection"))

    def test_same_card_id_bridge_proves_mewtwo_without_english_set_number_assumption(self):
        ja = retrieval_v3.JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_JA_EXACT_SET_CODE_LOCALID",
            card_id="sv2a-183",
            set_id="sv2a",
            name_ja="ミュウツー",
            set_name_ja="ポケモンカード151",
            local_id="183",
            official_count="165",
        )
        bridge = FakeBridge(
            {
                "sv2a-183": (
                    200,
                    en_card("sv2a-183", "183", "Mewtwo", "sv2a", "Pokemon Card 151"),
                )
            }
        )
        try:
            proof = bridge.resolve(MEWTWO, ja)
        finally:
            bridge.close()
        self.assertEqual(proof.status, "EXACT")
        self.assertEqual(proof.reason, "TCGDEX_SAME_CARD_ID_JA_EN_TARGET_EXACT")
        self.assertEqual(proof.card_name_en, "Mewtwo")
        self.assertEqual(proof.card_name_ja, "ミュウツー")

    def test_wrong_card_same_number_is_blocked(self):
        ja = retrieval_v3.JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_JA_UNIQUE_FULL_NUMBER",
            card_id="sv9x-75",
            set_id="sv9x",
            name_ja="タルップル",
            set_name_ja="別セット",
            local_id="75",
            official_count="64",
        )
        bridge = FakeBridge(
            {
                "sv9x-75": (
                    200,
                    en_card("sv9x-75", "75", "Appletun", "sv9x", "Other Set"),
                )
            }
        )
        try:
            proof = bridge.resolve(PERSIAN, ja)
        finally:
            bridge.close()
        self.assertEqual(proof.status, "CONFLICT")
        self.assertEqual(proof.reason, "TCGDEX_TARGET_EN_NAME_CONFLICT")

    def test_wrong_set_same_card_name_is_blocked(self):
        ja = retrieval_v3.JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_JA_UNIQUE_FULL_NUMBER",
            card_id="sv9x-75",
            set_id="sv9x",
            name_ja="ペルシアン",
            set_name_ja="別セット",
            local_id="75",
            official_count="64",
        )
        bridge = FakeBridge(
            {
                "sv9x-75": (
                    200,
                    en_card("sv9x-75", "75", "Persian", "sv9x", "Other Set"),
                )
            }
        )
        try:
            proof = bridge.resolve(PERSIAN, ja)
        finally:
            bridge.close()
        self.assertEqual(proof.status, "CONFLICT")
        self.assertEqual(proof.reason, "TCGDEX_TARGET_EN_SET_CONFLICT")

    def test_ambiguous_japanese_catalog_stays_blocked_without_network(self):
        ja = retrieval_v3.JapaneseCatalogProof(
            status="AMBIGUOUS",
            reason="TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER",
        )
        bridge = FakeBridge({})
        try:
            proof = bridge.resolve(PERSIAN, ja)
        finally:
            bridge.close()
        self.assertEqual(proof.status, "AMBIGUOUS")
        self.assertEqual(proof.reason, "TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER")
        self.assertEqual(bridge.requests_used, 0)

    def test_cross_language_card_id_conflict_is_blocked(self):
        ja = retrieval_v3.JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_JA_UNIQUE_FULL_NUMBER",
            card_id="sv6a-75",
            set_id="sv6a",
            name_ja="ペルシアン",
            set_name_ja="ナイトワンダラー",
            local_id="75",
            official_count="64",
        )
        bridge = FakeBridge(
            {
                "sv6a-75": (
                    200,
                    en_card("different-id", "75", "Persian", "sv6a", "Night Wanderer"),
                )
            }
        )
        try:
            proof = bridge.resolve(PERSIAN, ja)
        finally:
            bridge.close()
        self.assertEqual(proof.status, "CONFLICT")
        self.assertEqual(proof.reason, "TCGDEX_CROSS_LANGUAGE_CARD_ID_CONFLICT")


if __name__ == "__main__":
    unittest.main()
