from __future__ import annotations

import unittest

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_set_code_proof as set_proof
import v4_global_retrieval_hardening_v3 as v3


class FakeResolver:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def resolve(self, identity, *, title=""):
        self.calls += 1
        return self.result


def exact_proof(*, set_id="SV2a", name_ja="ミュウツー", local_id="183", official_count="165"):
    return v3.JapaneseCatalogProof(
        status="EXACT",
        reason="TCGDEX_JA_EXACT_SET_CODE_LOCALID",
        card_id=f"{set_id}-{local_id}",
        set_id=set_id,
        name_ja=name_ja,
        set_name_ja="ポケモンカード151",
        local_id=local_id,
        official_count=official_count,
    )


def alias_get(card_id="SV2a-183", set_id="SV2a", local_id="183"):
    def get(url, **_kwargs):
        if "/en/cards/" not in url:
            return 404, {}, {}
        return 200, {
            "id": card_id,
            "localId": local_id,
            "name": "Mewtwo",
            "set": {"id": set_id, "name": "Pokemon Card 151"},
        }, {}

    return get


class MagiSetCodeProofTests(unittest.TestCase):
    def setUp(self):
        self.ask = japan.Ask(
            "magi",
            "https://magi.camp/items/200",
            "【PSA10】ミュウツー AR {183/165} [SV2a/X] 1枚の通販",
            25000,
            "",
        )
        self.original = native.MagiNativeResolution(
            "NO_MATCH",
            "target_japanese_set_unproven",
            card_id="SV2a-183",
            set_id="SV2a",
        )

    def test_exact_provider_set_code_can_replace_redundant_localized_set_name(self):
        resolver = FakeResolver(exact_proof())
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            self.original,
            resolver=resolver,
            alias_json_get=alias_get(),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.number, "183/165")
        self.assertEqual(result.identity.language, "ja")
        self.assertIn("SET_CODE_EXACT", result.reason)

    def test_tcgdex_set_conflict_stays_blocked(self):
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            self.original,
            resolver=FakeResolver(exact_proof(set_id="SV6a")),
            alias_json_get=alias_get(),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result, self.original)

    def test_tcgdex_local_id_conflict_stays_blocked(self):
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            self.original,
            resolver=FakeResolver(exact_proof(local_id="184")),
            alias_json_get=alias_get(),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result, self.original)

    def test_tcgdex_denominator_conflict_stays_blocked(self):
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            self.original,
            resolver=FakeResolver(exact_proof(official_count="166")),
            alias_json_get=alias_get(),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result, self.original)

    def test_japanese_card_name_remains_mandatory(self):
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            self.original,
            resolver=FakeResolver(exact_proof(name_ja="ペルシアン")),
            alias_json_get=alias_get(),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result, self.original)

    def test_other_rejection_reason_is_never_recovered(self):
        resolver = FakeResolver(exact_proof())
        original = native.MagiNativeResolution("NO_MATCH", "collector_number_unproven")
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            original,
            resolver=resolver,
            alias_json_get=alias_get(),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result, original)
        self.assertEqual(resolver.calls, 0)

    def test_cross_locale_alias_coordinate_conflict_does_not_become_exact(self):
        result = set_proof.recover_exact_set_code_resolution(
            self.ask,
            self.original,
            resolver=FakeResolver(exact_proof()),
            alias_json_get=alias_get(card_id="SV2a-999"),
            proof_cache={},
            alias_cache={},
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "tcgdex_alias_coordinate_conflict")


if __name__ == "__main__":
    unittest.main()
