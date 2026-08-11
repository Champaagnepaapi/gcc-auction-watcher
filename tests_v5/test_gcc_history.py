from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

try:
    import requests
except ModuleNotFoundError:
    requests = types.ModuleType("requests")
    requests.Session = object
    requests.Response = object
    requests.RequestException = Exception
    sys.modules["requests"] = requests

from v5.gcc_history_diagnostic import render_summary, run_diagnostic
from v5.live_raw_pipeline import (
    LiveRawPipelineDiagnostic,
    PipelineEconomicAggregate,
    PipelineMarketAggregate,
    _PipelineCandidate,
    render_live_raw_pipeline_summary,
)
from v5.ebay_live_diagnostic import MarketplaceAggregate, OAuthAggregate
from v5.market_values.gcc_history.identity import (
    canonical_from_card_identity,
    match_identity,
    normalize_card_number,
)
from v5.market_values.gcc_history.models import (
    CanonicalCollectible,
    ConfidenceLevel,
    GCCSale,
    Grader,
    MatchedSale,
    MatchClass,
    SaleType,
    ValuationPolicy,
    ValuationStatus,
    ValuationType,
)
from v5.market_values.gcc_history.normalization import (
    GCCSaleParser,
    normalize_grade,
    normalize_grader,
)
from v5.market_values.gcc_history.provider import (
    GCCHistoryProvider,
    GCCProviderConfig,
    OfflineGCCSource,
)
from v5.market_values.gcc_history.ratios import CrossGraderRatioModel
from v5.market_values.gcc_history.statistics import (
    InjectedRateConverter,
    estimate_direct_market,
)
from v5.models import CardIdentity, EbayListing, SellerInfo, StructuredGradingStatus


FIXTURE = (
    Path(__file__).parents[1]
    / "v5"
    / "market_values"
    / "gcc_history"
    / "fixtures"
    / "offline_sales.json"
)
WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "v5-gcc-history-diagnostic.yml"
)
LIVE_WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "v5-live-raw-pipeline-diagnostic.yml"
)


def records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]


def charizard() -> CardIdentity:
    return CardIdentity(
        game="Pokémon",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        year=1999,
        language="English",
        finish="Holo",
        edition="Unlimited",
    )


def pikachu() -> CardIdentity:
    return CardIdentity(
        game="Pokemon",
        card_name="Pikachu",
        set="Jungle",
        card_number="60/64",
        year=1999,
        language="English",
        finish="Non Holo",
        edition="Unlimited",
    )


def provider_for(
    policy: ValuationPolicy = ValuationPolicy.DISCOVERY,
    converter=None,
) -> GCCHistoryProvider:
    return GCCHistoryProvider(
        GCCProviderConfig(enabled=True, policy=policy),
        OfflineGCCSource(records()),
        converter=converter,
        today=date(2026, 8, 10),
    )


class GCCFixtureCoverageTests(unittest.TestCase):
    def test_offline_fixtures_cover_cases_a_through_v(self):
        fixture_cases = {record["fixture_case"] for record in records()}
        self.assertEqual(fixture_cases, set("ABCDEFGHIJKLMNOPQRSTUV"))

    def test_parser_returns_normalized_sale_with_absent_fields_as_none(self):
        sale = GCCSaleParser().parse_record(
            {
                "status": "sold",
                "card_name": "Dracaufeu",
                "set_name": "Set de Base",
                "card_number": "# 4 / 102",
                "grader": "PSA",
                "grade": "GEM MINT 10",
                "price": "100.50",
                "currency": "eur",
            }
        )
        self.assertIsNotNone(sale)
        assert sale is not None
        self.assertEqual(sale.identity.card_number, "4/102")
        self.assertEqual(sale.grade, Decimal("10"))
        self.assertIsNone(sale.grade_qualifier)
        self.assertEqual(sale.currency, "EUR")
        self.assertIsNone(sale.sale_date)
        self.assertIsNone(sale.source_url)

    def test_active_asking_record_is_rejected(self):
        active = next(value for value in records() if value["fixture_case"] == "V")
        self.assertIsNone(GCCSaleParser().parse_record(active))


