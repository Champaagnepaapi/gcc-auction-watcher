from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_legacy_set_cohort_probe as probe


def paid_record(*, ulid, set_name, number, name="Pokemon"):
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
        "set_name": set_name,
        "collector_number": number,
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
    }


def source(set_id, dex_id):
    return f'''import {{ Card }} from "../../../interfaces"\nimport Set from "../{set_id}"\nconst card: Card = {{\n  set: Set,\n  category: "Pokemon",\n  dexId: [{dex_id}],\n}}\nexport default card\n'''


class Fetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.requests = 0
        self.paths = []

    def __call__(self, path):
        self.requests += 1
        self.paths.append(path)
        if path not in self.mapping:
            raise probe.legacy.LegacyDexProviderError("PINNED_SOURCE_HTTP_404")
        return self.mapping[path]


class Searcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.requests = 0

    def __call__(self, dex_id):
        self.requests += 1
        return list(self.mapping.get(dex_id, []))


def exact_name_searcher(rows):
    mapping = {}
    for row in rows:
        raw = str(row["collector_number"]).lstrip("#")
        if not raw.isdigit():
            continue
        dex_id = int(raw)
        mapping.setdefault(dex_id, []).append(
            {"id": f"en-{dex_id}-{len(mapping.get(dex_id, []))}", "name": row["card_name"]}
        )
    return Searcher(mapping)


