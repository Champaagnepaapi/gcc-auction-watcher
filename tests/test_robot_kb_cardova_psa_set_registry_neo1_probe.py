from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_legacy_set_cohort_probe as cohort_probe
import robot_kb_cardova_psa_set_registry_corroboration_probe as registry_probe


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
        "certification_number": f"cert-{ulid}",
        "card_name": name,
        "set_name": "Pokemon TCG: Japanese neo Gold, Silver, to a New World...",
        "collector_number": number,
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
    }


def card_source(local_id, dex_id):
    return f'''import {{ Card }} from "../../../interfaces"\nimport Set from "../neo1"\nconst card: Card = {{\n  set: Set,\n  category: "Pokemon",\n  dexId: [{dex_id}],\n}}\nexport default card\n'''


def set_source(release_date):
    return f'''import {{ Set }} from "../../interfaces"\nconst set: Set = {{\n  id: "neo1",\n  cardCount: {{ official: 96 }},\n  releaseDate: "{release_date}",\n}}\nexport default set\n'''


class Searcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.requests = 0

    def __call__(self, dex_id):
        self.requests += 1
        return list(self.mapping.get(dex_id, []))


class Fetcher:
    def __init__(self, release_date):
        self.requests = 0
        self.mapping = {
            "data-asia/neo/neo1/042.ts": card_source("042", 172),
            "data-asia/neo/neo1/072.ts": card_source("072", 249),
            "data-asia/neo/neo1.ts": set_source(release_date),
        }

    def __call__(self, path):
        self.requests += 1
        if path not in self.mapping:
            raise cohort_probe.legacy.LegacyDexProviderError("PINNED_SOURCE_HTTP_404")
        return self.mapping[path]


def rows():
    return [
        paid_record(ulid="A", number="#172", name="Pichu"),
        paid_record(ulid="B", number="#249", name="Lugia"),
    ]


def ja_searcher():
    return Searcher({
        172: [{"id": "neo1-042"}],
        249: [{"id": "neo1-072"}],
    })


def en_searcher():
    return Searcher({
        172: [{"id": "en-172", "name": "Pichu"}],
        249: [{"id": "en-249", "name": "Lugia"}],
    })


class CardovaPsaNeo1SemanticsTests(unittest.TestCase):
    def test_neo1_keeps_psa_issue_year_separate_from_release_year(self):
        result = registry_probe.run_records(
            rows(),
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=ja_searcher(),
            english_dex_searcher=en_searcher(),
            source_fetcher=Fetcher("2000-02-04"),
        )
        self.assertEqual(result["psa_registry_corroborated_groups"], 1)
        self.assertEqual(result["psa_registry_corroborated_records"], 2)
        self.assertEqual(result["corroboration_blocked"], {})
        group = result["corroborated_groups"][0]
        self.assertEqual(group["tcgdex_set_id_candidate"], "neo1")
        self.assertEqual(group["reviewed_psa_issue_year"], 1999)
        self.assertEqual(group["reviewed_release_year"], 2000)
        self.assertEqual(group["pinned_set_official_count"], 96)
        self.assertEqual(group["pinned_set_release_date"], "2000-02-04")
        self.assertIn("pokemon-card.com", group["reviewed_release_year_source_url"])
        self.assertFalse(group["psa_issue_year_used_as_release_year"])
        self.assertFalse(group["macro_identity_exact"])
        self.assertFalse(group["microvariant_exact"])
        self.assertFalse(group["exact_identity_link_candidate"])
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["exact_identity_link_candidate_count"], 0)

    def test_neo1_rejects_psa_issue_year_as_pinned_release_year(self):
        result = registry_probe.run_records(
            rows(),
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=ja_searcher(),
            english_dex_searcher=en_searcher(),
            source_fetcher=Fetcher("1999-02-04"),
        )
        self.assertEqual(result["psa_registry_corroborated_groups"], 0)
        self.assertEqual(
            result["corroboration_blocked"],
            {"PSA_REGISTRY_PINNED_YEAR_CONFLICT": 1},
        )
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["exact_identity_link_candidate_count"], 0)

    def test_summary_never_uses_psa_issue_year_as_release_year(self):
        summary = registry_probe.safe_summary()
        self.assertFalse(summary["psa_issue_year_used_as_release_year"])
        self.assertTrue(
            summary["independent_release_year_source_required_when_years_differ"]
        )
        self.assertFalse(summary["canonical_link_written"])
        self.assertFalse(summary["robot_kb_write"])


if __name__ == "__main__":
    unittest.main()
