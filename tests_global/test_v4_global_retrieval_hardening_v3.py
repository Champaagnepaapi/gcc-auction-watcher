import unittest

import japan_edge_hunter as japan
from v4_global_retrieval_hardening_v3 import (
    JapaneseCatalogProof,
    TCGdexJapaneseProofResolver,
    _comc_identity_block_proof,
    fanatics_title_identity_proof_v3,
    magi_identity_check_v3,
)


GROUDON = japan.Identity(
    name="Groudon",
    set_name="Raging Surf",
    number="69/62",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2023,
)
MEWTWO = japan.Identity(
    name="Mewtwo",
    set_name="151",
    number="183/165",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2023,
)
PIKACHU = japan.Identity(
    name="Pikachu",
    set_name="M-P Promotional",
    number="20/M-P",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2025,
)


class FakeResolver(TCGdexJapaneseProofResolver):
    def __init__(self, responses):
        super().__init__(max_requests=20)
        self.responses = list(responses)

    def _get(self, path, *, params=None):
        self.requests_used += 1
        if not self.responses:
            return 404, {}
        expected, status, payload = self.responses.pop(0)
        self.assert_path = path
        if expected is not None:
            assert expected in path, (expected, path)
        return status, payload


class RetrievalHardeningV3Tests(unittest.TestCase):
    def test_fanatics_h1_exact_not_poisoned_by_unrelated_page_fraction(self):
        title = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 PSA 10 GEM MINT"
        ok, proof = fanatics_title_identity_proof_v3(title, GROUDON)
        self.assertTrue(ok)
        self.assertEqual(proof, "EXACT_FANATICS_H1_SET_LOCAL_ID_PROOF")

    def test_fanatics_wrong_fraction_in_h1_still_blocks(self):
        title = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 69/70 PSA 10 GEM MINT"
        ok, reason = fanatics_title_identity_proof_v3(title, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "conflicting_full_fraction")

    def test_magi_japanese_psa10_suffix_is_detected(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1",
            "〔PSA10鑑定済〕ミュウツー 183/165 1枚",
            10000,
            "日本 ポケモンカード151 183/165",
        )
        catalog = JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_JA_UNIQUE_FULL_NUMBER",
            name_ja="ミュウツー",
            set_name_ja="ポケモンカード151",
            card_id="sv2a-183",
            set_id="sv2a",
            local_id="183",
            official_count="165",
        )
        ok, proof = magi_identity_check_v3(ask, MEWTWO, catalog=catalog)
        self.assertTrue(ok)
        self.assertIn("TCGDEX_JA_UNIQUE_FULL_NUMBER", proof)

    def test_magi_title_1_card_ignores_related_2_card_boilerplate(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1",
            "[PSA10] Mewtwo 183/165 1枚 日本",
            10000,
            "151 Japanese Mewtwo 183/165 PSA10 related recommendation 2枚",
        )
        ok, proof = magi_identity_check_v3(ask, MEWTWO)
        self.assertTrue(ok)
        self.assertEqual(proof, "MAGI_SINGLE_PLUS_LEGACY_EXACT_TEXT_PROOF")

    def test_magi_title_real_bundle_still_blocks(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
            "[PSA10] Mewtwo 183/165 2枚 日本",
            10000,
            "151 Mewtwo",
        )
        ok, reason = magi_identity_check_v3(ask, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "multi_item_listing")

    def test_tcgdex_set_code_endpoint_proves_japanese_name(self):
        detail = {
            "id": "sv2a-183",
            "localId": "183",
            "name": "ミュウツー",
            "set": {
                "id": "sv2a",
                "name": "ポケモンカード151",
                "cardCount": {"official": 165, "total": 210},
            },
        }
        resolver = FakeResolver([("sets/SV2a/183", 200, detail)])
        proof = resolver.resolve(MEWTWO, title="【PSA10】ミュウツー {183/165} [SV2a/ポケモンカード151] 1枚")
        self.assertEqual(proof.status, "EXACT")
        self.assertEqual(proof.name_ja, "ミュウツー")
        self.assertEqual(proof.reason, "TCGDEX_JA_EXACT_SET_CODE_LOCALID")
        resolver.close()

    def test_comc_dom_block_accepts_exact_mewtwo_psa10(self):
        block = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese\n"
            "183\nArt Rare - Mewtwo [PSA 10 GEM MT]\nGet SRP\n$86.50\nGet SRP\n2"
        )
        ok, proof, price = _comc_identity_block_proof(block, MEWTWO)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_DOM_BLOCK_EXACT")
        self.assertEqual(price, 86.50)

    def test_comc_dom_block_rejects_raw_same_card(self):
        block = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese\n"
            "183\nArt Rare - Mewtwo [Near Mint]\n$18.71"
        )
        ok, reason, price = _comc_identity_block_proof(block, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "psa10_unproven")
        self.assertIsNone(price)

    def test_comc_intrinsic_promo_number_can_prove_provider_set_alias(self):
        block = (
            "2025 Pokemon McDonald's Collection - Happy Meal Promos - Japanese\n"
            "020/M-P\nPikachu [PSA 10 GEM MT]\n$99.15"
        )
        ok, proof, price = _comc_identity_block_proof(block, PIKACHU)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_DOM_BLOCK_EXACT")
        self.assertEqual(price, 99.15)

    def test_comc_multiple_prices_in_same_block_fail_closed(self):
        block = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese\n"
            "183\nArt Rare - Mewtwo [PSA 10 GEM MT]\n$86.50\nRelated $20.00"
        )
        ok, reason, price = _comc_identity_block_proof(block, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "ambiguous_price_block")
        self.assertIsNone(price)

    def test_comc_wrong_numeric_set_same_localid_still_rejects(self):
        block = (
            "2023 Pokemon Scarlet & Violet - Paradox Rift [PAR] - [Base] - Japanese\n"
            "69\nGroudon [PSA 10 GEM MT]\n$50"
        )
        ok, reason, _ = _comc_identity_block_proof(block, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "set_unproven")


if __name__ == "__main__":
    unittest.main()