class GCCIdentityMatchingTests(unittest.TestCase):
    def setUp(self):
        self.parser = GCCSaleParser()
        self.target = canonical_from_card_identity(charizard())
        self.sales, _ = self.parser.parse_records(records())

    def sale(self, source_id: str) -> GCCSale:
        return next(value for value in self.sales if value.source_id == source_id)

    def test_exact_match_uses_name_set_number_and_safe_normalization(self):
        result = match_identity(self.target, self.sale("zard-10-2"))
        self.assertEqual(result.match_class, MatchClass.EXACT_MATCH)
        self.assertIn("card_name", result.matched_fields)
        self.assertIn("set_name", result.matched_fields)
        self.assertIn("card_number", result.matched_fields)
        self.assertFalse(result.conflicts)
        self.assertEqual(normalize_card_number("No. 4 / 102"), "4/102")

    def test_known_identity_conflicts_are_rejected(self):
        expected = {
            "wrong-number": "card_number",
            "wrong-set": "set_name",
            "wrong-language": "language",
            "wrong-edition": "first_edition",
            "wrong-finish": "finish",
        }
        for source_id, conflict in expected.items():
            with self.subTest(source_id=source_id):
                result = match_identity(self.target, self.sale(source_id))
                self.assertEqual(result.match_class, MatchClass.REJECTED)
                self.assertIn(conflict, result.conflicts)

    def test_name_only_is_ambiguous_and_never_a_comparable(self):
        result = match_identity(self.target, self.sale("ambiguous-name-only"))
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("name-only", result.reason)

    def test_name_and_number_without_set_is_strong_but_not_exact(self):
        candidate = CanonicalCollectible(
            card_name="Charizard",
            set_name=None,
            card_number="4/102",
            language="English",
            first_edition=False,
            finish="Holo",
        )
        result = match_identity(self.target, candidate)
        self.assertEqual(result.match_class, MatchClass.STRONG_MATCH)
        self.assertGreater(result.score, 0)

    def test_candidate_only_material_variant_downgrades_exact_core_to_strong(self):
        target = CanonicalCollectible("Pikachu", "Jungle", "60/64", "English")
        candidate = CanonicalCollectible(
            "Pikachu",
            "Jungle",
            "60/64",
            "English",
            variant="stamped regional print",
        )
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.STRONG_MATCH)
        self.assertIn("target_variant", result.missing_fields)

    def test_variant_and_edition_are_normalized_as_separate_discriminators(self):
        canonical = canonical_from_card_identity(
            CardIdentity(
                game="Pokemon",
                card_name="Charizard",
                set="Base Set",
                card_number="4/102",
                language="English",
                variant="Shadowless",
                edition="1st Edition",
            )
        )
        self.assertEqual(canonical.variant, "shadowless")
        self.assertTrue(canonical.first_edition)

    def test_match_is_explainable(self):
        result = match_identity(self.target, self.sale("wrong-number"))
        self.assertTrue(result.reason)
        self.assertTrue(result.matched_fields)
        self.assertTrue(result.conflicts)


