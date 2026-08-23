from __future__ import annotations

import unittest

import japan_edge_hunter as japan
import v4_global_marketplace_magi_detail_coordinate as detail


class MagiDetailCoordinateTests(unittest.TestCase):
    def test_detail_can_supply_missing_title_coordinate_and_set_code(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/10",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            "商品情報\nミュウツー (AR) {183/165} [SV2a/ポケモンカード151]\nPSA10",
        )
        full_number, set_code, reason = detail.preflight_with_detail_coordinate(ask)
        self.assertEqual(full_number, "183/165")
        self.assertEqual(set_code, "SV2a")
        self.assertEqual(reason, "magi_native_detail_coordinate_parsed")

    def test_related_item_coordinate_after_boundary_is_ignored(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/11",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            "商品情報\nミュウツー {183/165} [SV2a/ポケモンカード151]\nおすすめ\nペルシアン {075/064} [SV6a/ナイトワンダラー]",
        )
        full_number, set_code, _ = detail.preflight_with_detail_coordinate(ask)
        self.assertEqual(full_number, "183/165")
        self.assertEqual(set_code, "SV2a")

    def test_multiple_current_product_numbers_are_ambiguous(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/12",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            "商品情報\n183/165\n184/165\n[SV2a/ポケモンカード151]",
        )
        full_number, set_code, reason = detail.preflight_with_detail_coordinate(ask)
        self.assertEqual(full_number, "")
        self.assertEqual(set_code, "")
        self.assertEqual(reason, "collector_number_ambiguous")

    def test_multiple_current_product_set_codes_are_ambiguous(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/13",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            "商品情報\n183/165\n[SV2a/ポケモンカード151]\n[SV6a/ナイトワンダラー]",
        )
        full_number, set_code, reason = detail.preflight_with_detail_coordinate(ask)
        self.assertEqual(full_number, "")
        self.assertEqual(set_code, "")
        self.assertEqual(reason, "set_code_ambiguous")

    def test_generic_latin_english_ui_label_is_not_card_language_evidence(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/14",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            "商品情報\nミュウツー 183/165 [SV2a/ポケモンカード151]\nEnglish\nお問い合わせ",
        )
        full_number, set_code, reason = detail.preflight_with_detail_coordinate(ask)
        self.assertEqual((full_number, set_code, reason), ("183/165", "SV2a", "magi_native_detail_coordinate_parsed"))

    def test_real_magi_english_footer_is_not_card_language_evidence(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/141",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            (
                "商品情報\nミュウツー 183/165 [SV2a/ポケモンカード151]\nPSA10\n"
                "商品ID: 141\n絞り込み\nカテゴリで絞り込む\n"
                "magiについて\nHOME\nmagi（英語版）\nお問い合わせ"
            ),
        )
        full_number, set_code, reason = detail.preflight_with_detail_coordinate(ask)
        self.assertEqual((full_number, set_code, reason), ("183/165", "SV2a", "magi_native_detail_coordinate_parsed"))

    def test_explicit_japanese_english_product_marker_blocks(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/15",
            "【PSA10】ミュウツー AR 1枚の通販",
            25000,
            "商品情報\n183/165\n[SV2a/ポケモンカード151]\n英語版",
        )
        self.assertEqual(
            detail.preflight_with_detail_coordinate(ask),
            ("", "", "explicit_non_japanese_language"),
        )

    def test_latin_english_marker_in_product_title_blocks(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/16",
            "【PSA10】Mewtwo English 1枚の通販",
            25000,
            "商品情報\n183/165\n[SV2a/ポケモンカード151]",
        )
        self.assertEqual(
            detail.preflight_with_detail_coordinate(ask),
            ("", "", "explicit_non_japanese_language"),
        )

    def test_detail_sensitive_variant_blocks(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/17",
            "【PSA10】ミュウツー 1枚の通販",
            25000,
            "商品情報\n183/165\n[SV2a/ポケモンカード151]\nMASTER BALL",
        )
        self.assertEqual(
            detail.preflight_with_detail_coordinate(ask),
            ("", "", "sensitive_variant_unproven"),
        )


if __name__ == "__main__":
    unittest.main()
