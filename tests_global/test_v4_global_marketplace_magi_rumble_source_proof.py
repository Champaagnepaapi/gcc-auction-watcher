from __future__ import annotations

import unittest

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_rumble_source_proof as rumble


SET_TEXT = '''
import { Set } from '../../interfaces'
import serie from '../Platinum'
const ru1: Set = {
  id: "ru1",
  name: { en: "Pokémon Rumble", es: "Pokémon Rumble" },
  serie: serie,
  cardCount: { official: 16 },
}
export default ru1
'''

CARD_TEXT = '''
import { Card } from '../../../interfaces'
import Set from '../Pokémon Rumble'
const card: Card = {
  name: { en: "Heatran" },
  illustrator: undefined,
  set: Set,
}
export default card
'''

TRANSLATIONS = '''
export const cardTranslationsMap = new Map<string, string>([
  ['ヒードラン', 'Heatran'],
  ['サンダー', 'Zapdos'],
])
'''

TITLE = "〔PSA10鑑定済〕ヒードラン(乱戦！ポケモンスクランブル)【-】{004/016} 1枚の通販"


def source_for(*, set_text=SET_TEXT, card_text=CARD_TEXT, translations=TRANSLATIONS):
    def get(path: str):
        mapping = {
            "data/Platinum/Pokémon Rumble.ts": set_text,
            "data/Platinum/Pokémon Rumble/4.ts": card_text,
            "scripts/utils-data/jp_card_translations.ts": translations,
        }
        return mapping.get(path)
    return get


class MagiRumbleSourceProofTests(unittest.TestCase):
    def test_exact_rumble_coordinate_recovers_from_pinned_source(self):
        identity = rumble.source_pinned_rumble_identity(
            evidence=TITLE,
            source_text_get=source_for(),
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.name, "Heatran")
        self.assertEqual(identity.set_name, "Pokémon Rumble")
        self.assertEqual(identity.number, "4/16")
        self.assertEqual(identity.language, "ja")
        self.assertEqual(identity.grader, "PSA")
        self.assertEqual(identity.grade, "10")

    def test_final_no_set_rejection_is_recovered_exactly(self):
        ask = japan.Ask("magi", "https://magi.camp/items/1", TITLE, 100000, TITLE)
        original = native.MagiNativeResolution(
            "NO_MATCH",
            "target_catalog_unproven:TCGDEX_NO_SET_WITH_OFFICIAL_DENOMINATOR",
        )
        result = rumble.recover_rumble_resolution(
            ask,
            original,
            source_text_get=source_for(),
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "ru1-4")
        self.assertEqual(result.set_id, "ru1")
        self.assertIn("POKEMON_RUMBLE", result.reason)

    def test_wrong_denominator_fails_closed(self):
        title = TITLE.replace("004/016", "004/017")
        self.assertIsNone(
            rumble.source_pinned_rumble_identity(
                evidence=title,
                source_text_get=source_for(),
            )
        )

    def test_wrong_japanese_name_translation_fails_closed(self):
        title = TITLE.replace("ヒードラン", "サンダー")
        self.assertIsNone(
            rumble.source_pinned_rumble_identity(
                evidence=title,
                source_text_get=source_for(),
            )
        )

    def test_wrong_card_set_import_fails_closed(self):
        bad_card = CARD_TEXT.replace("../Pokémon Rumble", "../Other Set")
        self.assertIsNone(
            rumble.source_pinned_rumble_identity(
                evidence=TITLE,
                source_text_get=source_for(card_text=bad_card),
            )
        )

    def test_exact_rumble_marker_is_mandatory(self):
        title = TITLE.replace("乱戦！ポケモンスクランブル", "別の商品")
        self.assertIsNone(
            rumble.source_pinned_rumble_identity(
                evidence=title,
                source_text_get=source_for(),
            )
        )

    def test_other_rejection_reason_is_untouched_without_source_reads(self):
        calls = []
        def source(path: str):
            calls.append(path)
            return None
        ask = japan.Ask("magi", "https://magi.camp/items/2", TITLE, 100000, TITLE)
        original = native.MagiNativeResolution("NO_MATCH", "japanese_set_name_unproven")
        result = rumble.recover_rumble_resolution(
            ask,
            original,
            source_text_get=source,
        )
        self.assertIs(result, original)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
