from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_psa_checklist_numeric_semantics_probe as probe
import robot_kb_cardova_legacy_set_cohort_probe as cohort_probe


def paid_record(*, ulid, number, name):
    return {
        "source": "cardova_public_past_auction",
        "source_native_record_id": ulid,
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "sale_evidence_ready": True,
        "currency": "JPY",
        "currency_proven": True,
        "final_bid_jpy": 100000,
        "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
        "certification_number": "12345678",
        "card_name": name,
        "set_name": "Pokemon TCG: Japanese Basic",
        "collector_number": number,
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
    }


def card_source(set_id, dex_id):
    return f'''import {{ Card }} from "../../../interfaces"\nimport Set from "../{set_id}"\nconst card: Card = {{\n  set: Set,\n  category: "Pokemon",\n  dexId: [{dex_id}],\n}}\nexport default card\n'''


def set_source(set_id, official, release_date):
    return f'''import {{ Set }} from "../../interfaces"\nconst set: Set = {{\n  id: "{set_id}",\n  cardCount: {{ official: {official} }},\n  releaseDate: "{release_date}",\n}}\nexport default set\n'''


class Searcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.requests = 0

    def __call__(self, dex_id):
        self.requests += 1
        return list(self.mapping.get(dex_id, []))


class Fetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.requests = 0

    def __call__(self, path):
        self.requests += 1
        if path not in self.mapping:
            raise cohort_probe.legacy.LegacyDexProviderError(
                "PINNED_SOURCE_HTTP_404"
            )
        return self.mapping[path]


def exact_name_searcher(rows):
    mapping = {}
    for row in rows:
        dex_id = int(str(row["collector_number"]).lstrip("#"))
        mapping[dex_id] = [{"id": f"en-{dex_id}", "name": row["card_name"]}]
    return Searcher(mapping)


def basic_inputs():
    rows = [
        paid_record(ulid="A", number="#013", name="Weedle"),
        paid_record(ulid="B", number="#025", name="Pikachu"),
    ]
    ja = Searcher(
        {
            13: [{"id": "PMCG1-001"}],
            25: [{"id": "PMCG1-002"}],
        }
    )
    source = Fetcher(
        {
            "data-asia/PMCG/PMCG1/001.ts": card_source("PMCG1", 13),
            "data-asia/PMCG/PMCG1/002.ts": card_source("PMCG1", 25),
            "data-asia/PMCG/PMCG1.ts": set_source(
                "PMCG1", 102, "1996-10-20"
            ),
        }
    )
    return rows, ja, exact_name_searcher(rows), source


def html(*rows):
    body = "".join(
        f"<tr><td><a>{name}</a></td><td>{number}</td><td>1.00</td></tr>"
        for name, number in rows
    )
    return (
        "<html><body><h1>1996 Pokemon Japanese Basic Set Checklist</h1>"
        f"<table>{body}</table></body></html>"
    )


