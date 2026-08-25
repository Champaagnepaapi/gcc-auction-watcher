from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_unique_full_number as unique_full
import v4_global_marketplace_unicode_identity as unicode_identity
import v4_global_retrieval_hardening_v3 as v3


CENTER_LADY = "【PSA10】ポケモンセンターのお姉さん SR 086/080 1枚の通販"


def exact_proof():
    return v3.JapaneseCatalogProof(
        status="EXACT",
        reason="TCGDEX_JA_UNIQUE_FULL_NUMBER",
        card_id="XY2-086",
        set_id="XY2",
        name_ja="ポケモンセンターのお姉さん",
        set_name_ja="ワイルドブレイズ",
        local_id="086",
        official_count="80",
    )


class FakeResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve(self, identity, *, title=""):
        self.calls.append((identity, title))
        return self.result


class MagiUniqueFullNumberTests(unittest.TestCase):
    def test_missing_set_code_recovers_only_after_global_unique_full_number(self):
        ask = japan.Ask("magi", "https://magi.camp/items/1", CENTER_LADY, 50000, CENTER_LADY)
        resolver = FakeResolver(exact_proof())
        original = native.MagiNativeResolution("NO_MATCH", "set_code_unproven")

        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = unique_full.recover_unique_full_number_resolution(
                ask,
                original,
                resolver=resolver,
            )

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "ポケモンセンターのお姉さん")
        self.assertEqual(result.identity.set_name, "ワイルドブレイズ")
        self.assertEqual(result.identity.number, "86/80")
        self.assertEqual(result.identity.language, "ja")
        self.assertEqual(resolver.calls[0][1], "")
        self.assertEqual(resolver.calls[0][0].number, "86/80")
        self.assertIn("UNIQUE_FULL_NUMBER", result.reason)

    def test_catalog_ambiguity_remains_blocking(self):
        ask = japan.Ask("magi", "https://magi.camp/items/2", CENTER_LADY, 50000, CENTER_LADY)
        proof = v3.JapaneseCatalogProof("AMBIGUOUS", reason="TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER")
        result = unique_full.recover_unique_full_number_resolution(
            ask,
            native.MagiNativeResolution("NO_MATCH", "set_code_unproven"),
            resolver=FakeResolver(proof),
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("MULTIPLE_CARDS", result.reason)

    def test_wrong_japanese_name_stays_blocked(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/3",
            "【PSA10】別のカード SR 086/080 1枚の通販",
            50000,
            "【PSA10】別のカード SR 086/080 1枚の通販",
        )
        result = unique_full.recover_unique_full_number_resolution(
            ask,
            native.MagiNativeResolution("NO_MATCH", "set_code_unproven"),
            resolver=FakeResolver(exact_proof()),
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "target_japanese_card_name_unproven")

    def test_non_numeric_denominator_is_not_reinterpreted(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/4",
            "【PSA10】ルギアV 324/S-P 1枚の通販",
            50000,
            "【PSA10】ルギアV 324/S-P 1枚の通販",
        )
        original = native.MagiNativeResolution("NO_MATCH", "set_code_unproven")
        resolver = FakeResolver(exact_proof())
        result = unique_full.recover_unique_full_number_resolution(ask, original, resolver=resolver)
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])

    def test_alphanumeric_local_id_does_not_spend_recovery_budget(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/5",
            "【PSA10】カメックス CLL007/032 1枚の通販",
            50000,
            "【PSA10】カメックス CLL007/032 1枚の通販",
        )
        original = native.MagiNativeResolution("NO_MATCH", "set_code_unproven")
        resolver = FakeResolver(exact_proof())
        result = unique_full.recover_unique_full_number_resolution(ask, original, resolver=resolver)
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])

    def test_other_rejection_reason_is_untouched(self):
        ask = japan.Ask("magi", "https://magi.camp/items/6", CENTER_LADY, 50000, CENTER_LADY)
        original = native.MagiNativeResolution("NO_MATCH", "collector_number_unproven")
        resolver = FakeResolver(exact_proof())
        result = unique_full.recover_unique_full_number_resolution(ask, original, resolver=resolver)
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