class GCCGraderAndGradeTests(unittest.TestCase):
    def test_grader_aliases_are_normalized_without_mixing(self):
        aliases = {
            "PSA": Grader.PSA,
            "Professional Card Authenticator": Grader.PCA,
            "Beckett Grading Services": Grader.BGS,
            "CGC": Grader.CGC,
            "Sportscard Guaranty": Grader.SGC,
            "Mystery Slab Co": Grader.UNKNOWN,
        }
        for raw, expected in aliases.items():
            self.assertEqual(normalize_grader(raw), expected)

    def test_raw_and_unknown_grader_are_distinct(self):
        parsed, _ = GCCSaleParser().parse_records(records())
        raw = next(value for value in parsed if value.source_id == "mew-raw")
        unknown = next(
            value for value in parsed if value.source_id == "unknown-grader"
        )
        self.assertEqual(raw.grader, Grader.RAW)
        self.assertIsNone(raw.grade)
        self.assertEqual(unknown.grader, Grader.UNKNOWN)
        self.assertIsNone(unknown.grade)

    def test_numeric_grade_and_qualifier_are_both_preserved(self):
        grade, qualifier = normalize_grade("PSA 9 OC", Grader.PSA)
        self.assertEqual(grade, Decimal("9"))
        self.assertEqual(qualifier, "OC")

    def test_grade_is_not_parsed_without_known_grader_context(self):
        grade, qualifier = normalize_grade("10", Grader.UNKNOWN)
        self.assertIsNone(grade)
        self.assertEqual(qualifier, "10")


class GCCRobustValuationTests(unittest.TestCase):
    def test_direct_raw_psa9_and_psa10_remain_separate(self):
        result = provider_for().market_for(charizard(), "USD")
        raw = result.valuation(Grader.RAW, None)
        psa9 = result.valuation(Grader.PSA, Decimal("9"))
        psa10 = result.valuation(Grader.PSA, Decimal("10"))
        self.assertEqual(raw.valuation_type, ValuationType.DIRECT_MARKET_VALUE)
        self.assertEqual(psa9.valuation_type, ValuationType.DIRECT_MARKET_VALUE)
        self.assertEqual(psa10.valuation_type, ValuationType.DIRECT_MARKET_VALUE)
        self.assertLess(raw.mid, psa9.mid)
        self.assertLess(psa9.mid, psa10.mid)

    def test_robust_statistics_flag_outlier_and_remove_duplicate(self):
        result = provider_for().market_for(charizard(), "USD")
        value = result.valuation(Grader.PSA, Decimal("10"))
        self.assertEqual(value.statistics.outliers_flagged, 1)
        self.assertEqual(value.statistics.duplicates_removed, 1)
        self.assertGreater(
            value.statistics.raw_sales_count,
            value.statistics.deduplicated_sales_count,
        )
        self.assertGreaterEqual(
            value.statistics.deduplicated_sales_count,
            value.statistics.eligible_currency_sales,
        )
        self.assertLess(value.mid, Decimal("1200"))
        self.assertIsNotNone(value.statistics.mad)
        self.assertIsNotNone(value.statistics.iqr)
        self.assertIsNotNone(value.statistics.trimmed_mean)

    def test_recency_weighting_is_explicit_and_old_sale_has_lower_weight(self):
        result = provider_for().market_for(charizard(), "USD")
        stats = result.valuation(Grader.PSA, Decimal("10")).statistics
        self.assertIn("RECENCY", stats.recency_method.upper())
        self.assertGreater(stats.recent_90d, 0)
        self.assertEqual(stats.minimum, Decimal("850"))
        self.assertGreater(stats.weighted_median, stats.minimum)

    def test_sparse_direct_market_is_low_confidence_range(self):
        result = provider_for().market_for(
            CardIdentity(
                game="Pokemon",
                card_name="Venusaur",
                set="Base Set",
                card_number="15/102",
                language="English",
            ),
            "USD",
        )
        value = result.valuation(Grader.PSA, Decimal("10"))
        self.assertEqual(value.confidence, ConfidenceLevel.LOW)
        self.assertEqual(value.status, ValuationStatus.MARKET_VALUE_RANGE)
        self.assertLess(value.low, value.mid)
        self.assertGreater(value.high, value.mid)

    def test_small_sample_is_not_aggressively_outlier_filtered(self):
        target = CanonicalCollectible("test", "set", "1/1", "english")
        sales = tuple(
            MatchedSale(
                GCCSale(
                    source="fixture",
                    identity=target,
                    grader=Grader.PSA,
                    grade=Decimal("10"),
                    grade_qualifier=None,
                    price=price,
                    currency="USD",
                    sale_date=date(2026, 8, day),
                    sale_type=SaleType.AUCTION,
                ),
                match_identity(target, target),
            )
            for price, day in ((Decimal("100"), 1), (Decimal("1000"), 2))
        )
        value = estimate_direct_market(
            sales,
            Grader.PSA,
            Decimal("10"),
            "USD",
            date(2026, 8, 10),
            ValuationPolicy.DISCOVERY,
        )
        self.assertEqual(value.statistics.outliers_flagged, 0)
        self.assertEqual(value.statistics.n, 2)

    def test_currency_is_segregated_without_converter(self):
        result = provider_for().market_for(charizard(), "USD")
        value = result.valuation(Grader.PSA, Decimal("10"))
        self.assertIn("EUR", " ".join(value.limitations))
        self.assertNotEqual(value.mid, Decimal("900"))

    def test_currency_can_be_included_only_with_injected_valid_rate(self):
        converter = InjectedRateConverter({("EUR", "USD"): Decimal("1.1")})
        result = provider_for(converter=converter).market_for(charizard(), "USD")
        value = result.valuation(Grader.PSA, Decimal("10"))
        self.assertNotIn("excluded currencies", " ".join(value.limitations))
        self.assertIn("INJECTED_VALID_RATES", " ".join(value.notes))

    def test_final_policy_requires_manual_validation_for_low_confidence(self):
        result = provider_for(ValuationPolicy.FINAL).market_for(
            CardIdentity(
                game="Pokemon",
                card_name="Venusaur",
                set="Base Set",
                card_number="15/102",
                language="English",
            ),
            "USD",
        )
        self.assertEqual(
            result.valuation(Grader.PSA, Decimal("10")).status,
            ValuationStatus.MANUAL_VALIDATION_REQUIRED,
        )
        self.assertIsNone(result.market_values)


