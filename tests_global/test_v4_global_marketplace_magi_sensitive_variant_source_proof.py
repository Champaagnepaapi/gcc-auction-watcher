from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_sensitive_variant_source_proof as variant_source
import v4_global_marketplace_unicode_identity as unicode_identity


SET_TEXT = '''
import { Set } from '../../interfaces'
import serie from '../SV'
const set: Set = {
  id: 'SV2a',
  name: { ja: 'ポケモンカード151' },
  serie: serie,
  cardCount: { official: 165 },
}
export default set
'''

CARD_TEXT = '''
import { Card } from "../../../interfaces";
import Set from "../SV2a";
const card: Card = {
  set: Set,
  name: { ja: "ゲンガー" },
  illustrator: "Tomokazu Komiya",
  variants: [
    { type: "holo" },
    { type: "reverse", foil: "pokeball", thirdParty: { cardmarket: 1 } },
    { type: "reverse", foil: "masterball", thirdParty: { cardmarket: 2 } },
  ],
};
export default card;
'''

TITLE = "PSA10 ゲンガー 094/165 モンスターボールミラー ポケモンカード151 SV2a 1枚の通販"


def source_for(*, set_text=SET_TEXT, card_text=CARD_TEXT):
    def get(path: str):
        mapping = {
            "data-asia/SV/SV2a.ts": set_text,
            "data-asia/SV/SV2a/094.ts": card_text,
        }
        return mapping.get(path)
    return get


class MagiSensitiveVariantSourceProofTests(unittest.TestCase):
    def test_pokeball_mirror_recovers_exact_existing_variant_dimensions(self):
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            identity, card_id, set_id = variant_source.source_pinned_sensitive_variant_identity(
                evidence=TITLE,
                source_text_get=source_for(),
            )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(card_id, "SV2a-094")
        self.assertEqual(set_id, "SV2a")
        self.assertEqual(identity.name, "ゲンガー")
        self.assertEqual(identity.set_name, "ポケモンカード151")
        self.assertEqual(identity.number, "94/165")
        self.assertEqual(identity.finish, "reverse")
        self.assertEqual(identity.variant, "poke_ball")

    def test_masterball_marker_uses_masterball_variant(self):
        title = TITLE.replace("モンスターボールミラー", "マスターボールミラー")
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            identity, _, _ = variant_source.source_pinned_sensitive_variant_identity(
                evidence=title,
                source_text_get=source_for(),
            )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.variant, "master_ball")
        self.assertEqual(identity.finish, "reverse")

    def test_requested_foil_absent_fails_closed(self):
        card = CARD_TEXT.replace('foil: "pokeball"', 'foil: "cosmos"')
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            identity, _, _ = variant_source.source_pinned_sensitive_variant_identity(
                evidence=TITLE,
                source_text_get=source_for(card_text=card),
            )
        self.assertIsNone(identity)

    def test_other_sensitive_claim_stays_blocked(self):
        title = TITLE + " 初版"
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            identity, _, _ = variant_source.source_pinned_sensitive_variant_identity(
                evidence=title,
                source_text_get=source_for(),
            )
        self.assertIsNone(identity)

    def test_wrong_japanese_card_name_stays_blocked(self):
        title = TITLE.replace("ゲンガー", "ピカチュウ")
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            identity, _, _ = variant_source.source_pinned_sensitive_variant_identity(
                evidence=title,
                source_text_get=source_for(),
            )
        self.assertIsNone(identity)

    def test_wrapper_only_handles_sensitive_variant_rejection(self):
        ask = japan.Ask("magi", "https://magi.camp/items/1", TITLE, 50000, TITLE)
        original = native.MagiNativeResolution("NO_MATCH", "collector_number_unproven")
        calls = []
        def source(path: str):
            calls.append(path)
            return None
        result = variant_source.recover_sensitive_variant_resolution(
            ask,
            original,
            source_text_get=source,
        )
        self.assertIs(result, original)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
