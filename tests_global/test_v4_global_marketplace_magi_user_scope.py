from __future__ import annotations

import unittest

import v4_global_marketplace_magi_user_scope as scope


class FakePage:
    def __init__(self):
        self.urls = []

    def goto(self, url, *args, **kwargs):
        self.urls.append(url)
        return "ok"

    def passthrough(self):
        return "delegated"


class MagiUserScopeTests(unittest.TestCase):
    def test_only_reviewed_subjects_are_excluded(self):
        self.assertTrue(scope.excluded_magi_opportunity_subject("ポケモンだいすきクラブ【SR】087/080"))
        self.assertTrue(scope.excluded_magi_opportunity_subject("ポケモンパルシティ バトルロード サマー★2007"))
        self.assertTrue(scope.excluded_magi_opportunity_subject("バトルロード サマー 2007 九州大会"))

    def test_pokemon_subject_cards_are_not_generically_excluded(self):
        self.assertFalse(scope.excluded_magi_opportunity_subject("カスミのタッツー LV.16 旧裏 No.116"))
        self.assertFalse(scope.excluded_magi_opportunity_subject("ピカチュウ 025/165 PSA10"))
        self.assertFalse(scope.excluded_magi_opportunity_subject("ロケット団のミュウツーex 231/182 PSA10"))

    def test_provider_native_presented_status_is_added_to_magi_search(self):
        raw = "https://magi.camp/items/search?forms_search_items%5Bkeyword%5D=PSA10"
        updated = scope._presented_only_url(raw)
        self.assertIn("forms_search_items%5Bstatus%5D=presented", updated)
        self.assertEqual(updated.count("forms_search_items%5Bstatus%5D=presented"), 1)

    def test_presented_status_is_not_added_outside_magi_search(self):
        self.assertEqual(
            scope._presented_only_url("https://magi.camp/items/123"),
            "https://magi.camp/items/123",
        )

    def test_page_proxy_rewrites_search_only_and_delegates(self):
        page = FakePage()
        proxy = scope._PresentedOnlyPage(page)
        proxy.goto("https://magi.camp/items/search?forms_search_items%5Bkeyword%5D=x")
        proxy.goto("https://magi.camp/items/123")
        self.assertIn("forms_search_items%5Bstatus%5D=presented", page.urls[0])
        self.assertEqual(page.urls[1], "https://magi.camp/items/123")
        self.assertEqual(proxy.passthrough(), "delegated")


if __name__ == "__main__":
    unittest.main()