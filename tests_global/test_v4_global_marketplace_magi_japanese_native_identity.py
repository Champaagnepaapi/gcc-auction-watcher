from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_japanese_native_identity as japanese_native
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_unicode_identity as unicode_identity
import v4_global_retrieval_hardening_v3 as v3


MEWTWO_TITLE = "【PSA10】 ミュウツー (AR) {183/165} [SV2a/ポケモンカード151] 1枚の通販"


def proof(
    *,
    card_id="SV2a-183",
    set_id="SV2a",
    name_ja="ミュウツー",
    set_name_ja="ポケモンカード151",
    local_id="183",
    official_count="165",
    reason="TCGDEX_JA_EXACT_SET_CODE_LOCALID",
):
    return v3.JapaneseCatalogProof(
        status="EXACT",
        reason=reason,
        card_id=card_id,
        set_id=set_id,
        name_ja=name_ja,
        set_name_ja=set_name_ja,
        local_id=local_id,
        official_count=official_count,
    )


class MagiJapaneseNativeIdentityTests(unittest.TestCase):
    def test_clean_latin_alias_absence_recovers_exact_japanese_identity(self):
        ask = japan.Ask("magi", "https://magi.camp/items/1", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        exact = proof()
        original = native.MagiNativeResolution(
            "NO_MATCH",
            "tcgdex_alias_not_found",
            card_id=exact.card_id,
            set_id=exact.set_id,
        )
        cache = {("sv2a", "183/165"): exact}

        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = japanese_native.recover_japanese_native_resolution(
                ask,
                original,
                proof_cache=cache,
            )

        self.assertEqual(result.status, "EXACT")
        self.assertIsNotNone(result.identity)
        self.assertEqual(result.identity.name, "ミュウツー")
        self.assertEqual(result.identity.set_name, "ポケモンカード151")
        self.assertEqual(result.identity.number, "183/165")
        self.assertEqual(result.identity.language, "ja")
        self.assertEqual(result.card_id, "SV2a-183")
        self.assertIn("TCGDEX_JA_NATIVE_EXACT", result.reason)

    def test_source_pinned_s_p_uses_existing_resolver_alias_without_latin_card_alias(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
            "【PSA10】ルギアV 324/S-P 1枚の通販",
            50000,
            "【PSA10】ルギアV 324/S-P 1枚の通販",
        )
        exact = proof(
            card_id="S-P-324",
            set_id="S-P",
            name_ja="ルギアV",
            set_name_ja="S-P",
            local_id="324",
            official_count="",
            reason="TCGDEX_SOURCE_PINNED_S_P_PROMO_EXACT",
        )
        original = native.MagiNativeResolution(
            "NO_MATCH",
            "tcgdex_alias_not_found",
            card_id=exact.card_id,
            set_id=exact.set_id,
        )
        cache = {("s-p", "324/S-P"): exact}

        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = japanese_native.recover_japanese_native_resolution(
                ask,
                original,
                proof_cache=cache,
            )

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "ルギアV")
        self.assertEqual(result.identity.set_name, "S-P Promotional")
        self.assertEqual(result.identity.number, "324/S-P")

    def test_transient_alias_failure_stays_blocked(self):
        ask = japan.Ask("magi", "https://magi.camp/items/3", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        exact = proof()
        original = native.MagiNativeResolution(
            "ERROR",
            "tcgdex_alias_transient_http_503",
            card_id=exact.card_id,
            set_id=exact.set_id,
        )
        result = japanese_native.recover_japanese_native_resolution(
            ask,
            original,
            proof_cache={("sv2a", "183/165"): exact},
        )
        self.assertIs(result, original)

    def test_conflicting_cached_card_id_is_not_recovered(self):
        ask = japan.Ask("magi", "https://magi.camp/items/4", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        exact = proof()
        original = native.MagiNativeResolution(
            "NO_MATCH",
            "tcgdex_alias_not_found",
            card_id="SV2a-999",
            set_id=exact.set_id,
        )
        result = japanese_native.recover_japanese_native_resolution(
            ask,
            original,
            proof_cache={("sv2a", "183/165"): exact},
        )
        self.assertIs(result, original)

    def test_source_pinned_s_p_skips_unnecessary_latin_requests(self):
        exact = proof(
            card_id="S-P-324",
            set_id="S-P",
            name_ja="ルギアV",
            set_name_ja="S-P",
            local_id="324",
            official_count="",
            reason="TCGDEX_SOURCE_PINNED_S_P_PROMO_EXACT",
        )
        called = []

        def original_fetch(_proof, *, json_get):
            called.append(json_get)
            return {"id": "unexpected"}, "unexpected"

        with mock.patch.object(japanese_native, "_ORIGINAL_ALIAS_FETCH", original_fetch):
            card, reason = japanese_native._alias_fetch_with_source_native(
                exact,
                json_get=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
            )
        self.assertIsNone(card)
        self.assertEqual(reason, "tcgdex_alias_not_found")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
