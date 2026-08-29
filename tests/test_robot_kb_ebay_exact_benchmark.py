from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "mac" / "robot-kb-local" / "robot_kb_ebay_exact_benchmark.py"
)
SPEC = importlib.util.spec_from_file_location(
    "robot_kb_ebay_exact_benchmark", MODULE_PATH
)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def target(**overrides):
    values = {
        "gcc_url": "https://gradedcardcenter.com/item/example",
        "title": "Pikachu",
        "card_set": "Terastal Festival ex",
        "collector_number": "195/187",
        "language": "JA",
        "grader": "PSA",
        "grade": "10",
        "year": 2024,
    }
    values.update(overrides)
    return benchmark.BenchmarkTarget(**values)


def candidate(title: str, *, best_offer: bool = False, **overrides):
    values = {
        "item_id": "123456789012",
        "title": title,
        "date_sold": "2026-08-18",
        "sale_price_minor": 25000,
        "currency": "USD",
        "buying_format": "Best Offer" if best_offer else "Buy It Now",
        "accepted_offer_ambiguous": best_offer,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def corroboration(**overrides):
    values = {
        "item_id": "123456789012",
        "source": "PSA Sales History",
        "source_url": "https://www.psacard.com/example",
        "verified_at": "2026-08-29T07:00:00Z",
        "gcc_url": "https://gradedcardcenter.com/item/example",
        "title": "Pikachu",
        "card_set": "Terastal Festival ex",
        "collector_number": "195/187",
        "language": "JA",
        "grader": "PSA",
        "grade": "10",
        "year": 2024,
        "date_sold": "2026-08-18",
        "sale_price_minor": 25000,
        "currency": "USD",
        "exact_identity_proven": True,
        "microvariant_compatible_proven": True,
        "sale_status_proven": True,
        "final_price_semantics_proven": True,
        "best_offer": False,
    }
    values.update(overrides)
    return benchmark.CorroborationRecord(**values)


class EbayExactBenchmarkTests(unittest.TestCase):
    def test_strict_title_compatibility_requires_all_dimensions(self):
        result, reasons = benchmark.classify_candidate(
            target(),
            candidate(
                "2024 Pokemon Japanese Terastal Festival ex Pikachu "
                "195/187 PSA 10 Gem Mint"
            ),
        )
        self.assertEqual(result, "TITLE_COMPATIBLE_NON_OFFER")
        self.assertTrue(reasons)

    def test_best_offer_is_ambiguous_even_when_identity_title_matches(self):
        result, _reasons = benchmark.classify_candidate(
            target(),
            candidate(
                "2024 Pokemon Japanese Terastal Festival ex Pikachu "
                "195/187 PSA 10",
                best_offer=True,
            ),
        )
        self.assertEqual(result, "BEST_OFFER_AMBIGUOUS")

    def test_multi_card_title_is_rejected(self):
        result, _reasons = benchmark.classify_candidate(
            target(),
            candidate(
                "Lot of 4 Pokemon Japanese Terastal Festival ex Pikachu "
                "195/187 PSA 10"
            ),
        )
        self.assertEqual(result, "LOT_OR_MULTI_CARD")

    def test_missing_language_is_not_promoted(self):
        result, _reasons = benchmark.classify_candidate(
            target(),
            candidate("Pokemon Terastal Festival ex Pikachu 195/187 PSA 10"),
        )
        self.assertEqual(result, "LANGUAGE_UNPROVEN")

    def test_wrong_grade_is_not_compatible(self):
        result, _reasons = benchmark.classify_candidate(
            target(),
            candidate(
                "Pokemon Japanese Terastal Festival ex Pikachu 195/187 PSA 9"
            ),
        )
        self.assertEqual(result, "GRADER_GRADE_UNPROVEN")

    def test_collector_number_requires_full_reference(self):
        self.assertTrue(
            benchmark.collector_number_present(
                "195/187", "Pokemon Pikachu #195/187 PSA 10"
            )
        )
        self.assertFalse(
            benchmark.collector_number_present(
                "195/187", "Pokemon Pikachu #195 PSA 10"
            )
        )

    def test_selector_keeps_only_exact_benchmarkable_gcc_cards(self):
        lots = [
            SimpleNamespace(
                url="https://gradedcardcenter.com/item/ja",
                title="Pikachu",
                card_set="Terastal Festival ex",
                card_number="195/187",
                language="Japanese",
                grader="PSA",
                grade="10",
                year=2024,
            ),
            SimpleNamespace(
                url="https://gradedcardcenter.com/item/en",
                title="Charizard ex",
                card_set="151",
                card_number="199/165",
                language="English",
                grader="CGC",
                grade="10",
                year=2023,
            ),
            SimpleNamespace(
                url="https://gradedcardcenter.com/item/fr",
                title="Mew",
                card_set="151",
                card_number="205/165",
                language="French",
                grader="PSA",
                grade="10",
                year=2023,
            ),
        ]
        selected = benchmark.select_targets(lots, 10)
        self.assertEqual(len(selected), 2)
        self.assertEqual({row.language for row in selected}, {"JA", "EN"})

    def test_rate_limit_stops_live_benchmark_without_retries(self):
        targets = [target(), target(title="Charizard", collector_number="199/165")]
        first = {
            "http_status": 429,
            "provider_error": "http-429",
            "classification_counts": {},
            "corroborated_sold_count": 0,
        }
        with (
            patch.object(benchmark, "fetch_gcc_targets", return_value=targets),
            patch.object(
                benchmark, "benchmark_target", return_value=first
            ) as probe,
        ):
            code, report = benchmark.run_benchmark("secret", 2, 0)
        self.assertEqual(code, 1)
        self.assertTrue(report["provider_rate_limited"])
        self.assertEqual(report["attempted_targets"], 1)
        self.assertEqual(probe.call_count, 1)
        self.assertFalse(report["genuine_sale_evidence"])
        self.assertFalse(report["exact_identity_proven"])
        self.assertFalse(report["robot_kb_write"])
        self.assertFalse(report["v4_economic_use"])

    def test_query_is_explicit_and_does_not_hide_identity_dimensions(self):
        query = target().query
        for expected in (
            "Pikachu",
            "Terastal Festival ex",
            "195/187",
            "Japanese",
            "PSA",
            "10",
            "2024",
        ):
            self.assertIn(expected, query)

    def test_corroborated_sold_requires_all_independent_proofs(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10 Gem Mint"
        )
        record = corroboration()
        result, reasons, used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "CORROBORATED_SOLD")
        self.assertIs(used, record)
        self.assertTrue(any("exact identity" in reason for reason in reasons))

    def test_best_offer_never_becomes_corroborated_sold(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10",
            best_offer=True,
        )
        record = corroboration()
        result, _reasons, used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "BEST_OFFER_AMBIGUOUS")
        self.assertIsNone(used)

    def test_price_mismatch_blocks_corroborated_sold(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10"
        )
        record = corroboration(sale_price_minor=24000)
        result, reasons, used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "TITLE_COMPATIBLE_NON_OFFER")
        self.assertIs(used, record)
        self.assertTrue(any("sale price" in reason for reason in reasons))

    def test_date_mismatch_blocks_corroborated_sold(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10"
        )
        record = corroboration(date_sold="2026-08-17")
        result, reasons, _used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "TITLE_COMPATIBLE_NON_OFFER")
        self.assertTrue(any("sale date" in reason for reason in reasons))

    def test_same_provider_family_cannot_corroborate_itself(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10"
        )
        record = corroboration(source="RapidAPI eBay Average Selling Price")
        result, reasons, _used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "TITLE_COMPATIBLE_NON_OFFER")
        self.assertTrue(any("not independent" in reason for reason in reasons))

    def test_microvariant_proof_is_mandatory(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10"
        )
        record = corroboration(microvariant_compatible_proven=False)
        result, reasons, _used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "TITLE_COMPATIBLE_NON_OFFER")
        self.assertTrue(any("microvariant" in reason for reason in reasons))

    def test_exact_identity_fields_must_match_target(self):
        c = candidate(
            "2024 Pokemon Japanese Terastal Festival ex Pikachu "
            "195/187 PSA 10"
        )
        record = corroboration(collector_number="196/187")
        result, reasons, _used = benchmark.classify_with_corroboration(
            target(), c, {record.item_id: record}
        )
        self.assertEqual(result, "TITLE_COMPATIBLE_NON_OFFER")
        self.assertTrue(any("exact commercial identity" in reason for reason in reasons))

    def test_grade_10_and_10_point_0_are_equivalent_in_review_record(self):
        record = corroboration(grade="10.0")
        self.assertTrue(benchmark._same_identity(target(), record))

    def test_corroboration_file_duplicate_item_ids_fail_closed(self):
        raw = {
            "schema_version": 1,
            "records": [
                {
                    **corroboration().__dict__,
                },
                {
                    **corroboration().__dict__,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corroboration.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate corroboration item_id"):
                benchmark.load_corroboration_file(path)

    def test_invalid_schema_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corroboration.json"
            path.write_text(
                json.dumps({"schema_version": 999, "records": []}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "schema_version"):
                benchmark.load_corroboration_file(path)


if __name__ == "__main__":
    unittest.main()
