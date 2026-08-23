from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as v3
from v4_global_market_core import FIXED_ASK


MEWTWO_TITLE = "【PSA10】 ミュウツー (AR) {183/165} [SV2a/ポケモンカード151] [SV] 1枚の通販"


def exact_proof(
    *,
    card_id="SV2a-183",
    set_id="SV2a",
    name_ja="ミュウツー",
    set_name_ja="ポケモンカード151",
    local_id="183",
    official_count="165",
):
    return v3.JapaneseCatalogProof(
        status="EXACT",
        reason="TCGDEX_JA_EXACT_SET_CODE_LOCALID",
        card_id=card_id,
        set_id=set_id,
        name_ja=name_ja,
        set_name_ja=set_name_ja,
        local_id=local_id,
        official_count=official_count,
    )


def latin_alias(*, card_id="SV2a-183", set_id="SV2a", local_id="183"):
    return {
        "id": card_id,
        "localId": local_id,
        "name": "Mewtwo",
        "set": {"id": set_id, "name": "Pokemon Card 151"},
    }


class FakeResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.requests_used = 1

    def resolve(self, identity, *, title=""):
        self.calls.append((identity, title))
        return self.result

    def close(self):
        pass


def alias_get(card):
    def get(url, **_kwargs):
        if "/en/cards/" in url:
            return 200, card, {}
        return 404, {}, {}

    return get


