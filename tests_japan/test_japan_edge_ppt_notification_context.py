from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import japan_edge_hunter as base
import japan_edge_hunter_v3 as v3
import japan_edge_ppt_notification_context as context


def opportunity(*, fair=100.0, landed=66.98):
    identity = base.Identity(
        name="Bulbasaur",
        set_name="151",
        number="166/165",
        language="Japanese",
        grader="PSA",
        grade="10",
        year=2023,
    )
    return base.Opportunity(
        provider="yahoo_fleamarket",
        url="https://paypayfleamarket.yahoo.co.jp/item/z-test",
        title="Bulbasaur 166/165 PSA10 Japanese",
        price_jpy=10500,
        ask_eur=57.09,
        ask_chf=54.0,
        landed_eur=landed,
        landed_chf=63.0,
        fair_eur=fair,
        discount_pct=33.0,
        gcc_sold_count=2,
        gcc_recent_90=2,
        evidence="GCC_EXACT_SOLD_RECENT",
        identity=identity,
    )


class NoNetworkSession:
    def get(self, *args, **kwargs):
        raise AssertionError("network must not be called")


class JapanEdgePptNotificationContextTests(unittest.TestCase):
    def test_notification_displays_gcc_and_ppt_as_two_separate_market_views(self):
        op = opportunity()
        external = v3.ExternalReference(status="CLEAN_NO_MATCH")
        decision = v3.classify_market(op, external, 30)
        ppt = context.PptNotificationContext(
            status="MATCHED",
            fair_eur=76.94,
            discount_pct=12.9,
            sales_count=193,
            last_sale_date="2026-08-13",
        )

        response = Mock()
        response.raise_for_status.return_value = None
        with patch.object(v3.requests, "post", return_value=response) as post:
            v3.notify(op, external, decision, "https://ntfy.sh", "topic", ppt)

        body = post.call_args.kwargs["data"].decode()
        self.assertIn("GCC exact JP PSA10: €100 | 2 SOLD (2 <90j)", body)
        self.assertIn("→ décote vs GCC: -33%", body)
        self.assertIn("PPT eBay agrégé JP PSA10: €77 | 193 ventes agrégées", body)
        self.assertIn("dernière 2026-08-13", body)
        self.assertIn("→ décote vs PPT: -13%", body)
        self.assertIn("PPT = CONTEXTE AFFICHÉ, PAS DÉCIDEUR", body)
        self.assertNotIn("Fair PPT+GCC", body)

    def test_ppt_context_cannot_change_existing_market_decision(self):
        op = opportunity(fair=100.0, landed=66.98)
        external = v3.ExternalReference(status="CLEAN_NO_MATCH")
        before = v3.classify_market(op, external, 30)

        _ppt = context.PptNotificationContext(
            status="MATCHED",
            fair_eur=76.94,
            discount_pct=12.9,
            sales_count=193,
        )
        after = v3.classify_market(op, external, 30)

        self.assertEqual(before, after)
        self.assertEqual(after.status, "GCC_ONLY_UNCONFIRMED")
        self.assertTrue(after.should_notify)
        self.assertEqual(after.gcc_fair_eur, 100.0)

    def test_disabled_context_is_zero_network(self):
        client = context.PptNotificationClient(
            enabled=False,
            api_key="not-used",
            max_candidates=4,
            budget=context.shadow.PptBudget(interval_seconds=0),
            session=NoNetworkSession(),
            fx=Mock(),
            timeout=1.0,
        )
        result = client.fetch(opportunity(), datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertEqual(result.status, "DISABLED")
        self.assertFalse(result.notification_display_use)
        self.assertEqual(client.budget.http_calls, 0)
        self.assertEqual(client.budget.credits, 0)

    def test_matched_snapshot_calculates_discount_from_landed_price(self):
        client = context.PptNotificationClient(
            enabled=True,
            api_key="fake",
            max_candidates=4,
            budget=context.shadow.PptBudget(interval_seconds=0),
            session=NoNetworkSession(),
            fx=Mock(),
            timeout=1.0,
        )
        snapshot = context.shadow.PptJapaneseSnapshot(
            status="MATCHED",
            fair_value_eur=76.94,
            sales_count=193,
            last_sale_date="2026-08-13",
            momentum_30d_pct=7.6,
            momentum_90d_pct=-7.4,
            momentum_180d_pct=15.6,
        )
        with patch.object(
            context.shadow,
            "fetch_japanese_snapshot",
            return_value=(snapshot, {}),
        ):
            result = client.fetch(
                opportunity(landed=66.98),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

        self.assertEqual(result.status, "MATCHED")
        self.assertEqual(result.fair_eur, 76.94)
        self.assertEqual(result.discount_pct, 12.9)
        self.assertEqual(result.sales_count, 193)
        self.assertEqual(client.attempted, 1)
        self.assertEqual(client.matched, 1)

    def test_context_summary_is_explicitly_non_decision(self):
        client = context.PptNotificationClient(
            enabled=True,
            api_key="fake",
            max_candidates=4,
            budget=context.shadow.PptBudget(interval_seconds=0),
            session=NoNetworkSession(),
            fx=Mock(),
            timeout=1.0,
        )
        summary = client.summary()
        self.assertEqual(summary["evidence_class"], "SOLD_AGGREGATED")
        self.assertEqual(summary["correlation_group"], "EBAY_GRADED_AGGREGATE")
        self.assertIs(summary["production_decision_use"], False)
        self.assertIs(summary["notification_decision_use"], False)
        self.assertIs(summary["notification_display_use"], True)


if __name__ == "__main__":
    unittest.main()
