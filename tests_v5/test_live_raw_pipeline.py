import builtins
import io
import os
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tests_v5.test_ebay_live_diagnostic import (
    FakeLiveSession,
    FakeResponse,
    complete_item,
    load_fixture,
    search_summary,
)
from v5.live_raw_pipeline import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_INSUFFICIENT,
    IDENTITY_OK,
    MANUAL_MARKET_VALIDATION_REQUIRED,
    NO_PERSISTENCE_MODE,
    PRODUCT_RESEARCH_MODE,
    RAW_DISCOVERY_INTERVAL_MINUTES,
    LiveRawPipelineConfig,
    LiveRawPipelineDiagnostic,
    ManualProductResearch,
    MemoryOnlySeenItemStore,
    identity_status,
    render_live_raw_pipeline_summary,
)
from v5.market_values.economic import CostModel
from v5.market_values.models import MarketValues
from v5.models import CardIdentity


WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "v5-live-raw-pipeline-diagnostic.yml"
)


def run_pipeline(item=None, session=None, config=None, **kwargs):
    chosen = deepcopy(item or complete_item())
    if session is None:
        response = FakeResponse(
            200, {"total": 1, "itemSummaries": [search_summary(chosen)]}
        )
        session = FakeLiveSession(
            search_responses={
                "EBAY_US": response,
                "EBAY_CH": FakeResponse(200, {"total": 0, "itemSummaries": []}),
            },
            detail_payloads={chosen["itemId"]: chosen},
        )
    diagnostic = LiveRawPipelineDiagnostic(
        "private-client-id",
        "private-client-secret",
        config=config or LiveRawPipelineConfig(result_limit=20),
        session=session,
        **kwargs,
    )
    captured = io.StringIO()
    with redirect_stdout(captured):
        summary = diagnostic.run()
    return diagnostic, summary, render_live_raw_pipeline_summary(summary), session, captured.getvalue()


class FixtureMarketSource:
    def __init__(self, values=None):
        self.values = values
        self.calls = 0

    def values_for(self, identity):
        self.calls += 1
        if self.values is None:
            return None
        return self.values(identity)


def complete_market_values(identity):
    return MarketValues(
        source="offline sold fixture",
        currency="USD",
        ungraded_value=Decimal("15"),
        grade8_generic_value=Decimal("40"),
        grade9_generic_value=Decimal("55"),
        psa10_value=Decimal("100"),
        matched_identity=identity,
        match_confidence=Decimal("1"),
        matched_product_id="offline-only",
    )


def complete_costs(listing):
    return CostModel(
        raw_purchase_price=listing.price,
        buyer_fees=Decimal("0"),
        domestic_shipping=Decimal("0"),
        international_shipping=Decimal("0"),
        grading_fee=Decimal("20"),
        grading_shipping=Decimal("2.50"),
        vault_fee=Decimal("0"),
        selling_fee_pct=Decimal("0"),
        selling_fixed_fee=Decimal("0"),
        fx_buffer_pct=Decimal("0"),
        other_costs=Decimal("0"),
        currency=listing.currency,
    )


