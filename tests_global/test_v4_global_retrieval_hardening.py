import unittest

import japan_edge_hunter as japan
from v4_global_retrieval_hardening import (
    comc_detail_identity_proof,
    comc_row_candidate_proof,
    fanatics_title_identity_proof,
    magi_candidates_hardened,
    target_local_id,
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


class GlobalRetrievalHardeningTests(unittest.TestCase):
    def test_target_local_id_normalizes_leading_zero(self):
        pikachu = japan.Identity("Pikachu", "M-P Promotional", "020/M-P", "Japanese", "PSA", "10", 2025)
        self.assertEqual(target_local_id(pikachu), "20")

    def test_fanatics_accepts_exact_parsed_set_plus_local_id(self):
        text = "2023 Pokemon Japanese SV Raging Surf AR Groudon #69 PSA 10 GEM MINT\nBuy Now $180"
        ok, proof = fanatics_title_identity_proof(text, GROUDON)
        self.assertTrue(ok)
        self.assertEqual(proof, "EXACT_SET_LOCAL_ID_PROOF")

    def test_fanatics_rejects_same_local_id_wrong_set(self):
        text = "2023 Pokemon Japanese SV Ancient Roar AR Groudon #69 PSA 10 GEM MINT\nBuy Now $180"
        ok, reason = fanatics_title_identity_proof(text, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "set_unproven")

    def test_fanatics_rejects_conflicting_full_fraction(self):
        text = (
            "2023 Pokemon Japanese SV Raging Surf AR Groudon #69 PSA 10 GEM MINT\n"
            "Collector number 69/70"
        )
        ok, reason = fanatics_title_identity_proof(text, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "conflicting_full_fraction")

    def test_fanatics_sensitive_variant_remains_fail_closed(self):
        variant = japan.Identity(
            name="Groudon",
            set_name="Raging Surf",
            number="69/62",
            language="Japanese",
            grader="PSA",
            grade="10",
            year=2023,
            variety="Master Ball",
        )
        text = "2023 Pokemon Japanese SV Raging Surf AR Groudon #69 PSA 10 GEM MINT"
        ok, reason = fanatics_title_identity_proof(text, variant)
        self.assertFalse(ok)
        self.assertEqual(reason, "sensitive_variant_unproven")

    def test_comc_candidate_accepts_exact_set_field_and_local_id(self):
        row = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - Japanese\n"
            "#183 Mewtwo Art Rare\nAll Sellers"
        )
        ok, proof = comc_row_candidate_proof(row, MEWTWO)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_EXACT_SET_LOCAL_ID_CANDIDATE")

    def test_comc_detail_requires_psa10(self):
        row = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - Japanese\n"
            "#183 Mewtwo Art Rare PSA 9 GEM MT"
        )
        ok, reason = comc_detail_identity_proof(row, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "psa10_unproven")

    def test_comc_rejects_wrong_set_with_same_local_id(self):
        row = (
            "2023 Pokemon Scarlet & Violet - Shiny Treasure ex [sv4a] - Japanese\n"
            "#183 Mewtwo PSA 10 GEM MT"
        )
        ok, reason = comc_detail_identity_proof(row, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "set_unproven")

    def test_magi_filters_exact_full_number_before_candidate_cap(self):
        rows = [
            {
                "href": f"https://magi.camp/items/{1000 + index}",
                "anchor": f"Yu-Gi-Oh unrelated {index}",
                "text": f"PSA10 62/100 unrelated {index} 10,000円",
            }
            for index in range(20)
        ]
        rows.append(
            {
                "href": "https://magi.camp/items/9999",
                "anchor": "Groudon 069/062 PSA10",
                "text": "ポケモン Groudon 069/062 PSA10 20,000円",
            }
        )
        page = FakePage(rows)
        asks, searches = magi_candidates_hardened(page, GROUDON, max_candidates=1)
        self.assertEqual(searches, 1)
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0].url, "https://magi.camp/items/9999")


if __name__ == "__main__":
    unittest.main()
