import json
import os
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from v5.image_detection import BACK_IMAGE_CONFIRMED, BACK_IMAGE_UNKNOWN
from v5.market_diagnostic import render_summary
from v5.market_values.aggregator import AggregatorConfig, MarketValueAggregator
from v5.market_values.economic import (
    COST_MODEL_INCOMPLETE,
    ECONOMIC_REJECT_EVEN_PSA10,
    GRADE9_PROFITABLE,
    GRADING_VISUAL_CONFIDENCE_REDUCED,
    PSA10_DEPENDENT,
    CostModel,
    evaluate_economic_pre_filter,
)
from v5.market_values.models import (
    MARKET_VALUE_CONFLICT,
    MARKET_VALUES_MISSING,
    AggregationStatus,
    MarketLevel,
    MarketValues,
)
from v5.market_values.pricecharting import (
    PRICECHARTING_AMBIGUOUS,
    PRICECHARTING_DISABLED,
    PRICECHARTING_MATCHED,
    PriceChartingConfig,
    PriceChartingProvider,
    market_values_from_product,
)
from v5.market_values.secondary import (
    MarketplaceInsightsProvider,
    PSASalesProvider,
    active_asking_statistics,
)
from v5.models import CardIdentity, GradeImagePair
from v5.scanner import (
    GRADING_VISUAL_CONFIDENCE_REDUCED as SCANNER_VISUAL_REDUCED,
    RawCardScanner,
    SafeguardConfig,
    ScanRequest,
)
from v5.ebay import parse_ebay_item
from v5.valuation import StaticMarketDataProvider
from v5.models import CostInputs, MarketValue as LegacyMarketValue, MarketValues as LegacyMarketValues


FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def identity(name="Charizard", number="4/102"):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=name,
        set="Base Set",
        card_number=number,
        year=1999,
        language="English",
    )


def values_for(card, raw="3", grade8="6", grade9="8", psa10="60", source="fixture"):
    return MarketValues(
        source=source,
        currency="USD",
        ungraded_value=Decimal(raw) if raw is not None else None,
        grade8_generic_value=Decimal(grade8) if grade8 is not None else None,
        grade9_generic_value=Decimal(grade9) if grade9 is not None else None,
        psa10_value=Decimal(psa10) if psa10 is not None else None,
        matched_identity=card,
        match_confidence=Decimal("1"),
        matched_product_id="fixture-product",
    )


def costs(purchase="2", grading="20", grading_shipping="5", **changes):
    data = {
        "raw_purchase_price": Decimal(purchase),
        "buyer_fees": Decimal("0"),
        "domestic_shipping": Decimal("0"),
        "international_shipping": Decimal("0"),
        "grading_fee": Decimal(grading),
        "grading_shipping": Decimal(grading_shipping),
        "vault_fee": Decimal("0"),
        "selling_fee_pct": Decimal("0"),
        "selling_fixed_fee": Decimal("0"),
        "fx_buffer_pct": Decimal("0"),
        "other_costs": Decimal("0"),
        "currency": "USD",
    }
    data.update(changes)
    return CostModel(**data)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class PriceChartingSession:
    def __init__(self, products, product=None):
        self.products = products
        self.product = product
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/api/products"):
            return FakeResponse(self.products)
        return FakeResponse(self.product)


