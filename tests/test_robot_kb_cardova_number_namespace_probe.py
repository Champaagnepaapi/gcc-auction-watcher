from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_number_namespace_probe as probe


class CardovaNumberNamespaceProbeTests(unittest.TestCase):
    def record(self, **updates):
        value = {
            "source": "cardova_public_past_auction",
            "source_native_record_id": "01TEST",
            "source_url": "https://www.cardova.co.jp/en/auction/card/01TEST",
            "provider_sale_status": "PAID_COMPLETED",
            "provider_sale_status_proven": True,
            "sale_evidence_ready": True,
            "currency": "JPY",
            "currency_proven": True,
            "final_bid_jpy": 5000000,
            "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
            "certification_number": "153603277",
            "card_name": "Mario Pikachu",
            "set_name": "Pokemon TCG: Japanese XY Promo Mario Pikachu Special Box",
            "collector_number": "#294/XY-P",
            "language": "Japanese",
            "grader": "PSA",
            "grade": "10",
        }
        value.update(updates)
        return value

    def canonical(self, **updates):
        value = {
            "status": "EXACT",
            "reason": "TCGDEX_EXACT_SET_LOCALID",
            "language_code": "ja",
            "card_id": "XY-P-294",
            "set_id": "XY-P",
            "set_name": "XY-P",
            "local_id": "294",
        }
        value.update(updates)
        return SimpleNamespace(**value)

    def test_printed_namespace_examples_are_structural_not_aliases(self):
        cases = {
            "#294/XY-P": ("294", "XY-P"),
            "145/BW-P": ("145", "BW-P"),
            "065/L-P": ("065", "L-P"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                local_id, namespace, status = probe.printed_number_namespace(raw)
                self.assertEqual((local_id, namespace), expected)
                self.assertEqual(status, "EXACT_LITERAL_NAMESPACE_CANDIDATE")

    def test_numeric_denominator_is_never_a_set_namespace(self):
        local_id, namespace, status = probe.printed_number_namespace("102/100")
        self.assertEqual(local_id, "")
        self.assertEqual(namespace, "")
        self.assertEqual(status, "NUMBER_NAMESPACE_ABSENT")

    def test_malformed_namespace_fails_closed(self):
        for raw in ("", "294", "294/XY-P/EXTRA", "294/XY P", "/XY-P"):
            with self.subTest(raw=raw):
                _local_id, namespace, status = probe.printed_number_namespace(raw)
                self.assertEqual(namespace, "")
                self.assertIn(status, {
                    "NUMBER_MISSING",
                    "NUMBER_NAMESPACE_MALFORMED",
                    "NUMBER_LOCALID_MALFORMED",
                })

    def test_literal_namespace_calls_existing_exact_coordinate_validator(self):
        seen = {}

        def fetcher(lot, **kwargs):
            seen.update(kwargs)
            seen["lot_number"] = lot.card_number
            seen["lot_set"] = lot.card_set
            return self.canonical()

        row, reason = probe.probe_record(
            self.record(),
            coordinate_fetcher=fetcher,
            microvariant_checker=lambda identity, canonical: (
                True,
                "EXACT",
                "TEST_EXACT",
                {"finish": "holo"},
            ),
        )
        self.assertEqual(reason, "EXACT_LITERAL_NAMESPACE_COORDINATE")
        self.assertIsNotNone(row)
        self.assertEqual(seen["set_id"], "XY-P")
        self.assertEqual(seen["listing_set"], "XY-P")
        self.assertEqual(seen["lot_number"], "#294/XY-P")
        self.assertEqual(seen["lot_set"], "XY-P")
        self.assertTrue(seen["allow_localized_name_mismatch"])
        self.assertEqual(row["printed_set_id_candidate"], "XY-P")
        self.assertEqual(row["tcgdex_card_id"], "XY-P-294")
        self.assertTrue(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_english_coordinate_does_not_allow_localized_name_mismatch(self):
        seen = {}

        def fetcher(lot, **kwargs):
            seen.update(kwargs)
            return self.canonical(
                language_code="en",
                set_id="SVP",
                card_id="SVP-001",
                local_id="001",
            )

        record = self.record(
            collector_number="001/SVP",
            language="English",
            set_name="Scarlet & Violet Promo",
            card_name="Pikachu",
        )
        row, reason = probe.probe_record(
            record,
            coordinate_fetcher=fetcher,
            microvariant_checker=lambda identity, canonical: (True, "EXACT", "", {}),
        )
        self.assertEqual(reason, "EXACT_LITERAL_NAMESPACE_COORDINATE")
        self.assertIsNotNone(row)
        self.assertFalse(seen["allow_localized_name_mismatch"])

    def test_wrong_returned_set_or_language_is_blocked(self):
        row, reason = probe.probe_record(
            self.record(),
            coordinate_fetcher=lambda lot, **kwargs: self.canonical(set_id="OTHER"),
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "LITERAL_NAMESPACE_SET_ID_CONFLICT")

        row, reason = probe.probe_record(
            self.record(),
            coordinate_fetcher=lambda lot, **kwargs: self.canonical(language_code="en"),
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "LITERAL_NAMESPACE_LANGUAGE_CONFLICT")

    def test_microvariant_ambiguity_never_becomes_ready(self):
        row, reason = probe.probe_record(
            self.record(),
            coordinate_fetcher=lambda lot, **kwargs: self.canonical(),
            microvariant_checker=lambda identity, canonical: (
                False,
                "AMBIGUOUS",
                "multiple finishes",
                {},
            ),
        )
        self.assertIsNotNone(row)
        self.assertTrue(reason.startswith("MICROVARIANT_AMBIGUOUS"))
        self.assertFalse(row["microvariant_exact"])
        self.assertFalse(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_run_reports_structural_coverage_separately_from_exactness(self):
        records = [
            self.record(source_native_record_id="a", collector_number="294/XY-P"),
            self.record(source_native_record_id="b", collector_number="102/100"),
        ]

        payload = probe.run(
            records,
            max_records=2,
            coordinate_fetcher=lambda lot, **kwargs: self.canonical(),
            microvariant_checker=lambda identity, canonical: (True, "EXACT", "", {}),
            stack_installer=lambda: None,
        )
        self.assertEqual(payload["structured_namespace_candidate_count"], 1)
        self.assertEqual(payload["unique_literal_namespaces"], ["XY-P"])
        self.assertEqual(payload["macro_identity_exact_count"], 1)
        self.assertEqual(payload["exact_microvariant_count"], 1)
        self.assertEqual(payload["blocked"].get("NUMBER_NAMESPACE_ABSENT"), 1)

    def test_safety_summary_is_read_only_and_has_no_alias_table(self):
        summary = probe.safe_summary()
        self.assertTrue(summary["literal_provider_namespace_only"])
        self.assertTrue(summary["tcgdex_exact_coordinate_required"])
        self.assertTrue(summary["microvariant_exact_required"])
        self.assertFalse(summary["numeric_denominator_as_set_id"])
        for key in (
            "fuzzy_matching",
            "translation_assumed",
            "provider_set_alias_table_used",
            "robot_kb_write",
            "sale_transaction_stored",
            "sale_transaction_ready",
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
