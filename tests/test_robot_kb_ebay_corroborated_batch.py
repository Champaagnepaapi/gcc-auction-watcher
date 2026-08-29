from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "mac" / "robot-kb-local" / "robot_kb_ebay_corroborated_batch.py"
)
SPEC = importlib.util.spec_from_file_location(
    "robot_kb_ebay_corroborated_batch", MODULE_PATH
)
assert SPEC and SPEC.loader
batch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = batch
SPEC.loader.exec_module(batch)


GCC_ID = "3edd662b-258c-4d73-bd76-5078a48bd02c"
GCC_URL = f"https://gradedcardcenter.com/item/{GCC_ID}"
ITEM_ID = "287464263284"


@dataclass(frozen=True)
class FakePlan:
    tcgdex_card_id: str = "M2a-242"
    tcgdex_set_id: str = "M2a"
    tcgdex_set_name: str = "Mega Dream Ex"
    tcgdex_name: str = "N's Zoroark Ex"
    language_code: str = "ja"
    collector_number: str = "242/193"
    finish: str = "HOLO"
    edition_stamp: str = "NO_FIRST_EDITION_STAMP"
    resolver_reason: str = "TCGDEX_EXACT_SET_LOCALID"


def target(**overrides):
    values = {
        "gcc_url": GCC_URL,
        "title": "PSA 10 N's Zoroark Ex",
        "card_set": "Mega Dream Ex",
        "collector_number": "#242/193",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
        "year": 2025,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def identity(**overrides):
    values = {
        "listing_id": GCC_ID,
        "title": "PSA 10 N's Zoroark Ex",
        "card_set": "Mega Dream Ex",
        "collector_number": "#242/193",
        "language_code": "ja",
        "grader": "PSA",
        "grade": "10",
        "year": 2025,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def candidate(item_id=ITEM_ID):
    return SimpleNamespace(item_id=item_id)


def record(item_id=ITEM_ID):
    return SimpleNamespace(
        item_id=item_id,
        date_sold="2026-08-01",
        sale_price_minor=13000,
        currency="USD",
        source="PSA Similar Sales",
    )


class BoundsTests(unittest.TestCase):
    def test_selection_is_sorted_and_bounded(self):
        corroborations = {"3": object(), "1": object(), "2": object()}
        self.assertEqual(batch._selected_item_ids(corroborations, 2), ["1", "2"])

    def test_limit_is_hard_capped(self):
        with self.assertRaisesRegex(batch.CorroboratedBatchError, "between 1 and 50"):
            batch._validate_limit(51)
        with self.assertRaisesRegex(batch.CorroboratedBatchError, "between 1 and 50"):
            batch._validate_limit(0)

    def test_write_requires_explicit_confirmation_before_input_files(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = batch.main(
                [
                    "write",
                    "--benchmark-file",
                    "/does/not/exist.json",
                    "--corroboration-file",
                    "/does/not/exist.json",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertIn("requires --confirm-write", payload["error"])
        self.assertFalse(payload["robot_kb_write"])


class IdentityConsistencyTests(unittest.TestCase):
    def test_exact_target_matches_retained_gcc(self):
        batch._assert_target_matches_retained_gcc(target(), identity())

    def test_target_conflict_is_blocking(self):
        with self.assertRaisesRegex(
            batch.CorroboratedBatchError,
            "collector number conflicts",
        ):
            batch._assert_target_matches_retained_gcc(
                target(collector_number="#241/193"),
                identity(),
            )


class BatchOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.kb = SimpleNamespace()
        self.report = {"mode": "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK"}
        self.corroborations = {ITEM_ID: object()}
        self.target = target()
        self.candidate = candidate()
        self.record = record()
        self.prepared = {
            "identity": identity(),
            "plan": FakePlan(),
            "listing_id": GCC_ID,
        }

    def _selection_patch(self):
        return mock.patch.object(
            batch,
            "select_corroborated_item",
            return_value=(self.target, self.candidate, self.record),
        )

    def test_validate_prepares_missing_canonical_without_writes(self):
        with (
            self._selection_patch(),
            mock.patch.object(batch, "_existing_canonical_card", return_value=None),
            mock.patch.object(
                batch,
                "_prepare_canonicalization",
                return_value=self.prepared,
            ),
            mock.patch.object(batch, "persist_plan") as persist_plan,
            mock.patch.object(batch, "persist_corroborated_sale") as persist_sale,
        ):
            summary, code = batch.run_batch(
                self.kb,
                mode="validate",
                report=self.report,
                corroborations=self.corroborations,
                max_items=20,
            )

        self.assertEqual(code, 0)
        self.assertEqual(summary["corroborated_sold"], 1)
        self.assertEqual(summary["canonicalization_ready"], 1)
        self.assertEqual(summary["sale_transactions_stored"], 0)
        self.assertFalse(summary["robot_kb_write"])
        self.assertEqual(summary["items"][0]["status"], "READY")
        self.assertTrue(summary["items"][0]["tcgdex_exact"])
        self.assertTrue(summary["items"][0]["microvariant_proven"])
        persist_plan.assert_not_called()
        persist_sale.assert_not_called()

    def test_write_canonicalizes_then_stores_sale(self):
        sale_result = {
            "canonical_card_id": "card_exact",
            "sale_transactions_stored": 1,
            "duplicate_sale_replays": 0,
            "observations_replayed": 0,
        }
        with (
            self._selection_patch(),
            mock.patch.object(batch, "_existing_canonical_card", return_value=None),
            mock.patch.object(
                batch,
                "_prepare_canonicalization",
                return_value=self.prepared,
            ),
            mock.patch.object(
                batch,
                "persist_plan",
                return_value={"canonical_card_id": "card_exact"},
            ) as persist_plan,
            mock.patch.object(
                batch,
                "validate_database_target",
                return_value="card_exact",
            ),
            mock.patch.object(
                batch,
                "persist_corroborated_sale",
                return_value=sale_result,
            ) as persist_sale,
        ):
            summary, code = batch.run_batch(
                self.kb,
                mode="write",
                report=self.report,
                corroborations=self.corroborations,
                max_items=20,
            )

        self.assertEqual(code, 0)
        self.assertEqual(summary["canonicalizations_persisted"], 1)
        self.assertEqual(summary["sale_transactions_stored"], 1)
        self.assertTrue(summary["robot_kb_write"])
        self.assertEqual(summary["items"][0]["status"], "SALE_STORED")
        persist_plan.assert_called_once()
        persist_sale.assert_called_once()

    def test_existing_proven_canonical_skips_tcgdex_bootstrap(self):
        sale_result = {
            "canonical_card_id": "card_existing",
            "sale_transactions_stored": 0,
            "duplicate_sale_replays": 1,
            "observations_replayed": 1,
        }
        with (
            self._selection_patch(),
            mock.patch.object(
                batch,
                "_existing_canonical_card",
                return_value="card_existing",
            ),
            mock.patch.object(batch, "_prepare_canonicalization") as prepare,
            mock.patch.object(
                batch,
                "persist_corroborated_sale",
                return_value=sale_result,
            ),
        ):
            summary, code = batch.run_batch(
                self.kb,
                mode="write",
                report=self.report,
                corroborations=self.corroborations,
                max_items=20,
            )

        self.assertEqual(code, 0)
        self.assertEqual(summary["canonical_already_proven"], 1)
        self.assertEqual(summary["duplicate_sale_replays"], 1)
        self.assertEqual(summary["items"][0]["status"], "DUPLICATE_REPLAY")
        prepare.assert_not_called()

    def test_non_corroborated_item_is_blocked_before_identity_or_write(self):
        with (
            mock.patch.object(
                batch,
                "select_corroborated_item",
                side_effect=batch.CorroboratedImportError(
                    "requested item must resolve to exactly one CORROBORATED_SOLD target; got 0"
                ),
            ),
            mock.patch.object(batch, "_existing_canonical_card") as existing,
            mock.patch.object(batch, "persist_plan") as persist_plan,
            mock.patch.object(batch, "persist_corroborated_sale") as persist_sale,
        ):
            summary, code = batch.run_batch(
                self.kb,
                mode="write",
                report=self.report,
                corroborations=self.corroborations,
                max_items=20,
            )

        self.assertEqual(code, 0)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["corroborated_sold"], 0)
        self.assertFalse(summary["robot_kb_write"])
        self.assertEqual(summary["items"][0]["status"], "BLOCKED")
        existing.assert_not_called()
        persist_plan.assert_not_called()
        persist_sale.assert_not_called()

    def test_one_blocked_item_does_not_weaken_or_abort_next_item(self):
        blocked_id = "111111111111"
        good_id = "222222222222"
        corroborations = {blocked_id: object(), good_id: object()}

        def select(_report, _corroborations, item_id):
            if item_id == blocked_id:
                raise batch.CorroboratedImportError("independent corroboration rejected")
            return self.target, candidate(good_id), record(good_id)

        with (
            mock.patch.object(batch, "select_corroborated_item", side_effect=select),
            mock.patch.object(
                batch,
                "_existing_canonical_card",
                return_value="card_existing",
            ),
        ):
            summary, code = batch.run_batch(
                self.kb,
                mode="validate",
                report=self.report,
                corroborations=corroborations,
                max_items=20,
            )

        self.assertEqual(code, 0)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["corroborated_sold"], 1)
        self.assertEqual([item["status"] for item in summary["items"]], ["BLOCKED", "READY"])

    def test_unexpected_error_is_fail_visible(self):
        with mock.patch.object(
            batch,
            "select_corroborated_item",
            side_effect=RuntimeError("boom"),
        ):
            summary, code = batch.run_batch(
                self.kb,
                mode="validate",
                report=self.report,
                corroborations=self.corroborations,
                max_items=20,
            )

        self.assertEqual(code, 1)
        self.assertEqual(summary["unexpected_errors"], 1)
        self.assertEqual(summary["items"][0]["status"], "ERROR")
        self.assertFalse(summary["robot_kb_write"])


if __name__ == "__main__":
    unittest.main()