class PriceChartingProviderTests(unittest.TestCase):
    def test_exact_official_card_price_mapping_and_generic_labels(self):
        product = load_json("pricecharting_product.json")
        result = market_values_from_product(product, identity(), Decimal("1"))
        self.assertEqual(result.ungraded_value, Decimal("12.34"))
        self.assertEqual(result.grade8_generic_value, Decimal("45.67"))
        self.assertEqual(result.grade9_generic_value, Decimal("89.01"))
        self.assertEqual(result.psa10_value, Decimal("234.56"))
        self.assertIn("GRADE8_GENERIC is not PSA8", result.limitations)
        self.assertIn("GRADE9_GENERIC is not PSA9", result.limitations)

    def test_structured_unique_match_uses_products_then_product(self):
        session = PriceChartingSession(
            load_json("pricecharting_products.json"),
            load_json("pricecharting_product.json"),
        )
        clock = iter((0.0, 0.2, 1.0))
        sleeps = []
        provider = PriceChartingProvider(
            PriceChartingConfig(enabled=True, token="fixture-secret"),
            session=session,
            monotonic=lambda: next(clock),
            sleeper=sleeps.append,
        )
        result = provider.values_for(identity())
        self.assertEqual(result.status, PRICECHARTING_MATCHED)
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.calls[0][0].endswith("/api/products"))
        self.assertTrue(session.calls[1][0].endswith("/api/product"))
        self.assertGreaterEqual(sleeps[0], 0.8)

    def test_ambiguous_search_never_fetches_or_values_first_result(self):
        session = PriceChartingSession(load_json("pricecharting_ambiguous.json"))
        provider = PriceChartingProvider(
            PriceChartingConfig(enabled=True, token="fixture-secret"), session=session
        )
        result = provider.values_for(identity())
        self.assertEqual(result.status, PRICECHARTING_AMBIGUOUS)
        self.assertIsNone(result.values)
        self.assertEqual(len(session.calls), 1)

    def test_variant_mismatch_reduces_explainable_match_score(self):
        session = PriceChartingSession(load_json("pricecharting_products.json"))
        provider = PriceChartingProvider(
            PriceChartingConfig(
                enabled=True,
                token="fixture-secret",
                minimum_match_score=Decimal("0.98"),
            ),
            session=session,
        )
        result = provider.values_for(replace(identity(), variant="1st Edition"))
        self.assertIsNone(result.values)
        self.assertIn("variant:no_match", result.match_explanation)

    def test_disabled_provider_makes_no_call(self):
        session = PriceChartingSession(load_json("pricecharting_products.json"))
        provider = PriceChartingProvider(
            PriceChartingConfig(enabled=False, token="fixture-secret"), session=session
        )
        self.assertEqual(provider.values_for(identity()).status, PRICECHARTING_DISABLED)
        self.assertEqual(session.calls, [])
        self.assertEqual(provider.live_calls, 0)

    def test_token_is_never_in_repr_or_diagnostic_output(self):
        secret = "super-private-pricecharting-token"
        config = PriceChartingConfig(enabled=False, token=secret)
        self.assertNotIn(secret, repr(config))
        self.assertNotIn(secret, render_summary())


class AggregationAndSecondaryProviderTests(unittest.TestCase):
    def test_missing_market_values_remain_missing(self):
        aggregate = MarketValueAggregator().aggregate(identity(), ())
        self.assertEqual(aggregate.status, AggregationStatus.MISSING)
        self.assertIn(MARKET_VALUES_MISSING, aggregate.reasons)

    def test_provider_disagreement_is_an_explicit_conflict(self):
        card = identity()
        aggregate = MarketValueAggregator(
            AggregatorConfig(maximum_relative_dispersion=Decimal("0.20"))
        ).aggregate(
            card,
            (
                values_for(card, psa10="60", source="source A"),
                values_for(card, psa10="120", source="source B"),
            ),
        )
        self.assertEqual(aggregate.status, AggregationStatus.CONFLICT)
        self.assertIn(MARKET_VALUE_CONFLICT, aggregate.reasons)
        self.assertTrue(aggregate.level(MarketLevel.PSA10).disagreement)

    def test_different_identities_are_never_merged(self):
        card = identity()
        aggregate = MarketValueAggregator().aggregate(
            card, (values_for(identity("Blastoise", "2/102")),)
        )
        self.assertEqual(aggregate.status, AggregationStatus.CONFLICT)

    def test_active_asking_prices_are_secondary_only(self):
        stats = active_asking_statistics(
            (Decimal("10"), Decimal("12"), Decimal("14"), Decimal("100")), "USD"
        )
        self.assertEqual(stats.count, 4)
        self.assertEqual(stats.median, Decimal("13"))
        self.assertFalse(stats.sufficient_for_economic_valuation)

    def test_unavailable_provider_interfaces_make_no_calls(self):
        insights = MarketplaceInsightsProvider()
        psa = PSASalesProvider()
        self.assertEqual(insights.sold_comparables_for(identity()), ())
        self.assertFalse(insights.enabled)
        self.assertEqual(insights.live_calls, 0)
        self.assertEqual(psa.status, "UNAVAILABLE")
        self.assertEqual(psa.sold_comparables_for(identity()), ())
        self.assertEqual(psa.live_calls, 0)


