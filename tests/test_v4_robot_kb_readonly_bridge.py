from __future__ import annotations

import importlib.util
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as multimarket
import v4_robot_kb_readonly_market as bridge_client
import run_watcher_multimarket_resilient as resilient


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _lot():
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test",
        title="Poochyena",
        current_price=30.0,
        source_type="auction",
        grader="PSA",
        grade="10",
        card_set="VSTAR Universe",
        card_number="208/172",
        language="Japanese",
    )


def _canonical():
    return multimarket.CanonicalCard(
        status="EXACT",
        card_id="swsh12pt5gg-GG33",
        set_id="swsh12pt5gg",
        set_name="VSTAR Universe",
        full_number="208/172",
        name="Poochyena",
        language_code="ja",
    )


def _load_service_module():
    path = Path(__file__).resolve().parents[1] / "mac" / "robot-kb-local" / "robot_kb_v4_readonly_bridge.py"
    spec = importlib.util.spec_from_file_location("robot_kb_v4_readonly_bridge_tested", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RobotKbReadonlyBridgeTests(unittest.TestCase):
    def setUp(self):
        bridge_client.reset_run_state()

    def test_service_filter_requires_proven_grader_grade_completed_sealed(self):
        service = _load_service_module()
        good = {
            "grader_resolution_state": "PROVEN",
            "grader_value_json": json.dumps("PSA"),
            "grade_resolution_state": "PROVEN",
            "grade_value_json": json.dumps("10"),
            "transaction_status": "COMPLETED",
            "lifecycle_state": "SEALED",
            "source_code": "cardova",
            "sold_at": "2026-09-01T12:00:00+00:00",
            "amount_minor": 5000,
            "currency": "EUR",
            "component_type": "HAMMER_PRICE",
        }
        bad_grade = dict(good, grade_value_json=json.dumps("9"))
        bad_state = dict(good, transaction_status="UNKNOWN")
        bad_resolution = dict(good, grader_resolution_state="SUPPORTED")
        rows = service.filter_exact_sold_rows(
            [good, bad_grade, bad_state, bad_resolution], grader="PSA", grade="10"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_code"], "cardova")
        self.assertEqual(rows[0]["component_type"], "HAMMER_PRICE")

    def test_client_uses_exact_non_gcc_completed_sold_and_excludes_gcc_history(self):
        payload = {
            "schema_version": 1,
            "identity": {
                "tcgdex_card_id": "swsh12pt5gg-GG33",
                "grader": "PSA",
                "grade": "10",
                "proof": "PROVEN_TCGDEX_AND_GRADE",
            },
            "sales": [
                {
                    "source_code": "gcc",
                    "transaction_status": "COMPLETED",
                    "sold_at": "2026-09-01T12:00:00+00:00",
                    "amount_minor": 1000,
                    "currency": "EUR",
                    "component_type": "ITEM_PRICE",
                },
                {
                    "source_code": "cardova",
                    "transaction_status": "COMPLETED",
                    "sold_at": "2026-08-30T12:00:00+00:00",
                    "amount_minor": 5000,
                    "currency": "EUR",
                    "component_type": "HAMMER_PRICE",
                },
                {
                    "source_code": "cardova",
                    "transaction_status": "COMPLETED",
                    "sold_at": "2026-08-20T12:00:00+00:00",
                    "amount_minor": 5200,
                    "currency": "EUR",
                    "component_type": "HAMMER_PRICE",
                },
            ],
        }
        session = _Session(_Response(200, payload))
        with patch.dict(
            os.environ,
            {
                "ROBOT_KB_V4_READONLY_URL": "https://kb-bridge.example.test",
                "ROBOT_KB_V4_READONLY_TOKEN": "x" * 32,
                "ROBOT_KB_V4_READONLY_MAX_REQUESTS_PER_RUN": "50",
            },
            clear=False,
        ):
            evidence = bridge_client.robot_kb_evidence_for_lot(
                _lot(),
                _canonical(),
                now=datetime(2026, 9, 6, tzinfo=timezone.utc),
                session=session,
            )
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(evidence.source, "robot_kb")
        self.assertEqual(evidence.estimate.central, 51.0)
        self.assertEqual(len(evidence.comparables), 2)
        self.assertNotIn("gcc", " ".join(evidence.estimate.source_counts))
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("x" * 32, session.calls[0][0])
        self.assertEqual(session.calls[0][1]["headers"]["Authorization"], "Bearer " + "x" * 32)

    def test_remote_plain_http_bridge_is_rejected_before_network(self):
        session = _Session(_Response(200, {}))
        with patch.dict(
            os.environ,
            {
                "ROBOT_KB_V4_READONLY_URL": "http://kb-bridge.example.test",
                "ROBOT_KB_V4_READONLY_TOKEN": "x" * 32,
            },
            clear=False,
        ):
            evidence = bridge_client.robot_kb_evidence_for_lot(
                _lot(), _canonical(), session=session
            )
        self.assertEqual(evidence.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(session.calls, [])

    def test_bridge_failure_does_not_hide_existing_provider(self):
        existing = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(_lot()),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "poketrace",
            estimate=watcher.MarketEstimate(
                low=48.0,
                central=50.0,
                high=52.0,
                kept_comparables=[],
                rejected_outliers=[],
                recent_90_count=0,
                dated_count=0,
                liquidity="moyenne",
                dispersion="faible",
                confidence="moyenne",
                adaptive_discount_pct=20.0,
                rationale="existing",
                source_counts={"poketrace": 3},
                exact_grade_count=3,
                same_grader_count=3,
                source_consistent=True,
            ),
        )
        original = multimarket._poketrace_evidence
        try:
            def current(lot, canonical, budget, now):
                return existing
            multimarket._poketrace_evidence = current
            with patch.object(
                bridge_client,
                "robot_kb_evidence_for_lot",
                return_value=watcher.ExternalMarketEvidence(
                    watcher.external_commercial_identity_key(_lot()),
                    watcher.EXTERNAL_PROVIDER_ERROR,
                    source="robot_kb",
                    note="offline",
                ),
            ):
                bridge_client.install_v4_robot_kb_readonly_market()
                result = multimarket._poketrace_evidence(
                    _lot(), _canonical(), multimarket.RequestBudget(), datetime.now(timezone.utc)
                )
            self.assertEqual(result.source, "poketrace")
            self.assertEqual(result.strength, watcher.EVIDENCE_STRONG)
            self.assertIn("Robot KB", result.note)
        finally:
            multimarket._poketrace_evidence = original
            bridge_client.reset_run_state()

    def test_resilient_bootstrap_installs_roles_then_kb_then_mandatory_pricecharting(self):
        calls = []
        with (
            patch.object(resilient, "_ORIGINAL_PRICECHARTING_SOURCE_ROLE_INSTALL", side_effect=lambda: calls.append("roles")),
            patch.object(resilient, "install_v4_robot_kb_readonly_market", side_effect=lambda: calls.append("kb")),
            patch.object(resilient, "install_v4_pricecharting_mandatory_guide_policy", side_effect=lambda: calls.append("pricecharting")),
        ):
            resilient._install_pricecharting_and_readonly_kb_roles()
        self.assertEqual(calls, ["roles", "kb", "pricecharting"])


if __name__ == "__main__":
    unittest.main()
