from __future__ import annotations

import unittest

import japan_edge_hunter as japan
import v4_global_marketplace_magi_classic_reviewed_catalog as classic


class MagiClassicReviewedCatalogTests(unittest.TestCase):
    def ask(self, title: str, text: str | None = None) -> japan.Ask:
        return japan.Ask("magi", "https://magi.camp/items/1", title, 10000, title if text is None else text)

    def test_exact_reviewed_pikachu_coordinate(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ピカチュウ (CLL) PROMO CLL008/032 1枚")
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "MAGI_REVIEWED_CLASSIC_COORDINATE_EXACT")
        self.assertEqual(result.identity.name, "Pikachu")
        self.assertEqual(result.identity.number, "CLL008/032")
        self.assertEqual(result.identity.language, "ja")
        self.assertEqual(result.identity.grader, "PSA")
        self.assertEqual(result.identity.grade, "10")

    def test_reviewed_blatoise_and_venusaur_coordinates(self):
        for title, name, number in (
            ("【PSA10】ポケモンカードゲーム Classic カメックス (CLK) PROMO CLK003/032 1枚", "Blastoise", "CLK003/032"),
            ("【PSA10】ポケモンカードゲーム Classic フシギバナ (CLF) PROMO CLF003/032 1枚", "Venusaur", "CLF003/032"),
        ):
            with self.subTest(number=number):
                result = classic.resolve_reviewed_classic_identity(self.ask(title))
                self.assertEqual(result.status, "EXACT")
                self.assertEqual(result.identity.name, name)
                self.assertEqual(result.identity.number, number)

    def test_unreviewed_clefairy_stays_blocked(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ピッピ (CLL) PROMO CLL013/032 1枚")
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "reviewed_classic_coordinate_absent")

    def test_wrong_denominator_stays_blocked(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ピカチュウ (CLL) PROMO CLL008/031 1枚")
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "reviewed_classic_coordinate_absent")

    def test_name_conflict_stays_blocked(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ライチュウ (CLL) PROMO CLL008/032 1枚")
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "reviewed_classic_japanese_name_unproven")

    def test_multiple_coordinates_are_ambiguous(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ピカチュウ CLL008/032 CLK008/032 1枚")
        )
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_sensitive_variant_and_bundle_stay_blocked(self):
        sensitive = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ピカチュウ Reverse CLL008/032 1枚")
        )
        self.assertEqual(sensitive.status, "NO_MATCH")
        self.assertEqual(sensitive.reason, "sensitive_variant_unproven")

        bundle = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ポケモンカードゲーム Classic ピカチュウ CLL008/032 2枚")
        )
        self.assertEqual(bundle.status, "NO_MATCH")
        self.assertEqual(bundle.reason, "multi_item_listing")

    def test_unrelated_detail_body_english_does_not_reject_japanese_title(self):
        title = "【PSA10】ポケモンカードゲーム Classic ピカチュウ (CLL) PROMO CLL008/032 1枚"
        result = classic.resolve_reviewed_classic_identity(
            self.ask(title, f"{title}\nMarketplace UI English")
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "MAGI_REVIEWED_CLASSIC_COORDINATE_EXACT")

    def test_explicit_english_in_title_stays_blocked(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】English ポケモンカードゲーム Classic ピカチュウ CLL008/032 1枚")
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "explicit_non_japanese_language")

    def test_non_classic_delegates_only_in_installed_wrapper(self):
        result = classic.resolve_reviewed_classic_identity(
            self.ask("【PSA10】ピカチュウ 025/165 1枚")
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "not_reviewed_classic")


if __name__ == "__main__":
    unittest.main()