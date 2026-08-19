import unittest

import japan_edge_hunter as japan
from v4_global_magi_target_hardening import (
    TargetCatalogProof,
    _catalog_name_compatible,
    magi_target_identity_check,
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

CATALOG = TargetCatalogProof(
    status="EXACT",
    reason="TCGDEX_TARGET_SET_LOCALID_CROSS_LANGUAGE",
    set_id="SV6a",
    set_name_en="Night Wanderer",
    set_name_ja="ナイトワンダラー",
    card_id_en="SV6a-075",
    card_id_ja="SV6a-075",
    card_name_en="Persian",
    card_name_ja="ペルシアン",
    local_id_en="075",
    local_id_ja="075",
    official_count="64",
)


class MagiTargetHardeningTests(unittest.TestCase):
    def test_catalog_name_compatibility_is_token_based_not_substring(self):
        self.assertTrue(_catalog_name_compatible("Dragonite", "Mega Dragonite ex"))
        self.assertTrue(_catalog_name_compatible("Persian", "Persian"))
        self.assertFalse(_catalog_name_compatible("Mew", "Mewtwo"))

    def test_wrong_card_same_printed_number_is_rejected(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1",
            "【状態A】【PSA10】タルップル AR 075/064 1枚",
            6600,
            "ポケモンカード ナイトワンダラー 075/064 日本",
        )
        ok, reason = magi_target_identity_check(ask, PERSIAN, CATALOG)
        self.assertFalse(ok)
        self.assertEqual(reason, "target_japanese_card_name_unproven")

    def test_correct_card_and_japanese_set_are_exact(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
            "【PSA10】ペルシアン AR 075/064 1枚",
            12000,
            "ポケモンカード ナイトワンダラー ペルシアン 075/064 日本",
        )
        ok, proof = magi_target_identity_check(ask, PERSIAN, CATALOG)
        self.assertTrue(ok)
        self.assertEqual(proof, "MAGI_TARGET_TCGDEX_CROSS_LANGUAGE_EXACT")

    def test_exact_set_code_can_replace_japanese_set_text(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/3",
            "【PSA10】ペルシアン AR {075/064} [SV6a/ナイトワンダラー] 1枚",
            12000,
            "日本 ペルシアン 075/064",
        )
        ok, proof = magi_target_identity_check(ask, PERSIAN, CATALOG)
        self.assertTrue(ok)
        self.assertEqual(proof, "MAGI_TARGET_TCGDEX_CROSS_LANGUAGE_EXACT")

    def test_conflicting_set_code_blocks(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/4",
            "【PSA10】ペルシアン AR {075/064} [SV7a/別セット] 1枚",
            12000,
            "日本 ペルシアン 075/064",
        )
        ok, reason = magi_target_identity_check(ask, PERSIAN, CATALOG)
        self.assertFalse(ok)
        self.assertEqual(reason, "target_set_code_conflict")

    def test_unproven_target_catalog_never_falls_back_to_same_number(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/5",
            "【PSA10】ペルシアン AR 075/064 1枚",
            12000,
            "ナイトワンダラー 日本",
        )
        catalog = TargetCatalogProof("NO_MATCH", "TCGDEX_TARGET_SET_NOT_UNIQUE")
        ok, reason = magi_target_identity_check(ask, PERSIAN, catalog)
        self.assertFalse(ok)
        self.assertEqual(reason, "target_catalog_unproven:TCGDEX_TARGET_SET_NOT_UNIQUE")


if __name__ == "__main__":
    unittest.main()
