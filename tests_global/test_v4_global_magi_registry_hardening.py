import unittest

import japan_edge_hunter as japan
import v4_global_retrieval_hardening_v3 as v3
from v4_global_magi_registry_hardening import (
    _target_catalog_proof,
    magi_registry_identity_check,
)
from v4_tcgdex_japanese_set_registry import (
    REGISTRY_VERSION,
    resolve_japanese_set,
)


MEWTWO = japan.Identity("Mewtwo", "151", "183/165", "Japanese", "PSA", "10", 2023)
PERSIAN = japan.Identity("Persian", "Night Wanderer", "75/64", "Japanese", "PSA", "10", 2024)
GROUDON = japan.Identity("Groudon", "Raging Surf", "69/62", "Japanese", "PSA", "10", 2023)
DRAGONITE = japan.Identity("Dragonite", "Mega Dream Ex", "246/193", "Japanese", "PSA", "10", 2025)
PIKACHU = japan.Identity("Pikachu", "M-P Promotional", "20/M-P", "Japanese", "PSA", "10", 2026)


def proof(*, card_id, set_id, name_ja, set_name_ja, local_id, official_count=""):
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


class FakeResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve(self, identity, *, title=""):
        self.calls.append((identity, title))
        return self.result


class JapaneseSetRegistryTests(unittest.TestCase):
    def test_registry_is_versioned_and_maps_panel_sets_exactly(self):
        self.assertTrue(REGISTRY_VERSION)
        expected = {
            (MEWTWO.set_name, MEWTWO.number): "SV2a",
            (PERSIAN.set_name, PERSIAN.number): "SV6a",
            (GROUDON.set_name, GROUDON.number): "SV3a",
            (DRAGONITE.set_name, DRAGONITE.number): "M2a",
            (PIKACHU.set_name, PIKACHU.number): "M-P",
        }
        for (set_name, number), set_id in expected.items():
            entry, reason = resolve_japanese_set(set_name, number)
            self.assertEqual(reason, "REGISTRY_EXACT_SET_MAPPING")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.set_id, set_id)
            self.assertTrue(entry.provenance_url.startswith("https://github.com/tcgdex/cards-database/pull/"))
            self.assertEqual(len(entry.provenance_merge_sha), 40)

    def test_unknown_set_fails_closed(self):
        entry, reason = resolve_japanese_set("Imaginary Set", "75/64")
        self.assertIsNone(entry)
        self.assertEqual(reason, "REGISTRY_TARGET_SET_UNMAPPED")

    def test_known_set_with_wrong_denominator_fails_closed(self):
        entry, reason = resolve_japanese_set("Night Wanderer", "75/62")
        self.assertIsNone(entry)
        self.assertEqual(reason, "REGISTRY_TARGET_DENOMINATOR_CONFLICT")