class CardovaLegacySetCohortProbeTests(unittest.TestCase):
    def test_split_card_id_uses_last_hyphen(self):
        self.assertEqual(probe._split_card_id("S-P-214"), ("S-P", "214"))
        self.assertEqual(probe._split_card_id("PMCG2-007"), ("PMCG2", "007"))
        self.assertEqual(probe._split_card_id("broken"), ("", ""))

    def test_unique_cohort_set_is_source_pinned_but_never_exact(self):
        rows = [
            paid_record(ulid="A", set_name="Pokemon TCG: Japanese Jungle", number="#013", name="Weedle"),
            paid_record(ulid="B", set_name="Pokemon TCG: Japanese Jungle", number="#025", name="Pikachu"),
            paid_record(ulid="C", set_name="Pokemon TCG: Japanese Jungle", number="#133", name="Eevee"),
        ]
        searcher = Searcher({
            13: [{"id": "PMCG1-009"}, {"id": "PMCG2-001"}],
            25: [{"id": "PMCG2-002"}, {"id": "neo1-010"}],
            133: [{"id": "PMCG2-003"}, {"id": "neo2-049"}],
        })
        fetcher = Fetcher({
            "data-asia/PMCG/PMCG2/001.ts": source("PMCG2", 13),
            "data-asia/PMCG/PMCG2/002.ts": source("PMCG2", 25),
            "data-asia/PMCG/PMCG2/003.ts": source("PMCG2", 133),
        })
        result, reason = probe.probe_group(
            "Pokemon TCG: Japanese Jungle",
            rows,
            min_distinct_dexids=2,
            dex_searcher=searcher,
            english_dex_searcher=exact_name_searcher(rows),
            source_fetcher=fetcher,
        )
        self.assertEqual(
            reason, "SOURCE_PINNED_COHORT_SET_DEXID_NAME_GATED_CANDIDATE_ONLY"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["tcgdex_set_id_candidate"], "PMCG2")
        self.assertEqual(result["distinct_dexids"], 3)
        self.assertEqual(len(result["records"]), 3)
        self.assertTrue(result["provider_name_dexid_exact_match_for_all_rows"])
        self.assertFalse(result["provider_numeric_semantics_proven"])
        self.assertFalse(result["macro_identity_exact"])
        self.assertFalse(result["exact_identity_link_candidate"])

    def test_exact_name_gate_rejects_false_local_id_cohort_before_set_inference(self):
        rows = [
            paid_record(ulid="A", set_name="Pokemon TCG: Japanese DPt Melee! Pokemon Scramble", number="#017", name="Pachirisu"),
            paid_record(ulid="B", set_name="Pokemon TCG: Japanese DPt Melee! Pokemon Scramble", number="#018", name="Croagunk"),
        ]
        ja_searcher = Searcher({
            17: [{"id": "SV2a-017"}],
            18: [{"id": "SV2a-018"}],
        })
        en_searcher = Searcher({
            17: [{"id": "base-x", "name": "Pidgeotto"}],
            18: [{"id": "base-y", "name": "Pidgeot"}],
        })
        result, reason = probe.probe_group(
            rows[0]["set_name"],
            rows,
            min_distinct_dexids=2,
            dex_searcher=ja_searcher,
            english_dex_searcher=en_searcher,
            source_fetcher=Fetcher({}),
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "PROVIDER_NAME_DEXID_EXACT_MISMATCH")
        self.assertEqual(ja_searcher.requests, 0)
        self.assertEqual(en_searcher.requests, 1)

    def test_multiple_complete_sets_fail_closed(self):
        rows = [
            paid_record(ulid="A", set_name="Legacy", number="#013", name="Weedle"),
            paid_record(ulid="B", set_name="Legacy", number="#025", name="Pikachu"),
        ]
        searcher = Searcher({
            13: [{"id": "PMCG1-001"}, {"id": "PMCG2-001"}],
            25: [{"id": "PMCG1-002"}, {"id": "PMCG2-002"}],
        })
        result, reason = probe.probe_group(
            "Legacy", rows, min_distinct_dexids=2,
            dex_searcher=searcher,
            english_dex_searcher=exact_name_searcher(rows),
            source_fetcher=Fetcher({}),
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "COHORT_SET_AMBIGUOUS")

    def test_no_common_set_fails_closed(self):
        rows = [
            paid_record(ulid="A", set_name="Legacy", number="#013", name="Weedle"),
            paid_record(ulid="B", set_name="Legacy", number="#025", name="Pikachu"),
        ]
        searcher = Searcher({13: [{"id": "PMCG1-001"}], 25: [{"id": "PMCG2-002"}]})
        result, reason = probe.probe_group(
            "Legacy", rows, min_distinct_dexids=2,
            dex_searcher=searcher,
            english_dex_searcher=exact_name_searcher(rows),
            source_fetcher=Fetcher({}),
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "COHORT_SET_NOT_FOUND")

    def test_source_conflict_blocks_candidate(self):
        rows = [
            paid_record(ulid="A", set_name="Legacy", number="#013", name="Weedle"),
            paid_record(ulid="B", set_name="Legacy", number="#025", name="Pikachu"),
        ]
        searcher = Searcher({13: [{"id": "PMCG2-001"}], 25: [{"id": "PMCG2-002"}]})
        fetcher = Fetcher({
            "data-asia/PMCG/PMCG2/001.ts": source("PMCG2", 13),
            "data-asia/PMCG/PMCG2/002.ts": source("PMCG2", 26),
        })
        result, reason = probe.probe_group(
            "Legacy", rows, min_distinct_dexids=2,
            dex_searcher=searcher,
            english_dex_searcher=exact_name_searcher(rows),
            source_fetcher=fetcher,
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "PINNED_SOURCE_SET_DEXID_CONFLICT")

    def test_single_distinct_dexid_is_insufficient(self):
        rows = [
            paid_record(ulid="A", set_name="Legacy", number="#013", name="Weedle"),
            paid_record(ulid="B", set_name="Legacy", number="#013", name="Weedle"),
        ]
        result, reason = probe.probe_group(
            "Legacy", rows, min_distinct_dexids=2,
            dex_searcher=Searcher({}),
            english_dex_searcher=exact_name_searcher(rows),
            source_fetcher=Fetcher({}),
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "COHORT_DISTINCT_DEXIDS_INSUFFICIENT")

    def test_structural_neo_rows_are_not_reprocessed(self):
        row = paid_record(
            ulid="A",
            set_name="Pokemon TCG: Japanese neo 2 Crossing the Ruins…",
            number="#013",
        )
        dex_id, reason = probe._eligible_numeric_row(row)
        self.assertIsNone(dex_id)
        self.assertEqual(reason, "STRUCTURAL_NEO_ALREADY_HANDLED")

    def test_run_records_groups_exact_labels_and_remains_candidate_only(self):
        rows = [
            paid_record(ulid="A", set_name="Jungle", number="#013", name="Weedle"),
            paid_record(ulid="B", set_name="Jungle", number="#025", name="Pikachu"),
            paid_record(ulid="C", set_name="Fossil", number="#093", name="Haunter"),
        ]
        searcher = Searcher({13: [{"id": "PMCG2-001"}], 25: [{"id": "PMCG2-002"}]})
        fetcher = Fetcher({
            "data-asia/PMCG/PMCG2/001.ts": source("PMCG2", 13),
            "data-asia/PMCG/PMCG2/002.ts": source("PMCG2", 25),
        })
        result = probe.run_records(
            rows,
            max_groups=10,
            min_distinct_dexids=2,
            dex_searcher=searcher,
            english_dex_searcher=exact_name_searcher(rows),
            source_fetcher=fetcher,
        )
        self.assertEqual(result["eligible_set_labels"], 2)
        self.assertEqual(result["groups_source_pinned_unique"], 1)
        self.assertEqual(result["candidate_records"], 2)
        self.assertEqual(
            result["blocked"], {"COHORT_DISTINCT_DEXIDS_INSUFFICIENT": 1}
        )
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["exact_identity_link_candidate_count"], 0)
        self.assertGreaterEqual(result["english_dex_name_gate_requests"], 2)

    def test_safe_summary_forbids_writes_and_promotions(self):
        summary = probe.safe_summary()
        self.assertTrue(summary["database_read_only_transaction"])
        self.assertTrue(summary["provider_name_dexid_exact_gate"])
        self.assertFalse(summary["translation_table_used"])
        self.assertFalse(summary["card_alias_table_used"])
        for key in (
            "provider_numeric_semantics_proven",
            "fuzzy_matching",
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
