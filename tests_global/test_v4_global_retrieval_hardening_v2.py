import unittest

import japan_edge_hunter as japan
from v4_global_retrieval_hardening_v2 import (
    MarketTrace,
    _canonical_fanatics_url,
    comc_psa10_price_from_row,
    comc_row_candidate_proof_v2,
    fanatics_title_identity_proof_v2,
    magi_candidates_v2,
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


class FakePage:
    def __init__(self, rows):
        self.rows = rows
        self.urls = []

    def goto(self, url, **_kwargs):
        self.urls.append(url)

    def wait_for_timeout(self, _ms):
        return None

    def evaluate(self, _script):
        return self.rows


class Seed:
    source_identity = GROUDON


class GlobalRetrievalHardeningV2Tests(unittest.TestCase):
    def test_fanatics_accepts_official_era_prefix_schema(self):
        text = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 PSA 10 GEM MINT\n$182"
        ok, proof = fanatics_title_identity_proof_v2(text, GROUDON)
        self.assertTrue(ok)
        self.assertEqual(proof, "EXACT_SET_LOCAL_ID_PROOF_V2")

    def test_fanatics_rejects_wrong_set_even_with_same_local_id(self):
        text = "2023 Pokemon Japanese Scarlet & Violet Ancient Roar AR Groudon #69 PSA 10 GEM MINT\n$182"
        ok, reason = fanatics_title_identity_proof_v2(text, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "set_unproven")

    def test_fanatics_embedded_route_is_canonicalized(self):
        url = _canonical_fanatics_url(
            'x /buy-now/2c2c47a6-046a-452e-89fd-620eef6cd458/2023-pokemon-japanese-raging-surf "'
        )
        self.assertEqual(
            url,
            "https://www.fanaticscollect.com/buy-now/2c2c47a6-046a-452e-89fd-620eef6cd458",
        )

    def test_comc_accepts_realistic_metadata_line(self):
        row = (
            "2023 Pokemon Scarlet & Violet - Raging Surf [sv3a] - [Base] - Japanese #069\n"
            "Art Rare - Groudon [PSA 10 GEM MT]\n"
            "$70.40"
        )
        ok, proof = comc_row_candidate_proof_v2(row, GROUDON)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_EXACT_METADATA_LOCAL_ID_CANDIDATE_V2")
        self.assertEqual(comc_psa10_price_from_row(row), 70.40)

    def test_comc_raw_listing_does_not_become_psa10_price(self):
        row = (
            "2023 Pokemon Scarlet & Violet - Raging Surf [sv3a] - [Base] - Japanese #069\n"
            "Art Rare - Groudon [Near Mint]\n"
            "$24.69"
        )
        ok, _ = comc_row_candidate_proof_v2(row, GROUDON)
        self.assertTrue(ok)
        self.assertIsNone(comc_psa10_price_from_row(row))

    def test_comc_wrong_set_rejected(self):
        row = (
            "2023 Pokemon Scarlet & Violet - Ancient Roar [sv4K] - [Base] - Japanese #069\n"
            "Art Rare - Groudon [PSA 10 GEM MT]\n$70.40"
        )
        ok, reason = comc_row_candidate_proof_v2(row, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "set_language_localid_unproven")

    def test_magi_prioritizes_pokemon_psa10_before_number_only_noise(self):
        rows = [
            {
                "href": "https://magi.camp/items/1001",
                "anchor": "unrelated 069/062",
                "text": "069/062 10,000円",
            },
            {
                "href": "https://magi.camp/items/1002",
                "anchor": "ポケモン 069/062 PSA10",
                "text": "ポケモン 069/062 PSA10 20,000円",
            },
        ]
        trace = MarketTrace("magi")
        asks, _ = magi_candidates_v2(FakePage(rows), Seed(), 1, trace)
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0].url, "https://magi.camp/items/1002")


if __name__ == "__main__":
    unittest.main()
