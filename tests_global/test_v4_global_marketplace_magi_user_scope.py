from __future__ import annotations

import unittest

import v4_global_marketplace_magi_user_scope as scope


class MagiUserScopeTests(unittest.TestCase):
    def test_only_reviewed_subjects_are_excluded(self):
        self.assertTrue(scope.excluded_magi_opportunity_subject("ポケモンだいすきクラブ【SR】087/080"))
        self.assertTrue(scope.excluded_magi_opportunity_subject("ポケモンパルシティ バトルロード サマー★2007"))
        self.assertTrue(scope.excluded_magi_opportunity_subject("バトルロード サマー 2007 九州大会"))

    def test_pokemon_subject_cards_are_not_generically_excluded(self):
        self.assertFalse(scope.excluded_magi_opportunity_subject("カスミのタッツー LV.16 旧裏 No.116"))
        self.assertFalse(scope.excluded_magi_opportunity_subject("ピカチュウ 025/165 PSA10"))
        self.assertFalse(scope.excluded_magi_opportunity_subject("ロケット団のミュウツーex 231/182 PSA10"))


if __name__ == "__main__":
    unittest.main()