class EconomicPreFilterTests(unittest.TestCase):
    def aggregate(self, values):
        return MarketValueAggregator().aggregate(identity(), (values,))

    def test_case_a_is_psa10_dependent(self):
        result = evaluate_economic_pre_filter(
            self.aggregate(values_for(identity(), raw="3", grade8="6", grade9="8", psa10="60")),
            costs("2", "20", "5"),
            BACK_IMAGE_CONFIRMED,
        )
        self.assertIn(PSA10_DEPENDENT, result.signals)
        self.assertLess(result.scenarios[MarketLevel.GRADE9_GENERIC].profit, 0)
        self.assertGreater(result.scenarios[MarketLevel.PSA10].profit, 0)

    def test_case_b_is_grade9_profitable_with_profit_and_roi(self):
        result = evaluate_economic_pre_filter(
            self.aggregate(values_for(identity(), raw="15", grade8="40", grade9="55", psa10="100")),
            costs("10", "20", "5"),
            BACK_IMAGE_CONFIRMED,
        )
        scenario = result.scenarios[MarketLevel.GRADE9_GENERIC]
        self.assertIn(GRADE9_PROFITABLE, result.signals)
        self.assertEqual(scenario.profit, Decimal("20"))
        self.assertGreater(scenario.roi_percent, 0)

    def test_case_c_rejects_even_psa10_after_costs(self):
        result = evaluate_economic_pre_filter(
            self.aggregate(values_for(identity(), raw="25", grade8="30", grade9="35", psa10="40")),
            costs("30", "10", "5"),
            BACK_IMAGE_CONFIRMED,
        )
        self.assertFalse(result.can_continue)
        self.assertIn(ECONOMIC_REJECT_EVEN_PSA10, result.signals)

    def test_case_d_missing_market_values(self):
        result = evaluate_economic_pre_filter(
            MarketValueAggregator().aggregate(identity(), ()),
            costs(),
            BACK_IMAGE_CONFIRMED,
        )
        self.assertIn(MARKET_VALUES_MISSING, result.signals)

    def test_incomplete_cost_model_is_blocking(self):
        result = evaluate_economic_pre_filter(
            self.aggregate(values_for(identity())),
            replace(costs(), grading_fee=None),
            BACK_IMAGE_CONFIRMED,
        )
        self.assertIn(COST_MODEL_INCOMPLETE, result.signals)

    def test_back_absent_reduces_visual_confidence_but_economics_continue(self):
        result = evaluate_economic_pre_filter(
            self.aggregate(values_for(identity(), grade9="55", psa10="100")),
            costs("10", "20", "5"),
            BACK_IMAGE_UNKNOWN,
        )
        self.assertTrue(result.can_continue)
        self.assertTrue(result.back_missing_but_economic_analysis_continued)
        self.assertIn(GRADING_VISUAL_CONFIDENCE_REDUCED, result.risk_flags)

    def test_percentage_and_fixed_selling_costs_affect_net_profit(self):
        result = evaluate_economic_pre_filter(
            self.aggregate(values_for(identity(), psa10="100")),
            costs(selling_fee_pct=Decimal("10"), selling_fixed_fee=Decimal("2"), fx_buffer_pct=Decimal("3")),
            BACK_IMAGE_CONFIRMED,
        )
        self.assertEqual(result.scenarios[MarketLevel.PSA10].net_sale, Decimal("85"))