class CardovaPsaChecklistNumericSemanticsTests(unittest.TestCase):
    def test_exact_psa_name_number_proves_row_scoped_numeric_semantics_only(self):
        rows, ja, en, source = basic_inputs()
        result = probe.run_records(
            rows,
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=ja,
            english_dex_searcher=en,
            source_fetcher=source,
            psa_fetcher=lambda url: html(("WEEDLE C", "13"), ("PIKACHU C", "25")),
            pacing_seconds=0,
        )
        self.assertEqual(result["set_corroboration_groups"], 1)
        self.assertEqual(result["set_corroboration_records"], 2)
        self.assertEqual(result["provider_numeric_semantics_proven_records"], 2)
        self.assertEqual(result["macro_identity_exact_candidate_count"], 2)
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["exact_identity_link_candidate_count"], 0)
        self.assertEqual(result["blocked"], {})
        self.assertTrue(result["groups"][0]["numeric_semantics_proven_for_all_rows"])
        for row in result["records"]:
            self.assertTrue(row["psa_name_number_exact_match"])
            self.assertTrue(row["provider_number_equals_tcgdex_dexid"])
            self.assertTrue(row["provider_numeric_semantics_proven_for_row"])
            self.assertTrue(row["macro_identity_exact_candidate"])
            self.assertFalse(row["macro_identity_exact"])
            self.assertFalse(row["microvariant_exact"])

    def test_wrong_psa_number_blocks_only_that_row(self):
        rows, ja, en, source = basic_inputs()
        result = probe.run_records(
            rows,
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=ja,
            english_dex_searcher=en,
            source_fetcher=source,
            psa_fetcher=lambda url: html(("WEEDLE C", "13"), ("PIKACHU C", "26")),
            pacing_seconds=0,
        )
        self.assertEqual(result["provider_numeric_semantics_proven_records"], 1)
        self.assertEqual(
            result["blocked"], {"PSA_CHECKLIST_NAME_NUMBER_NOT_FOUND": 1}
        )
        self.assertFalse(result["groups"][0]["numeric_semantics_proven_for_all_rows"])

    def test_duplicate_psa_name_number_is_ambiguous(self):
        rows, ja, en, source = basic_inputs()
        result = probe.run_records(
            rows,
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=ja,
            english_dex_searcher=en,
            source_fetcher=source,
            psa_fetcher=lambda url: html(
                ("WEEDLE C", "13"),
                ("WEEDLE C", "13"),
                ("PIKACHU C", "25"),
            ),
            pacing_seconds=0,
        )
        self.assertEqual(result["provider_numeric_semantics_proven_records"], 1)
        self.assertEqual(
            result["blocked"], {"PSA_CHECKLIST_NAME_NUMBER_AMBIGUOUS": 1}
        )

    def test_psa_suffix_normalization_is_narrow(self):
        self.assertEqual(probe._norm_name("Venusaur Holo R"), "VENUSAUR")
        self.assertEqual(probe._norm_name("Dark Blastoise-Holo"), "DARK BLASTOISE")
        self.assertEqual(probe._norm_name("Weedle C"), "WEEDLE")
        self.assertEqual(probe._norm_name("Dark Blastoise EX"), "DARK BLASTOISE EX")
        self.assertNotEqual(
            probe._norm_name("Dark Blastoise EX"),
            probe._norm_name("Dark Blastoise"),
        )

    def test_psa_403_is_fail_visible_and_opens_circuit(self):
        rows, ja, en, source = basic_inputs()

        def blocked(_url):
            raise probe.PsaChecklistError("PSA_CHECKLIST_HTTP_403")

        result = probe.run_records(
            rows,
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=ja,
            english_dex_searcher=en,
            source_fetcher=source,
            psa_fetcher=blocked,
            pacing_seconds=0,
        )
        self.assertTrue(result["psa_checklist_circuit_open"])
        self.assertEqual(result["provider_numeric_semantics_proven_records"], 0)
        self.assertEqual(result["blocked"], {"PSA_CHECKLIST_HTTP_403": 2})

    def test_checklist_url_gate_is_exact(self):
        allowed = next(iter(probe._ALLOWED_PSA_URLS))
        probe._validate_psa_url(allowed)
        with self.assertRaisesRegex(
            probe.PsaChecklistError, "PSA_CHECKLIST_URL_NOT_REVIEWED"
        ):
            probe._validate_psa_url("https://www.psacard.com/cert/123")

    def test_safety_summary_forbids_global_claim_write_and_commerce(self):
        summary = probe.safe_summary()
        self.assertTrue(summary["database_read_only_transaction"])
        self.assertTrue(summary["provider_numeric_semantics_row_scoped_only"])
        self.assertFalse(summary["provider_numeric_semantics_global_claim"])
        self.assertFalse(summary["card_alias_table_used"])
        for key in (
            "fuzzy_matching",
            "translation_assumed",
            "macro_identity_exact",
            "microvariant_exact",
            "canonical_link_written",
            "robot_kb_write",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertIs(summary[key], False, key)


if __name__ == "__main__":
    unittest.main()