class MagiNativeResolutionTests(unittest.TestCase):
    def test_standard_magi_title_resolves_without_gcc_seed_or_translation(self):
        ask = japan.Ask("magi", "https://magi.camp/items/1", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        resolver = FakeResolver(exact_proof())
        result = native.resolve_magi_native_identity(
            ask,
            resolver=resolver,
            alias_json_get=alias_get(latin_alias()),
        )
        self.assertEqual(result.status, "EXACT")
        self.assertIsNotNone(result.identity)
        self.assertEqual(result.identity.name, "Mewtwo")
        self.assertEqual(result.identity.set_name, "Pokemon Card 151")
        self.assertEqual(result.identity.number, "183/165")
        self.assertEqual(result.identity.language, "ja")
        self.assertEqual(result.identity.grader, "PSA")
        self.assertEqual(result.identity.grade, "10")
        self.assertIn("same_card_en_projection", result.reason)
        self.assertEqual(resolver.calls[0][1], "[SV2a/MAGI_NATIVE]")

    def test_same_number_wrong_japanese_card_name_is_blocked(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
            "【PSA10】 ペルシアン (AR) {183/165} [SV2a/ポケモンカード151] 1枚の通販",
            25000,
            "",
        )
        result = native.resolve_magi_native_identity(
            ask,
            resolver=FakeResolver(exact_proof()),
            alias_json_get=alias_get(latin_alias()),
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "target_japanese_card_name_unproven")

    def test_tcgdex_set_code_conflict_is_ambiguous(self):
        ask = japan.Ask("magi", "https://magi.camp/items/3", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        result = native.resolve_magi_native_identity(
            ask,
            resolver=FakeResolver(exact_proof(set_id="SV6a")),
            alias_json_get=alias_get(latin_alias()),
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "tcgdex_set_code_conflict")

    def test_numeric_card_without_set_code_fails_closed(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/4",
            "【PSA10】ミュウツー AR 183/165 1枚の通販",
            25000,
            "",
        )
        result = native.resolve_magi_native_identity(
            ask,
            resolver=FakeResolver(exact_proof()),
            alias_json_get=alias_get(latin_alias()),
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "set_code_unproven")

    def test_intrinsic_promo_set_code_is_accepted(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/5",
            "〔PSA10鑑定済〕ピカチュウ(マクドナルド)【P】{020/M-P} 1枚の通販",
            45000,
            "",
        )
        proof = exact_proof(
            card_id="M-P-020",
            set_id="M-P",
            name_ja="ピカチュウ",
            set_name_ja="メガ プロモカード",
            local_id="020",
            official_count="",
        )
        alias = {
            "id": "M-P-020",
            "localId": "020",
            "name": "Pikachu",
            "set": {"id": "M-P", "name": "Mega Promo Card"},
        }
        result = native.resolve_magi_native_identity(
            ask,
            resolver=FakeResolver(proof),
            alias_json_get=alias_get(alias),
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.number, "20/M-P")

    def test_explicit_english_language_marker_is_blocked(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/6",
            MEWTWO_TITLE.replace("1枚の通販", "英語版 1枚の通販"),
            25000,
            "",
        )
        result = native.resolve_magi_native_identity(
            ask,
            resolver=FakeResolver(exact_proof()),
            alias_json_get=alias_get(latin_alias()),
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "explicit_non_japanese_language")

    def test_sensitive_variant_is_not_silently_collapsed(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/7",
            MEWTWO_TITLE.replace("(AR)", "MASTER BALL"),
            25000,
            "",
        )
        result = native.resolve_magi_native_identity(
            ask,
            resolver=FakeResolver(exact_proof()),
            alias_json_get=alias_get(latin_alias()),
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "sensitive_variant_unproven")


class ScanMagiNativeTests(unittest.TestCase):
    def test_scan_emits_fixed_ask_with_unknown_buyer_economics(self):
        observed_at = datetime(2026, 8, 22, 18, 0, tzinfo=timezone.utc)
        ask = japan.Ask("magi", "https://magi.camp/items/8", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        identity = native.CommercialIdentity(
            name="Mewtwo",
            set_name="Pokemon Card 151",
            number="183/165",
            language="ja",
            grader="PSA",
            grade="10",
        )
        resolution = native.MagiNativeResolution(
            "EXACT",
            "MAGI_NATIVE_TCGDEX_JA_SET_EXACT+tcgdex_same_card_en_projection",
            identity=identity,
            card_id="SV2a-183",
            set_id="SV2a",
        )
        with mock.patch.object(native.scan, "_magi_broad_rows", return_value=[ask]), mock.patch.object(
            native.retrieval_v1, "magi_detail_only", return_value=ask
        ), mock.patch.object(
            native.magi_hardening, "magi_listing_availability_check", return_value=(True, "no_sold_marker")
        ), mock.patch.object(native, "resolve_magi_native_identity", return_value=resolution):
            rows, status = native.scan_magi_native_inventory(
                object(), (), observed_at=observed_at, max_detail_pages=100
            )

        self.assertEqual(status.status, "OK")
        self.assertEqual(status.candidates, 1)
        self.assertEqual(status.exact, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].market, "magi")
        self.assertEqual(rows[0].evidence_type, FIXED_ASK)
        self.assertTrue(rows[0].identity_proven)
        self.assertIsNone(rows[0].buyer_fee_rate)
        self.assertIn("ASK is not SOLD", rows[0].note)

    def test_sold_detail_is_blocked_before_identity_resolution(self):
        observed_at = datetime(2026, 8, 22, 18, 0, tzinfo=timezone.utc)
        ask = japan.Ask("magi", "https://magi.camp/items/9", MEWTWO_TITLE, 25000, MEWTWO_TITLE)
        with mock.patch.object(native.scan, "_magi_broad_rows", return_value=[ask]), mock.patch.object(
            native.retrieval_v1, "magi_detail_only", return_value=ask
        ), mock.patch.object(
            native.magi_hardening, "magi_listing_availability_check", return_value=(False, "sold_listing")
        ), mock.patch.object(
            native, "resolve_magi_native_identity", side_effect=AssertionError("identity resolver must not run")
        ):
            rows, status = native.scan_magi_native_inventory(
                object(), (), observed_at=observed_at, max_detail_pages=100
            )
        self.assertEqual(rows, [])
        self.assertEqual(status.exact, 0)
        self.assertIn("sold_listing", status.detail)


if __name__ == "__main__":
    unittest.main()