class PipelineAndSummarySafetyTests(unittest.TestCase):
    def test_existing_scanner_economics_continue_without_back_before_grading(self):
        listing = parse_ebay_item(load_json("ebay_raw_item.json"))
        legacy_value = lambda amount: LegacyMarketValue(Decimal(amount), "EUR", 4, "high", "fixture")
        legacy_values = LegacyMarketValues(
            legacy_value("55"), legacy_value("100"), legacy_value("150"), legacy_value("250"), legacy_value("60")
        )
        key = (listing.identity.card_name, listing.identity.set, listing.identity.card_number)

        class NeverGrade:
            calls = 0

            def assess(self, image_pair, card_identity):
                self.calls += 1
                raise AssertionError("CardGrader must not be called")

        provider = NeverGrade()
        scanner = RawCardScanner(
            provider,
            StaticMarketDataProvider({key: legacy_values}),
            safeguards=SafeguardConfig(maximum_paid_gradings_per_run=0),
        )
        request = ScanRequest(
            listing,
            GradeImagePair(listing.primary_image_url, None),
            CostInputs(listing.price, listing.shipping_price, Decimal("2"), Decimal("20"), Decimal("10"), Decimal("0.13"), Decimal("3"), "EUR"),
        )
        cheap = scanner.cheap_filter(request)
        self.assertTrue(cheap.eligible_for_visual_grading)
        self.assertIn(SCANNER_VISUAL_REDUCED, cheap.risk_flags)
        self.assertIsNotNone(cheap.psa10_profit)
        self.assertEqual(provider.calls, 0)

    def test_diagnostic_is_aggregate_only_and_all_paid_actions_stay_zero(self):
        rendered = render_summary()
        self.assertIn("=== V5 MARKET VALUATION SUMMARY ===", rendered)
        self.assertIn("live calls: 0", rendered)
        self.assertIn("CardGrader calls: 0", rendered)
        self.assertIn("Purchases: 0", rendered)
        self.assertIn("Persisted eBay records: 0", rendered)
        self.assertNotIn("Offline Card", rendered)
        self.assertNotIn("fixture-product", rendered)

    def test_no_pricecharting_response_is_written_to_disk(self):
        session = PriceChartingSession(
            load_json("pricecharting_products.json"),
            load_json("pricecharting_product.json"),
        )
        provider = PriceChartingProvider(
            PriceChartingConfig(enabled=True, token="fixture-secret"), session=session
        )
        with patch("builtins.open", side_effect=AssertionError("disk write forbidden")):
            result = provider.values_for(identity())
        self.assertEqual(result.status, PRICECHARTING_MATCHED)

    def test_environment_default_locks_all_paid_services(self):
        with patch.dict(os.environ, {}, clear=True):
            pricecharting = PriceChartingConfig.from_env()
            safeguards = SafeguardConfig.from_env()
        self.assertFalse(pricecharting.enabled)
        self.assertEqual(safeguards.maximum_paid_gradings_per_run, 0)

    def test_market_workflow_is_manual_offline_and_contains_both_paid_locks(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "v5-market-valuation-diagnostic.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("name: V5 Market Valuation Diagnostic", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn('PRICECHARTING_ENABLED: "false"', workflow)
        self.assertIn('RAW_MAX_PAID_GRADINGS_PER_RUN: "0"', workflow)
        self.assertIn('CARDGRADER_V5_ALLOW_PAID_CALLS: "false"', workflow)
        self.assertNotIn("PRICECHARTING_TOKEN", workflow)
        self.assertNotIn("EBAY_CLIENT", workflow)


if __name__ == "__main__":
    unittest.main()