class GCCCrossGraderTests(unittest.TestCase):
    def setUp(self):
        self.sales, _ = GCCSaleParser().parse_records(records())

    def test_ratio_is_learned_from_paired_exact_cards(self):
        ratio = CrossGraderRatioModel(self.sales).ratio_for(
            canonical_from_card_identity(pikachu()),
            Grader.PCA,
            Grader.PSA,
            Decimal("10"),
            "USD",
        )
        self.assertIsNotNone(ratio)
        self.assertEqual(ratio.sample_size, 5)
        self.assertEqual(ratio.median_ratio, Decimal("0.8"))
        self.assertEqual(ratio.hierarchy, "BROAD_OBSERVED_RATIO")

    def test_exact_card_ratio_has_priority(self):
        identity = next(
            sale.identity for sale in self.sales if sale.source_id == "cal-pca-1"
        )
        ratio = CrossGraderRatioModel(self.sales).ratio_for(
            identity, Grader.PCA, Grader.PSA, Decimal("10"), "USD"
        )
        self.assertEqual(ratio.hierarchy, "EXACT_CARD_OBSERVED_RATIO")

    def test_supported_segment_ratio_fallback_for_bgs(self):
        ratio = CrossGraderRatioModel(self.sales).ratio_for(
            canonical_from_card_identity(pikachu()),
            Grader.BGS,
            Grader.PSA,
            Decimal("10"),
            "USD",
        )
        self.assertIsNotNone(ratio)
        self.assertEqual(ratio.hierarchy, "SUPPORTED_SEGMENT_RATIO")
        self.assertEqual(ratio.sample_size, 3)

    def test_supported_segment_ratio_fallback_for_cgc(self):
        ratio = CrossGraderRatioModel(self.sales).ratio_for(
            canonical_from_card_identity(charizard()),
            Grader.CGC,
            Grader.PSA,
            Decimal("10"),
            "USD",
        )
        self.assertIsNotNone(ratio)
        self.assertEqual(ratio.hierarchy, "SUPPORTED_SEGMENT_RATIO")
        self.assertEqual(ratio.sample_size, 3)

    def test_unsupported_ratio_is_unavailable(self):
        ratio = CrossGraderRatioModel(self.sales).ratio_for(
            canonical_from_card_identity(pikachu()),
            Grader.SGC,
            Grader.PSA,
            Decimal("10"),
            "USD",
        )
        self.assertIsNone(ratio)

    def test_pca_only_market_can_produce_explicit_psa_proxy(self):
        result = provider_for().market_for(pikachu(), "USD")
        value = result.valuation(Grader.PSA, Decimal("10"))
        pca = result.valuation(Grader.PCA, Decimal("10"))
        self.assertEqual(value.valuation_type, ValuationType.CROSS_GRADER_PROXY)
        self.assertEqual(value.source_grader, Grader.PCA)
        self.assertIsNotNone(value.ratio)
        self.assertEqual(value.source_market_mid, pca.mid)
        self.assertEqual(value.proxy_comparable_count, pca.statistics.n)
        self.assertEqual(pca.valuation_type, ValuationType.DIRECT_MARKET_VALUE)
        self.assertLessEqual(value.low, value.mid)
        self.assertGreaterEqual(value.high, value.mid)

    def test_raw_is_never_derived_from_graded_sales(self):
        value = provider_for().market_for(pikachu(), "USD").valuation(
            Grader.RAW, None
        )
        self.assertEqual(
            value.valuation_type, ValuationType.INSUFFICIENT_MARKET_DATA
        )

    def test_no_cross_grade_conversion(self):
        value = provider_for().market_for(pikachu(), "USD").valuation(
            Grader.PSA, Decimal("9")
        )
        self.assertEqual(
            value.valuation_type, ValuationType.INSUFFICIENT_MARKET_DATA
        )

    def test_same_grade_source_without_supported_ratio_requires_manual_validation(self):
        only_pca = [
            {
                "status": "sold",
                "source_id": "only-pca",
                "card_name": "Pikachu",
                "set_name": "Jungle",
                "card_number": "60/64",
                "language": "English",
                "first_edition": False,
                "finish": "Non Holo",
                "grader": "PCA",
                "grade": "10",
                "price": "120",
                "currency": "USD",
                "sale_date": "2026-07-01",
            }
        ]
        provider = GCCHistoryProvider(
            GCCProviderConfig(enabled=True),
            OfflineGCCSource(only_pca),
            today=date(2026, 8, 10),
        )
        value = provider.market_for(pikachu(), "USD").valuation(
            Grader.PSA, Decimal("10")
        )
        self.assertEqual(
            value.valuation_type, ValuationType.MANUAL_VALIDATION_REQUIRED
        )
        self.assertEqual(value.status, ValuationStatus.MANUAL_VALIDATION_REQUIRED)
        self.assertIsNone(value.mid)
        self.assertEqual(provider.counters.unsupported_conversions, 1)