class LiveRawPipelineFlowTests(unittest.TestCase):
    def test_real_browse_fixture_shape_reaches_full_manual_validation_path(self):
        diagnostic, summary, rendered, session, runtime = run_pipeline()
        self.assertTrue(summary.successful)
        self.assertEqual(summary.raw_condition_accepted, 1)
        self.assertEqual(summary.identity.ok, 1)
        self.assertEqual(summary.market.identities_evaluated, 1)
        self.assertEqual(summary.market.values_missing, 1)
        self.assertEqual(summary.market.manual_validation_required, 1)
        self.assertEqual(runtime, "")
        search_calls = [call for call in session.gets if "item_summary/search" in call[0]]
        detail_calls = [call for call in session.gets if "/buy/browse/v1/item/" in call[0]]
        self.assertEqual(len(search_calls), 1)
        self.assertEqual(search_calls[0][1]["params"]["filter"], "conditionIds:{4000}")
        self.assertEqual(len(detail_calls), 1)
        self.assertIn(MANUAL_MARKET_VALIDATION_REQUIRED.lower().replace("_", " "), rendered.lower())
        self.assertEqual(diagnostic.pricecharting.live_calls, 0)

    def test_result_limit_is_configurable_and_sent_to_browse(self):
        config = LiveRawPipelineConfig(result_limit=5)
        _, _, _, session, _ = run_pipeline(config=config)
        search = next(call for call in session.gets if "item_summary/search" in call[0])
        self.assertEqual(search[1]["params"]["limit"], "5")

    def test_condition_4000_is_accepted_and_graded_condition_is_not(self):
        _, raw_summary, _, _, _ = run_pipeline()
        graded = complete_item()
        graded["conditionId"] = "2750"
        graded["condition"] = "Professionally graded"
        _, graded_summary, _, _, _ = run_pipeline(graded)
        self.assertEqual(raw_summary.raw_condition_accepted, 1)
        self.assertEqual(graded_summary.raw_condition_accepted, 0)
        self.assertEqual(graded_summary.market.identities_evaluated, 0)

    def test_identity_ok_continues_but_ambiguous_and_insufficient_do_not_value(self):
        source = FixtureMarketSource(complete_market_values)
        _, ok, _, _, _ = run_pipeline(
            offline_market_sources=(source,), cost_factory=complete_costs
        )
        self.assertEqual(ok.identity.ok, 1)
        self.assertEqual(ok.market.values_found, 1)

        ambiguous = complete_item()
        card_name = next(
            aspect
            for aspect in ambiguous["localizedAspects"]
            if aspect["name"] == "Card Name"
        )
        card_name["value"] = ["Fixturemon", "Othermon"]
        source = FixtureMarketSource(complete_market_values)
        _, ambiguous_summary, _, _, _ = run_pipeline(
            ambiguous,
            offline_market_sources=(source,),
            cost_factory=complete_costs,
        )
        self.assertEqual(ambiguous_summary.identity.ambiguous, 1)
        self.assertEqual(ambiguous_summary.market.identities_evaluated, 0)
        self.assertEqual(source.calls, 0)

        insufficient = load_fixture("ebay_get_item_partial_fr.json")
        source = FixtureMarketSource(complete_market_values)
        _, insufficient_summary, _, _, _ = run_pipeline(
            insufficient,
            offline_market_sources=(source,),
            cost_factory=complete_costs,
        )
        self.assertEqual(insufficient_summary.identity.insufficient, 1)
        self.assertEqual(insufficient_summary.market.identities_evaluated, 0)
        self.assertEqual(source.calls, 0)

    def test_identity_status_is_conservative(self):
        self.assertEqual(identity_status(complete_market_identity()), IDENTITY_OK)
        self.assertEqual(
            identity_status(
                CardIdentity(
                    game="Pokemon TCG",
                    card_name="A",
                    set="S",
                    card_number="1/1",
                    language="English",
                    ambiguities=("ambiguous",),
                )
            ),
            IDENTITY_AMBIGUOUS,
        )
        self.assertEqual(identity_status(CardIdentity(game="Pokemon TCG")), IDENTITY_INSUFFICIENT)

    def test_back_absent_never_blocks_market_or_economic_pipeline(self):
        item = complete_item()
        item["additionalImages"] = []
        source = FixtureMarketSource(complete_market_values)
        _, summary, _, _, _ = run_pipeline(
            item,
            offline_market_sources=(source,),
            cost_factory=complete_costs,
        )
        self.assertEqual(summary.images.back_unknown, 1)
        self.assertEqual(summary.images.back_missing_pipeline_continued, 1)
        self.assertEqual(summary.images.grading_visual_confidence_reduced, 1)
        self.assertEqual(summary.market.values_found, 1)
        self.assertEqual(summary.economic.grade9_profitable, 1)

    def test_active_asking_price_alone_is_never_a_market_value(self):
        _, summary, _, _, _ = run_pipeline()
        self.assertEqual(summary.market.values_found, 0)
        self.assertEqual(summary.market.values_missing, 1)
        self.assertEqual(summary.market.manual_validation_required, 1)

    def test_listing_purchase_price_is_used_only_in_memory_for_economics(self):
        observed = []

        def costs(listing):
            observed.append(listing.price)
            return complete_costs(listing)

        source = FixtureMarketSource(complete_market_values)
        _, summary, rendered, _, _ = run_pipeline(
            offline_market_sources=(source,), cost_factory=costs
        )
        self.assertEqual(observed, [Decimal("12.50")])
        self.assertEqual(summary.economic.grade9_profitable, 1)
        self.assertNotIn("12.50", rendered)

    def test_listing_price_overrides_configured_raw_purchase_price_only(self):
        env = {
            "RAW_PURCHASE_PRICE": "999",
            "BUYER_FEES": "1",
            "DOMESTIC_SHIPPING": "2",
            "INTERNATIONAL_SHIPPING": "3",
            "GRADING_FEE": "4",
            "GRADING_SHIPPING": "5",
            "VAULT_FEE": "6",
            "SELLING_FEE_PCT": "7",
            "SELLING_FIXED_FEE": "8",
            "FX_BUFFER_PCT": "9",
            "OTHER_COSTS": "10",
        }
        with patch.dict(os.environ, env, clear=True):
            model = CostModel.from_env("USD", raw_purchase_price=Decimal("12.50"))
        self.assertEqual(model.raw_purchase_price, Decimal("12.50"))
        self.assertEqual(model.buyer_fees, Decimal("1"))

    def test_complete_market_with_missing_costs_is_cost_model_incomplete(self):
        source = FixtureMarketSource(complete_market_values)
        with patch.dict(os.environ, {}, clear=True):
            _, summary, _, _, _ = run_pipeline(offline_market_sources=(source,))
        self.assertEqual(summary.market.values_found, 1)
        self.assertEqual(summary.economic.cost_model_incomplete, 1)


