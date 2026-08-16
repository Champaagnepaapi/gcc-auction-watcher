from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

import japan_edge_hunter as base
import japan_edge_ppt_shadow as ppt


def identity(**overrides):
    values = dict(
        name="Bulbasaur",
        set_name="Pokemon Card 151",
        number="166/165",
        language="Japanese",
        grader="PSA",
        grade="10",
        year=2023,
        edition="",
        attribute="",
        variety="",
        rarity="Art Rare",
    )
    values.update(overrides)
    return base.Identity(**values)


def row(**overrides):
    values = {
        "name": "Bulbasaur",
        "setName": "Pokemon Card 151",
        "cardNumber": "166/165",
        "language": "Japanese",
        "tcgPlayerId": "jp-166",
        "rarity": "Art Rare",
    }
    values.update(overrides)
    return values


class FakeResponse:
    def __init__(self, payload, status=200, consumed=1, remaining=19990):
        self._payload = payload
        self.status_code = status
        self.headers = {
            "X-Api-Calls-Consumed": str(consumed),
            "X-Ratelimit-Daily-Remaining": str(remaining),
        }

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FakeFx:
    def convert(self, amount: Decimal, source_currency: str, target_currency: str, on_date):
        self.last = (amount, source_currency, target_currency, on_date)
        return amount * Decimal("0.90")


class JapanEdgePptShadowTests(unittest.TestCase):
    def test_exact_japanese_set_number_is_macro_match(self):
        match = ppt.match_japanese_identity(identity(), [row()])
        self.assertEqual(match.status, "EXACT")
        self.assertEqual(match.reason, "JP_LANGUAGE_SET_NUMBER_AND_VARIANT")

    def test_english_physical_card_is_never_relabelled_japanese(self):
        match = ppt.match_japanese_identity(identity(language="English"), [row()])
        self.assertEqual(match.status, "BLOCKED_LANGUAGE")

    def test_sensitive_master_ball_variant_requires_provider_proof(self):
        match = ppt.match_japanese_identity(
            identity(attribute="Master Ball Reverse"),
            [row(printing="Reverse Holofoil")],
        )
        self.assertEqual(match.status, "MICROVARIANT_UNPROVEN")

    def test_sensitive_master_ball_variant_accepts_explicit_provider_proof(self):
        match = ppt.match_japanese_identity(
            identity(attribute="Master Ball"),
            [row(printing="Master Ball")],
        )
        self.assertEqual(match.status, "EXACT")

    def test_every_provider_request_is_explicitly_japanese(self):
        shallow = {"data": [row()]}
        deep_row = row(
            ebay={
                "salesByGrade": {
                    "psa10": {
                        "count": 12,
                        "averagePrice": 100,
                        "medianPrice": 110,
                        "smartMarketPrice": {"price": 105, "confidence": "high"},
                        "lastSaleDate": "2026-08-15",
                    }
                },
                "priceHistory": {
                    "psa10": {
                        "2026-07-20": {"count": 2, "average": 90},
                        "2026-08-10": {"count": 3, "average": 110},
                    }
                },
            }
        )
        session = FakeSession([FakeResponse(shallow), FakeResponse({"data": deep_row})])
        budget = ppt.PptBudget(interval_seconds=0)
        snapshot = ppt.fetch_japanese_snapshot(
            identity(),
            api_key="test-key",
            budget=budget,
            session=session,
            fx=FakeFx(),
        )
        self.assertEqual(snapshot.status, "MATCHED")
        self.assertEqual(snapshot.evidence_class, "SOLD_AGGREGATED")
        self.assertEqual(snapshot.correlation_group, "EBAY_GRADED_AGGREGATE")
        self.assertEqual(snapshot.sales_count, 12)
        self.assertAlmostEqual(snapshot.fair_value_eur, 94.5)
        self.assertEqual(len(session.calls), 2)
        for _, kwargs in session.calls:
            self.assertEqual(kwargs["params"].get("language"), "japanese")

    def test_ppt_and_poketrace_never_increment_independent_market_count(self):
        report = {
            "opportunities": [
                {
                    "identity": identity().__dict__,
                    "external_reference": {"fair_eur": 100.0, "source": "PokeTrace/eBay SOLD"},
                    "market_decision": {"status": "MULTIMARKET_CONFIRMED", "should_notify": True},
                }
            ]
        }
        original_decision = dict(report["opportunities"][0]["market_decision"])
        shallow = {"data": [row()]}
        deep = row(
            ebay={
                "salesByGrade": {
                    "psa10": {
                        "count": 8,
                        "averagePrice": 100,
                        "medianPrice": 100,
                        "smartMarketPrice": {"price": 100},
                        "lastSaleDate": "2026-08-15",
                    }
                },
                "priceHistory": {},
            }
        )
        output = ppt.enrich_report(
            report,
            api_key="test-key",
            budget=ppt.PptBudget(interval_seconds=0),
            session=FakeSession([FakeResponse(shallow), FakeResponse({"data": deep})]),
            fx=FakeFx(),
            max_candidates=1,
        )
        shadow = output["opportunities"][0]["ppt_japanese_shadow"]
        self.assertEqual(shadow["independent_market_increment"], 0)
        self.assertEqual(shadow["production_decision_use"], False)
        self.assertEqual(shadow["notification_use"], False)
        self.assertEqual(output["opportunities"][0]["market_decision"], original_decision)

    def test_budget_fails_closed_without_quota_headers(self):
        budget = ppt.PptBudget(interval_seconds=0)
        budget.record({})
        self.assertEqual(budget.blocked_reason, "CREDIT_HEADER_REQUIRED")
        self.assertFalse(budget.can_call())

    def test_live_workflow_is_manual_bounded_and_notification_free(self):
        workflow = Path('.github/workflows/japan-edge-ppt-live-once.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('\n  schedule:', workflow)
        self.assertNotIn('\n  push:', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertIn('POKEMONPRICETRACKER_API_KEY: ${{ secrets.POKEMONPRICETRACKER_API_KEY }}', workflow)
        self.assertIn('JAPAN_EDGE_NOTIFY_ENABLED: "false"', workflow)
        self.assertIn('NTFY_TOPIC: ""', workflow)
        self.assertIn('JAPAN_EDGE_PPT_MAX_CANDIDATES: "4"', workflow)
        self.assertIn('JAPAN_EDGE_PPT_MAX_HTTP_CALLS: "8"', workflow)
        self.assertIn('JAPAN_EDGE_PPT_MAX_CREDITS: "40"', workflow)
        self.assertIn('JAPAN_EDGE_PPT_DAILY_REMAINING_FLOOR: "15000"', workflow)


if __name__ == "__main__":
    unittest.main()