class GCCProviderIntegrationTests(unittest.TestCase):
    def test_run_memory_cache_uses_canonical_identity(self):
        provider = provider_for()
        first = provider.market_for(charizard(), "USD")
        second = provider.market_for(charizard(), "USD")
        self.assertIs(first, second)
        self.assertEqual(provider.counters.queries, 1)
        self.assertEqual(provider.counters.cache_hits, 1)

    def test_normalized_query_records_are_reused_across_currency_views(self):
        provider = provider_for()
        provider.market_for(charizard(), "USD")
        provider.market_for(charizard(), "EUR")
        self.assertEqual(provider.counters.queries, 1)
        self.assertEqual(provider.counters.cache_hits, 1)

    def test_provider_exposes_normalized_match_annotated_sales(self):
        sales = provider_for().normalized_sales_for(charizard(), "USD")
        exact = next(value for value in sales if value.source_id == "zard-10-1")
        self.assertEqual(exact.match_class, MatchClass.EXACT_MATCH)
        self.assertGreater(exact.match_score, 0)
        self.assertIn("card_number", exact.matched_fields)
        self.assertTrue(exact.match_reason)

    def test_disabled_provider_is_graceful_and_makes_no_live_call(self):
        provider = GCCHistoryProvider(GCCProviderConfig(enabled=False))
        result = provider.market_for(charizard(), "USD")
        self.assertIsNone(result.market_values)
        self.assertEqual(provider.mode, "LIVE_UNAVAILABLE")
        self.assertEqual(provider.counters.queries, 0)
        self.assertEqual(provider.counters.live_calls, 0)

    def test_unavailable_source_cannot_become_effectively_enabled_by_env_config(self):
        provider = GCCHistoryProvider(GCCProviderConfig(enabled=True))
        result = provider.market_for(charizard(), "USD")
        self.assertFalse(provider.counters.enabled)
        self.assertEqual(provider.mode, "LIVE_UNAVAILABLE")
        self.assertEqual(provider.counters.queries, 0)
        self.assertIsNone(result.market_values)

    def test_ambiguous_identity_record_cannot_create_market_value(self):
        provider = GCCHistoryProvider(
            GCCProviderConfig(enabled=True),
            OfflineGCCSource(
                [
                    {
                        "status": "sold",
                        "card_name": "Charizard",
                        "grader": "PSA",
                        "grade": "10",
                        "price": "500",
                        "currency": "USD",
                    }
                ]
            ),
            today=date(2026, 8, 10),
        )
        result = provider.market_for(charizard(), "USD")
        self.assertIsNone(result.market_values)
        self.assertEqual(result.match_counts[MatchClass.AMBIGUOUS], 1)

    def test_discovery_can_surface_strong_comp_as_manual_range_but_final_excludes_it(self):
        strong_record = {
            "status": "sold",
            "card_name": "Charizard",
            "card_number": "4/102",
            "language": "English",
            "first_edition": False,
            "finish": "Holo",
            "grader": "RAW",
            "price": "120",
            "currency": "USD",
            "sale_date": "2026-07-01",
        }
        discovery = GCCHistoryProvider(
            GCCProviderConfig(enabled=True, policy=ValuationPolicy.DISCOVERY),
            OfflineGCCSource([strong_record]),
            today=date(2026, 8, 10),
        ).market_for(charizard(), "USD")
        final = GCCHistoryProvider(
            GCCProviderConfig(enabled=True, policy=ValuationPolicy.FINAL),
            OfflineGCCSource([strong_record]),
            today=date(2026, 8, 10),
        ).market_for(charizard(), "USD")
        discovery_raw = discovery.valuation(Grader.RAW, None)
        final_raw = final.valuation(Grader.RAW, None)
        self.assertEqual(discovery.match_counts[MatchClass.STRONG_MATCH], 1)
        self.assertEqual(discovery_raw.valuation_type, ValuationType.MARKET_VALUE_RANGE)
        self.assertEqual(
            discovery_raw.status, ValuationStatus.MANUAL_VALIDATION_REQUIRED
        )
        self.assertIsNotNone(discovery_raw.mid)
        self.assertEqual(
            final_raw.valuation_type, ValuationType.INSUFFICIENT_MARKET_DATA
        )

    def test_incomplete_target_identity_is_not_queried(self):
        provider = provider_for()
        result = provider.market_for(
            CardIdentity(game="Pokemon", card_name="Charizard"), "USD"
        )
        self.assertEqual(provider.counters.queries, 0)
        self.assertIsNone(result.market_values)

    def test_market_values_adapter_preserves_raw_psa9_psa10_meaning(self):
        values = provider_for().values_for(charizard())
        self.assertIsNotNone(values.ungraded_value)
        self.assertIsNotNone(values.grade9_generic_value)
        self.assertIsNotNone(values.psa10_value)
        self.assertIsNone(values.grade8_generic_value)
        self.assertIn("PSA values only", " ".join(values.limitations))

    def test_live_raw_pipeline_calls_gcc_only_after_receiving_resolved_candidate(self):
        gcc = provider_for()
        diagnostic = LiveRawPipelineDiagnostic(
            "client",
            "secret",
            session=object(),
            gcc_history_provider=gcc,
        )
        listing = EbayListing(
            item_id="memory-only-item",
            title="not rendered",
            url="https://example.invalid/not-rendered",
            price=Decimal("100"),
            currency="USD",
            shipping_price=None,
            buying_options=("FIXED_PRICE",),
            end_time=None,
            bid_count=None,
            condition="Ungraded",
            condition_id="4000",
            grading_status=StructuredGradingStatus.RAW,
            seller=SellerInfo(),
            primary_image_url="https://example.invalid/front",
            additional_image_urls=(),
            category_id="183454",
            category_name="CCG Individual Cards",
            aspects={},
            identity=charizard(),
        )
        market = PipelineMarketAggregate()
        economic = PipelineEconomicAggregate()
        diagnostic._evaluate_candidate(
            _PipelineCandidate(listing, charizard(), "BACK_IMAGE_UNKNOWN"),
            market,
            economic,
        )
        self.assertEqual(gcc.counters.queries, 1)
        self.assertEqual(gcc.counters.live_calls, 0)
        self.assertEqual(market.gcc_raw_direct_values, 1)
        self.assertEqual(market.gcc_psa9_direct_values, 1)
        self.assertEqual(market.gcc_psa10_direct_values, 1)

    def test_live_summary_reports_unavailable_gcc_without_crashing(self):
        diagnostic = LiveRawPipelineDiagnostic("client", "secret", session=object())
        summary = diagnostic._summary(
            OAuthAggregate("200", True, 7200),
            (MarketplaceAggregate("EBAY_US"),),
        )
        rendered = render_live_raw_pipeline_summary(summary)
        self.assertIn("GCC HISTORY:", rendered)
        self.assertIn("GCC History enabled: false", rendered)
        self.assertIn("live calls: 0", rendered)

    def test_diagnostic_summary_is_offline_and_has_safety_zeroes(self):
        summary = run_diagnostic()
        rendered = render_summary(summary)
        self.assertEqual(summary.mode, "OFFLINE")
        self.assertEqual(summary.live_calls, 0)
        self.assertIn("=== V5 GCC HISTORY SUMMARY ===", rendered)
        self.assertIn("CardGrader calls: 0", rendered)
        self.assertIn("Purchases: 0", rendered)
        self.assertIn("Persisted eBay records: 0", rendered)
        self.assertNotIn("zard-10-1", rendered)

    def test_no_fixed_cross_grader_conversion_constant_exists(self):
        ratios_source = (
            Path(__file__).parents[1]
            / "v5"
            / "market_values"
            / "gcc_history"
            / "ratios.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("FIXED_RATIO", ratios_source)
        self.assertNotIn("PCA_TO_PSA", ratios_source)

    def test_redundant_gcc_diagnostic_workflow_remains_removed(self):
        self.assertFalse(WORKFLOW.exists())

    def test_live_workflow_enables_only_existing_v4_live_access(self):
        workflow = LIVE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('GCC_HISTORY_ENABLED: "true"', workflow)
        self.assertIn("secrets.GCC_SESSION_B64", workflow)
        self.assertIn("playwright install --with-deps chromium", workflow)
        self.assertIn("python -m v5.live_raw_pipeline", workflow)
        self.assertNotIn("offline_sales.json", workflow)

    def test_gcc_modules_contain_no_hidden_network_or_persistence_calls(self):
        package = Path(__file__).parents[1] / "v5" / "market_values" / "gcc_history"
        implementation = "\n".join(
            path.read_text(encoding="utf-8")
            for path in package.glob("*.py")
        )
        self.assertNotIn("requests.", implementation)
        self.assertNotIn("playwright", implementation.casefold())
        self.assertNotIn("write_text(", implementation)
        self.assertNotIn("open(\"w", implementation)


if __name__ == "__main__":
    unittest.main()
