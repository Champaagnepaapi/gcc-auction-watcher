from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "mac" / "robot-kb-local" / "robot_kb_ebay_corroborated_import.py"
)
SPEC = importlib.util.spec_from_file_location(
    "robot_kb_ebay_corroborated_import", MODULE_PATH
)
assert SPEC and SPEC.loader
importer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = importer
SPEC.loader.exec_module(importer)

from robot_kb.domain import ResolutionState  # noqa: E402
from robot_kb.repository import IdempotencyConflict, KnowledgeBase  # noqa: E402


GCC_ID = "3edd662b-258c-4d73-bd76-5078a48bd02c"
GCC_URL = f"https://gradedcardcenter.com/item/{GCC_ID}"
ITEM_ID = "287464263284"


def target() -> importer.BenchmarkTarget:
    return importer.BenchmarkTarget(
        gcc_url=GCC_URL,
        title="PSA 10 N's Zoroark Ex",
        card_set="Mega Dream Ex",
        collector_number="#242/193",
        language="JA",
        grader="PSA",
        grade="10",
        year=2025,
    )


def candidate(**overrides):
    values = {
        "item_id": ITEM_ID,
        "title": "PSA 10 N's Zoroark ex SAR 242/193 MEGA Dream ex M2a Japanese Pokemon Card 2025",
        "date_sold": "2026-08-01",
        "sale_price_minor": 13000,
        "currency": "USD",
        "buying_format": "Buy It Now",
        "accepted_offer_ambiguous": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def corroboration(**overrides) -> importer.CorroborationRecord:
    values = {
        "item_id": ITEM_ID,
        "source": "PSA Sales History",
        "source_url": "https://www.psacard.com/cert/145414399/psa",
        "verified_at": "2026-08-29T07:00:00+00:00",
        "gcc_url": GCC_URL,
        "title": "PSA 10 N's Zoroark Ex",
        "card_set": "Mega Dream Ex",
        "collector_number": "#242/193",
        "language": "JA",
        "grader": "PSA",
        "grade": "10",
        "year": 2025,
        "date_sold": "2026-08-01",
        "sale_price_minor": 13000,
        "currency": "USD",
        "exact_identity_proven": True,
        "microvariant_compatible_proven": True,
        "sale_status_proven": True,
        "final_price_semantics_proven": True,
        "best_offer": False,
    }
    values.update(overrides)
    return importer.CorroborationRecord(**values)


def report(candidate_row=None, **overrides):
    c = candidate_row or candidate()
    payload = {
        "mode": "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK",
        "robot_kb_write": False,
        "v4_economic_use": False,
        "targets": [
            {
                "target": {
                    "gcc_url": GCC_URL,
                    "title": "PSA 10 N's Zoroark Ex",
                    "card_set": "Mega Dream Ex",
                    "collector_number": "#242/193",
                    "language": "JA",
                    "grader": "PSA",
                    "grade": "10",
                    "year": 2025,
                },
                "manual_review": [
                    {
                        "item_id": c.item_id,
                        "title": c.title,
                        "date_sold": c.date_sold,
                        "sale_price_minor": c.sale_price_minor,
                        "currency": c.currency,
                        "buying_format": c.buying_format,
                        "accepted_offer_ambiguous": c.accepted_offer_ambiguous,
                        "classification": "CORROBORATED_SOLD",
                        "reasons": ["untrusted report label; importer must revalidate"],
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def create_card(kb: KnowledgeBase) -> str:
    set_id = kb.create_canonical_set("mega-dream-ex", "Mega Dream Ex")
    family_id = kb.create_card_family(set_id, "242/193", "N's Zoroark ex")
    localized_id = kb.create_localized_card(
        family_id,
        "ja",
        "N's Zoroark ex",
        localized_set_name="Mega Dream Ex",
    )
    profile_id = kb.create_variant_profile(
        {
            "edition_stamp": "NO_FIRST_EDITION_STAMP",
            "shadow_treatment": "SHADOWED",
        }
    )
    kb.allow_variant_profile(family_id, profile_id)
    return kb.create_canonical_card(localized_id, profile_id)


def link_gcc(kb: KnowledgeBase, card_id: str) -> None:
    source_id = kb.create_source_system("gcc", "GCC Marketplace", "LISTING_PLATFORM")
    object_id = kb.create_external_object(source_id, "LISTING", GCC_ID)
    identifier_id = kb.add_external_identifier(
        object_id,
        "GCC_LISTING_ID",
        GCC_ID,
    )
    kb.link_identifier(
        identifier_id,
        ResolutionState.PROVEN,
        canonical_card_id=card_id,
    )


class CorroboratedSelectionTests(unittest.TestCase):
    def test_report_label_is_not_trusted_and_valid_evidence_is_rechecked(self):
        record = corroboration()
        selected_target, selected_candidate, selected_record = importer.select_corroborated_item(
            report(),
            {ITEM_ID: record},
            ITEM_ID,
        )
        self.assertEqual(selected_target.gcc_url, GCC_URL)
        self.assertEqual(selected_candidate.item_id, ITEM_ID)
        self.assertIs(selected_record, record)

    def test_best_offer_is_blocked_even_if_report_claims_corroborated(self):
        best_offer = candidate(
            buying_format="Best Offer",
            accepted_offer_ambiguous=True,
        )
        with self.assertRaisesRegex(
            importer.CorroboratedImportError,
            "exactly one CORROBORATED_SOLD",
        ):
            importer.select_corroborated_item(
                report(best_offer),
                {ITEM_ID: corroboration()},
                ITEM_ID,
            )

    def test_date_mismatch_is_blocked(self):
        with self.assertRaisesRegex(
            importer.CorroboratedImportError,
            "exactly one CORROBORATED_SOLD",
        ):
            importer.select_corroborated_item(
                report(),
                {ITEM_ID: corroboration(date_sold="2026-08-02")},
                ITEM_ID,
            )

    def test_non_fail_closed_benchmark_flags_are_blocked(self):
        with self.assertRaisesRegex(
            importer.CorroboratedImportError,
            "safety flags",
        ):
            importer.select_corroborated_item(
                report(robot_kb_write=True),
                {ITEM_ID: corroboration()},
                ITEM_ID,
            )


class CorroboratedPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()
        self.card_id = create_card(self.kb)

    def tearDown(self) -> None:
        self.kb.close()

    def test_missing_proven_gcc_mapping_fails_closed(self):
        with self.assertRaisesRegex(
            importer.CorroboratedImportError,
            "exactly one PROVEN canonical-card link",
        ):
            importer.resolve_gcc_canonical_card(self.kb, GCC_URL)

    def test_corroborated_sale_is_sealed_once_with_exact_card_and_day_precision(self):
        link_gcc(self.kb, self.card_id)
        result = importer.persist_corroborated_sale(
            self.kb,
            target(),
            candidate(),
            corroboration(),
        )
        self.assertEqual(result["canonical_card_id"], self.card_id)
        self.assertEqual(result["sale_transactions_stored"], 1)
        self.assertEqual(result["duplicate_sale_replays"], 0)

        rows = self.kb.connection.execute(
            """
            SELECT id, canonical_card_id, event_at, event_time_precision,
                   source_native_record_id, source_record_id
            FROM market_observation
            WHERE observation_type = 'SALE_TRANSACTION'
            """
        ).fetchall()
        self.assertEqual(len(rows), 1)
        sale = rows[0]
        self.assertEqual(sale["canonical_card_id"], self.card_id)
        self.assertEqual(sale["source_native_record_id"], ITEM_ID)
        self.assertEqual(sale["event_time_precision"], "DAY")
        self.assertTrue(str(sale["event_at"]).startswith("2026-08-01T00:00:00"))

        fact = self.kb.connection.execute(
            "SELECT transaction_status, sale_occurred_at FROM sale_transaction WHERE observation_id = ?",
            (sale["id"],),
        ).fetchone()
        self.assertEqual(fact["transaction_status"], "COMPLETED")
        self.assertTrue(str(fact["sale_occurred_at"]).startswith("2026-08-01T00:00:00"))

        prices = self.kb.connection.execute(
            """
            SELECT component_type, amount_minor, currency
            FROM price_component WHERE observation_id = ?
            """,
            (sale["id"],),
        ).fetchall()
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["component_type"], "ITEM_PRICE")
        self.assertEqual(prices[0]["amount_minor"], 13000)
        self.assertEqual(prices[0]["currency"], "USD")

        raw = self.kb.raw_source_payload(sale["source_record_id"])
        self.assertEqual(raw["provider_candidate"]["item_id"], ITEM_ID)
        self.assertEqual(raw["independent_corroboration"]["source"], "PSA Sales History")
        self.assertNotIn("api_key", raw)

    def test_identical_replay_does_not_duplicate_sale(self):
        link_gcc(self.kb, self.card_id)
        importer.persist_corroborated_sale(
            self.kb,
            target(),
            candidate(),
            corroboration(),
        )
        replay = importer.persist_corroborated_sale(
            self.kb,
            target(),
            candidate(),
            corroboration(),
        )
        count = self.kb.connection.execute(
            "SELECT COUNT(*) AS n FROM market_observation WHERE observation_type='SALE_TRANSACTION'"
        ).fetchone()["n"]
        self.assertEqual(count, 1)
        self.assertEqual(replay["sale_transactions_stored"], 0)
        self.assertEqual(replay["duplicate_sale_replays"], 1)

    def test_same_item_with_new_corrobated_date_conflicts_in_p3(self):
        link_gcc(self.kb, self.card_id)
        importer.persist_corroborated_sale(
            self.kb,
            target(),
            candidate(),
            corroboration(),
        )
        changed_candidate = candidate(date_sold="2026-08-02")
        changed_record = replace(corroboration(), date_sold="2026-08-02")
        with self.assertRaises(IdempotencyConflict):
            importer.persist_corroborated_sale(
                self.kb,
                target(),
                changed_candidate,
                changed_record,
            )


if __name__ == "__main__":
    unittest.main()