class ManualResearchAndProviderSafetyTests(unittest.TestCase):
    def test_product_research_is_manual_only_and_query_stays_in_memory(self):
        research = ManualProductResearch()
        query = research.build_query(complete_market_identity())
        self.assertIsNotNone(query)
        self.assertEqual(research.mode, PRODUCT_RESEARCH_MODE)
        self.assertEqual(research.automated_calls, 0)
        self.assertIn("Fixturemon", query.as_text())
        _, summary, rendered, _, _ = run_pipeline()
        self.assertEqual(summary.market.manual_product_research_queries_possible, 1)
        self.assertEqual(summary.providers.product_research_automated_calls, 0)
        self.assertNotIn(query.as_text(), rendered)

    def test_all_external_or_paid_providers_remain_at_zero(self):
        diagnostic, summary, rendered, session, _ = run_pipeline()
        self.assertFalse(summary.providers.pricecharting_enabled)
        self.assertEqual(summary.providers.pricecharting_live_calls, 0)
        self.assertFalse(summary.providers.marketplace_insights_enabled)
        self.assertEqual(summary.providers.marketplace_insights_live_calls, 0)
        self.assertEqual(summary.providers.psa_sales_status, "UNAVAILABLE")
        self.assertEqual(diagnostic.product_research.automated_calls, 0)
        self.assertIn("CardGrader calls: 0", rendered)
        self.assertIn("Purchases: 0", rendered)
        self.assertIn("Bids: 0", rendered)
        self.assertIn("Checkout: 0", rendered)
        self.assertEqual(len(session.posts), 1)
        self.assertIn("/identity/v1/oauth2/token", session.posts[0][0])

    def test_pricecharting_is_forced_off_even_if_environment_says_true(self):
        with patch.dict(
            os.environ,
            {"PRICECHARTING_ENABLED": "true", "PRICECHARTING_TOKEN": "never-use"},
            clear=False,
        ):
            diagnostic, summary, rendered, session, _ = run_pipeline()
        self.assertFalse(diagnostic.pricecharting.config.enabled)
        self.assertEqual(summary.providers.pricecharting_live_calls, 0)
        self.assertNotIn("never-use", rendered)
        self.assertFalse(any("pricecharting.com" in call[0] for call in session.gets))