class MagiRegistryHardeningTests(unittest.TestCase):
    def test_target_catalog_is_forced_to_registry_set_id(self):
        entry, _ = resolve_japanese_set(MEWTWO.set_name, MEWTWO.number)
        resolver = FakeResolver(
            proof(
                card_id="SV2a-183",
                set_id="SV2a",
                name_ja="ミュウツー",
                set_name_ja="ポケモンカード151",
                local_id="183",
                official_count="165",
            )
        )
        result = _target_catalog_proof(resolver, MEWTWO, entry)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "REGISTRY_TCGDEX_EXACT_SET_LOCALID")
        self.assertEqual(resolver.calls[0][1], "[SV2a/REGISTRY]")

    def test_catalog_set_name_drift_fails_closed(self):
        entry, _ = resolve_japanese_set(PERSIAN.set_name, PERSIAN.number)
        resolver = FakeResolver(
            proof(
                card_id="SV6a-075",
                set_id="SV6a",
                name_ja="ペルシアン",
                set_name_ja="別セット",
                local_id="075",
                official_count="64",
            )
        )
        result = _target_catalog_proof(resolver, PERSIAN, entry)
        self.assertEqual(result.status, "CONFLICT")
        self.assertEqual(result.reason, "REGISTRY_TCGDEX_SET_NAME_CONFLICT")

    def test_realistic_mewtwo_title_is_exact(self):
        entry, _ = resolve_japanese_set(MEWTWO.set_name, MEWTWO.number)
        catalog = proof(
            card_id="SV2a-183",
            set_id="SV2a",
            name_ja="ミュウツー",
            set_name_ja="ポケモンカード151",
            local_id="183",
            official_count="165",
        )
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/926248132",
            "【PSA10】 ミュウツー (AR) {183/165} [SV2a/ポケモンカード151] [SV] 1枚の通販",
            25000,
            "",
        )
        self.assertEqual(
            magi_registry_identity_check(ask, MEWTWO, catalog, entry),
            (True, "MAGI_VERSIONED_TCGDEX_JA_SET_EXACT"),
        )

    def test_persian_appletun_same_number_never_matches(self):
        entry, _ = resolve_japanese_set(PERSIAN.set_name, PERSIAN.number)
        catalog = proof(
            card_id="SV6a-075",
            set_id="SV6a",
            name_ja="ペルシアン",
            set_name_ja="ナイトワンダラー",
            local_id="075",
            official_count="64",
        )
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1",
            "【PSA10】タルップル AR {075/064} [SV7a/楽園ドラゴーナ] 1枚の通販",
            10000,
            "",
        )
        ok, reason = magi_registry_identity_check(ask, PERSIAN, catalog, entry)
        self.assertFalse(ok)
        self.assertEqual(reason, "target_japanese_card_name_unproven")

    def test_conflicting_explicit_set_code_blocks_even_with_target_name(self):
        entry, _ = resolve_japanese_set(PERSIAN.set_name, PERSIAN.number)
        catalog = proof(
            card_id="SV6a-075",
            set_id="SV6a",
            name_ja="ペルシアン",
            set_name_ja="ナイトワンダラー",
            local_id="075",
            official_count="64",
        )
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
            "【PSA10】ペルシアン AR {075/064} [SV7a/別セット] 1枚の通販",
            10000,
            "",
        )
        ok, reason = magi_registry_identity_check(ask, PERSIAN, catalog, entry)
        self.assertFalse(ok)
        self.assertEqual(reason, "target_set_code_conflict")

    def test_promo_number_can_prove_intrinsic_set_code(self):
        entry, _ = resolve_japanese_set(PIKACHU.set_name, PIKACHU.number)
        catalog = proof(
            card_id="M-P-020",
            set_id="M-P",
            name_ja="ピカチュウ",
            set_name_ja="メガ プロモカード",
            local_id="020",
        )
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1922834496",
            "〔PSA10鑑定済〕ピカチュウ(マクドナルド)【P】{020/M-P} 1枚の通販",
            45000,
            "",
        )
        self.assertEqual(
            magi_registry_identity_check(ask, PIKACHU, catalog, entry),
            (True, "MAGI_VERSIONED_TCGDEX_JA_SET_EXACT"),
        )

    def test_numeric_number_without_set_code_requires_japanese_set_name(self):
        entry, _ = resolve_japanese_set(MEWTWO.set_name, MEWTWO.number)
        catalog = proof(
            card_id="SV2a-183",
            set_id="SV2a",
            name_ja="ミュウツー",
            set_name_ja="ポケモンカード151",
            local_id="183",
            official_count="165",
        )
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1625046213",
            "【PSA10】ミュウツー AR 183/165 1枚の通販",
            25000,
            "",
        )
        ok, reason = magi_registry_identity_check(ask, MEWTWO, catalog, entry)
        self.assertFalse(ok)
        self.assertEqual(reason, "target_japanese_set_unproven")


if __name__ == "__main__":
    unittest.main()