class MemoryAndPrivacyTests(unittest.TestCase):
    def test_memory_dedup_avoids_duplicate_get_item_and_processing(self):
        item = complete_item()
        response = FakeResponse(
            200,
            {
                "total": 2,
                "itemSummaries": [search_summary(item), search_summary(item)],
            },
        )
        session = FakeLiveSession(
            search_responses={"EBAY_US": response, "EBAY_CH": response},
            detail_payloads={item["itemId"]: item},
        )
        _, summary, _, session, _ = run_pipeline(session=session)
        detail_calls = [call for call in session.gets if "/buy/browse/v1/item/" in call[0]]
        self.assertEqual(len(detail_calls), 1)
        self.assertEqual(summary.duplicates_skipped, 1)
        self.assertEqual(summary.market.identities_evaluated, 1)
        self.assertEqual(summary.seen_item_store_mode, NO_PERSISTENCE_MODE)

    def test_no_ebay_payload_is_written_to_disk(self):
        session = FakeLiveSession()
        diagnostic = LiveRawPipelineDiagnostic(
            "private-client", "private-secret", session=session
        )
        with patch.object(builtins, "open", wraps=builtins.open) as mocked_open:
            diagnostic.run()
        mocked_open.assert_not_called()

    def test_summary_contains_no_listing_level_values_or_secrets(self):
        item = complete_item()
        _, summary, rendered, _, runtime = run_pipeline(item)
        forbidden = (
            item["itemId"],
            item["title"],
            item["itemWebUrl"],
            item["seller"]["username"],
            item["price"]["value"],
            item["image"]["imageUrl"],
            "private-client-id",
            "private-client-secret",
            "live-application-token-never-log",
        )
        for value in forbidden:
            self.assertNotIn(str(value), rendered)
            self.assertNotIn(str(value), runtime)
        self.assertIn("Persisted eBay records: 0", rendered)
        self.assertEqual(summary.seen_item_store_mode, NO_PERSISTENCE_MODE)

    def test_real_network_is_blocked_outside_github_actions(self):
        with patch.dict(os.environ, {}, clear=True):
            diagnostic = LiveRawPipelineDiagnostic("private-client", "private-secret")
        with patch.object(
            diagnostic.discovery,
            "_application_token",
            side_effect=AssertionError("local eBay call forbidden"),
        ):
            summary = diagnostic.run()
        self.assertEqual(summary.oauth.http_status, "WORKFLOW_ONLY")
        self.assertFalse(summary.oauth.token_obtained)

    def test_ebay_ch_no_inventory_does_not_fail_us_pipeline(self):
        item = complete_item()
        session = FakeLiveSession(
            search_responses={
                "EBAY_US": FakeResponse(
                    200, {"total": 1, "itemSummaries": [search_summary(item)]}
                ),
                "EBAY_CH": FakeResponse(200, {"total": 0, "itemSummaries": []}),
            },
            detail_payloads={item["itemId"]: item},
        )
        config = LiveRawPipelineConfig(result_limit=20, include_ebay_ch=True)
        _, summary, _, _, _ = run_pipeline(session=session, config=config)
        ch = next(
            value for value in summary.marketplaces if value.marketplace_id == "EBAY_CH"
        )
        self.assertEqual(ch.empty_reason, "no inventory")
        self.assertTrue(summary.successful)
        self.assertEqual(summary.market.identities_evaluated, 1)


class LiveRawWorkflowTests(unittest.TestCase):
    def test_workflow_is_manual_read_only_and_persists_only_gcc_catalog(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: V5 Live Raw Pipeline Diagnostic", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("actions/cache/restore@v4", workflow)
        self.assertIn("actions/cache/save@v4", workflow)
        self.assertIn("path: gcc_catalog_index.json", workflow)
        self.assertNotIn("state.json", workflow)
        self.assertNotIn("upload-artifact", workflow)

    def test_workflow_has_required_read_only_secrets_and_all_safety_locks(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("secrets.EBAY_CLIENT_ID", workflow)
        self.assertIn("secrets.EBAY_CLIENT_SECRET", workflow)
        self.assertIn("secrets.GCC_SESSION_B64", workflow)
        self.assertIn("secrets.POKETRACE_API_KEY", workflow)
        self.assertIn('POKETRACE_PLAN: "free"', workflow)
        self.assertIn('POKETRACE_MIN_REQUEST_INTERVAL_SECONDS: "2.05"', workflow)
        self.assertIn('POKETRACE_CARDMARKET_DISCOUNT_THRESHOLD: "0.30"', workflow)
        self.assertNotIn("PRICECHARTING_TOKEN", workflow)
        self.assertNotIn("CARDGRADER_API_KEY", workflow)
        self.assertIn('PRICECHARTING_ENABLED: "false"', workflow)
        self.assertIn('MARKETPLACE_INSIGHTS_ENABLED: "false"', workflow)
        self.assertIn('RAW_MAX_PAID_GRADINGS_PER_RUN: "0"', workflow)
        self.assertIn('CARDGRADER_V5_ALLOW_PAID_CALLS: "false"', workflow)
        self.assertIn('V5_LIVE_RAW_RESULT_LIMIT: "20"', workflow)
        self.assertIn('V5_LIVE_INCLUDE_EBAY_CH: "false"', workflow)
        self.assertIn('GCC_HISTORY_ENABLED: "true"', workflow)
        self.assertIn("rm -f gcc_session.json", workflow)

    def test_future_interval_is_documented_but_not_scheduled(self):
        self.assertEqual(RAW_DISCOVERY_INTERVAL_MINUTES, 10)
        self.assertNotIn("cron:", WORKFLOW.read_text(encoding="utf-8"))


def complete_market_identity():
    return CardIdentity(
        game="Pokemon TCG",
        card_name="Fixturemon",
        set="Fixture Set",
        card_number="7/100",
        year=2024,
        language="English",
        variant="Standard",
    )


if __name__ == "__main__":
    unittest.main()
