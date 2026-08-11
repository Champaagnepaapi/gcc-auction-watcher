import os
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from tests_v5.test_ebay_live_diagnostic import (
    FakeLiveSession,
    FakeResponse,
    complete_item,
    search_summary,
)
from v5.ebay import parse_ebay_item, resolve_card_identity
from v5.ebay_live_diagnostic import (
    DEFAULT_LIVE_MARKETPLACES,
    DEFAULT_CATEGORY_TREE_URL,
    RESULT_LIMIT,
    SEARCH_URL,
    SUPPORTED_MARKETPLACES,
    EbayLiveDiagnostic,
)
from v5.live_raw_pipeline import (
    ECONOMICS_DEFERRED_CURRENCY_POLICY,
    LiveRawPipelineConfig,
    LiveRawPipelineDiagnostic,
    render_live_raw_pipeline_summary,
)
from v5.market_values.models import MarketValues


WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "v5-live-raw-pipeline-diagnostic.yml"
)

EXPECTED_MARKETPLACES = (
    "EBAY_US",
    "EBAY_CH",
    "EBAY_DE",
    "EBAY_FR",
    "EBAY_IT",
    "EBAY_ES",
    "EBAY_AT",
    "EBAY_BE",
    "EBAY_NL",
    "EBAY_PL",
    "EBAY_IE",
    "EBAY_GB",
)

SAFE_CATEGORY_NAMES = {
    "EBAY_US": "CCG Individual Cards",
    "EBAY_CH": "CCG Individual Cards",
    "EBAY_DE": "Pokémon Sammelkartenspiel Einzelkarten",
    "EBAY_FR": "Cartes individuelles Pokémon",
    "EBAY_IT": "Carte singole Pokémon",
    "EBAY_ES": "Cartas sueltas Pokémon",
    "EBAY_AT": "Pokémon Sammelkartenspiel Einzelkarten",
    "EBAY_BE": "Cartes individuelles Pokémon",
    "EBAY_NL": "Losse kaarten Pokémon",
    "EBAY_PL": "Pojedyncze karty Pokémon",
    "EBAY_IE": "CCG Individual Cards",
    "EBAY_GB": "CCG Individual Cards",
}


def marketplace_item(marketplace, index, currency="EUR"):
    item = deepcopy(complete_item())
    item["itemId"] = f"v1|{marketplace}-{index}|0"
    item["title"] = "Pokemon individual card fixture"
    item["price"] = {"value": "12.50", "currency": currency}
    return item


def make_session(stocks, currencies=None, taxonomy_failures=None):
    currencies = currencies or {}
    search_responses = {}
    details = {}
    categories = {}
    names = {}
    for marketplace, count in stocks.items():
        summaries = []
        for index in range(count):
            item = marketplace_item(
                marketplace,
                index,
                currencies.get(marketplace, "USD" if marketplace == "EBAY_US" else "EUR"),
            )
            summaries.append(search_summary(item))
            details[item["itemId"]] = item
        search_responses[marketplace] = FakeResponse(
            200, {"total": count, "itemSummaries": summaries}
        )
        categories[marketplace] = f"category-{marketplace}"
        names[marketplace] = SAFE_CATEGORY_NAMES[marketplace]
    return FakeLiveSession(
        search_responses=search_responses,
        detail_payloads=details,
        taxonomy_categories=categories,
        taxonomy_names=names,
        taxonomy_failures=taxonomy_failures,
    )


class FixtureMarketSource:
    def values_for(self, identity):
        return MarketValues(
            source="offline USD fixture",
            currency="USD",
            ungraded_value=Decimal("25"),
            grade8_generic_value=None,
            grade9_generic_value=None,
            psa10_value=None,
            matched_identity=identity,
            match_confidence=Decimal("1"),
            matched_product_id="offline-only",
        )


class EbayEuConfigurationTests(unittest.TestCase):
    def test_marketplace_whitelist_is_complete_and_default_is_priority_five(self):
        self.assertEqual(SUPPORTED_MARKETPLACES, EXPECTED_MARKETPLACES)
        self.assertEqual(
            DEFAULT_LIVE_MARKETPLACES,
            ("EBAY_US", "EBAY_DE", "EBAY_FR", "EBAY_IT", "EBAY_ES"),
        )

    def test_unknown_marketplace_is_rejected(self):
        with self.assertRaises(ValueError):
            LiveRawPipelineConfig(marketplaces=("EBAY_US", "EBAY_UNKNOWN"))
        with self.assertRaises(ValueError):
            EbayLiveDiagnostic("client", "secret", marketplaces=("EBAY_CA",))

    def test_single_environment_variable_controls_marketplaces(self):
        with patch.dict(
            os.environ,
            {"V5_LIVE_EBAY_MARKETPLACES": "EBAY_US,EBAY_GB,EBAY_CH"},
            clear=True,
        ):
            config = LiveRawPipelineConfig.from_env()
        self.assertEqual(config.marketplaces, ("EBAY_US", "EBAY_GB", "EBAY_CH"))

    def test_workflow_activates_only_priority_five_and_global_cap(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            'V5_LIVE_EBAY_MARKETPLACES: "EBAY_US,EBAY_DE,EBAY_FR,EBAY_IT,EBAY_ES"',
            workflow,
        )
        self.assertIn('V5_LIVE_RAW_RESULT_LIMIT: "20"', workflow)
        self.assertNotIn("V5_LIVE_INCLUDE_EBAY_CH", workflow)


class EbayEuDiscoveryTests(unittest.TestCase):
    def test_taxonomy_and_category_ids_are_independent_per_marketplace(self):
        markets = DEFAULT_LIVE_MARKETPLACES
        session = make_session({marketplace: 1 for marketplace in markets})
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=markets
        ).run()
        self.assertTrue(all(value.taxonomy_ok for value in summary.marketplaces))
        tree_calls = [call for call in session.gets if call[0] == DEFAULT_CATEGORY_TREE_URL]
        self.assertEqual(
            {call[1]["params"]["marketplace_id"] for call in tree_calls},
            set(markets),
        )
        search_calls = [call for call in session.gets if call[0] == SEARCH_URL]
        self.assertEqual(
            {
                call[1]["headers"]["X-EBAY-C-MARKETPLACE-ID"]:
                call[1]["params"]["category_ids"]
                for call in search_calls
            },
            {marketplace: f"category-{marketplace}" for marketplace in markets},
        )

    def test_taxonomy_failure_is_fail_closed_without_broad_search(self):
        failure = FakeResponse(500, {"errors": [{"category": "API", "errorId": 1}]})
        session = make_session(
            {"EBAY_DE": 1},
            taxonomy_failures={("EBAY_DE", "suggestions"): failure},
        )
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=("EBAY_DE",)
        ).run()
        aggregate = summary.marketplaces[0]
        self.assertFalse(aggregate.taxonomy_ok)
        self.assertEqual(aggregate.empty_reason, "marketplace unavailable/incomplete")
        self.assertFalse(any(call[0] == SEARCH_URL for call in session.gets))
        self.assertFalse(any("/buy/browse/v1/item/" in call[0] for call in session.gets))

    def test_unsafe_taxonomy_suggestion_is_fail_closed(self):
        session = make_session({"EBAY_FR": 1})
        session.taxonomy_names["EBAY_FR"] = "Boîtes et produits scellés"
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=("EBAY_FR",)
        ).run()
        self.assertEqual(
            summary.marketplaces[0].taxonomy_error_type,
            "SAFE_INDIVIDUAL_CATEGORY_MISSING",
        )
        self.assertFalse(any(call[0] == SEARCH_URL for call in session.gets))

    def test_delivery_country_ch_is_applied_to_priority_eu_marketplaces(self):
        markets = ("EBAY_DE", "EBAY_FR", "EBAY_IT", "EBAY_ES")
        session = make_session({marketplace: 1 for marketplace in markets})
        EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=markets
        ).run()
        searches = [call for call in session.gets if call[0] == SEARCH_URL]
        self.assertTrue(
            all("deliveryCountry:CH" in call[1]["params"]["filter"] for call in searches)
        )

    def test_contextual_location_is_absent_without_explicit_postcode(self):
        session = make_session({"EBAY_DE": 1})
        EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=("EBAY_DE",)
        ).run()
        self.assertTrue(
            all("X-EBAY-C-ENDUSERCTX" not in call[1].get("headers", {}) for call in session.gets)
        )

    def test_contextual_location_uses_only_explicit_swiss_postcode(self):
        session = make_session({"EBAY_DE": 1})
        EbayLiveDiagnostic(
            "client",
            "secret",
            session=session,
            marketplaces=("EBAY_DE",),
            delivery_postal_code="8001",
        ).run()
        search = next(call for call in session.gets if call[0] == SEARCH_URL)
        self.assertEqual(
            search[1]["headers"]["X-EBAY-C-ENDUSERCTX"],
            "contextualLocation=country%3DCH%2Czip%3D8001",
        )

    def test_shipping_estimate_is_available_only_when_browse_provides_it(self):
        session = make_session({"EBAY_DE": 1})
        detail = next(iter(session.detail_payloads.values()))
        detail["shippingOptions"] = [
            {"shippingCost": {"value": "5.00", "currency": "EUR"}}
        ]
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=("EBAY_DE",)
        ).run()
        aggregate = summary.marketplaces[0]
        self.assertEqual(aggregate.shipping_estimate_available, 1)
        self.assertEqual(aggregate.shipping_estimate_limited, 0)

    def test_global_cap_round_robin_represents_all_stocked_marketplaces(self):
        markets = DEFAULT_LIVE_MARKETPLACES
        session = make_session({marketplace: 8 for marketplace in markets})
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=markets
        ).run()
        self.assertEqual(summary.unique_items, RESULT_LIMIT)
        self.assertEqual(sum(value.get_item_calls for value in summary.marketplaces), 20)
        self.assertEqual([value.unique_selected for value in summary.marketplaces], [4] * 5)

    def test_global_round_robin_backfills_from_marketplace_with_stock(self):
        markets = ("EBAY_US", "EBAY_DE", "EBAY_FR")
        session = make_session({"EBAY_US": 20, "EBAY_DE": 1, "EBAY_FR": 0})
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=markets
        ).run()
        selected = {value.marketplace_id: value.unique_selected for value in summary.marketplaces}
        self.assertEqual(summary.unique_items, 20)
        self.assertEqual(selected, {"EBAY_US": 19, "EBAY_DE": 1, "EBAY_FR": 0})

    def test_cross_market_duplicate_is_enriched_once(self):
        shared = marketplace_item("SHARED", 1, "USD")
        response = FakeResponse(200, {"total": 1, "itemSummaries": [search_summary(shared)]})
        session = FakeLiveSession(
            search_responses={"EBAY_US": response, "EBAY_DE": response},
            detail_payloads={shared["itemId"]: shared},
            taxonomy_categories={"EBAY_US": "us", "EBAY_DE": "de"},
            taxonomy_names={
                "EBAY_US": SAFE_CATEGORY_NAMES["EBAY_US"],
                "EBAY_DE": SAFE_CATEGORY_NAMES["EBAY_DE"],
            },
        )
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=("EBAY_US", "EBAY_DE")
        ).run()
        self.assertEqual(summary.unique_items, 1)
        self.assertEqual(summary.duplicate_items, 1)
        self.assertEqual(sum(value.get_item_calls for value in summary.marketplaces), 1)
        self.assertEqual(summary.marketplaces[1].duplicates_cross_market, 1)

    def test_sealed_or_multi_product_title_is_not_selected(self):
        item = marketplace_item("EBAY_DE", 1)
        item["title"] = "Pokemon Elite Trainer Box sealed"
        session = make_session({"EBAY_DE": 0})
        session.search_responses["EBAY_DE"] = FakeResponse(
            200, {"total": 1, "itemSummaries": [search_summary(item)]}
        )
        summary = EbayLiveDiagnostic(
            "client", "secret", session=session, marketplaces=("EBAY_DE",)
        ).run()
        self.assertEqual(summary.unique_items, 0)
        self.assertEqual(summary.marketplaces[0].product_shape_rejected, 1)


class EbayEuIdentityCurrencyTests(unittest.TestCase):
    def test_spanish_localized_identity_and_labels_are_preserved(self):
        payload = marketplace_item("EBAY_ES", 1)
        payload["localizedAspects"] = [
            {"name": "Juego", "value": "Pokémon TCG"},
            {"name": "Nombre de la carta", "value": "Pikachu"},
            {"name": "Conjunto", "value": "Jungla"},
            {"name": "Número de carta", "value": "60/64"},
            {"name": "Idioma", "value": "Español"},
            {"name": "Edición", "value": "Primera edición"},
        ]
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.card_name, "Pikachu")
        self.assertEqual(identity.set, "Jungla")
        self.assertEqual(identity.card_number, "60/64")
        self.assertEqual(identity.language, "Español")
        self.assertEqual(identity.edition, "Primera edición")

    def test_listing_currency_is_preserved_for_us_eu_ch_and_gb(self):
        expected = {
            "EBAY_US": "USD",
            "EBAY_DE": "EUR",
            "EBAY_CH": "CHF",
            "EBAY_GB": "GBP",
        }
        actual = {
            marketplace: parse_ebay_item(
                marketplace_item(marketplace, 1, currency)
            ).currency
            for marketplace, currency in expected.items()
        }
        self.assertEqual(actual, expected)

    def test_non_us_economics_is_deferred_without_cost_or_currency_mixing(self):
        session = make_session({"EBAY_DE": 1}, currencies={"EBAY_DE": "EUR"})
        cost_factory = Mock(side_effect=AssertionError("USD cost model must not run"))
        diagnostic = LiveRawPipelineDiagnostic(
            "client",
            "secret",
            config=LiveRawPipelineConfig(
                result_limit=20, marketplaces=("EBAY_DE",)
            ),
            session=session,
            offline_market_sources=(FixtureMarketSource(),),
            cost_factory=cost_factory,
        )
        summary = diagnostic.run()
        rendered = render_live_raw_pipeline_summary(summary)
        self.assertEqual(summary.market.values_found, 1)
        self.assertEqual(summary.economic.deferred_currency_policy, 1)
        self.assertEqual(summary.economic.raw_path_evaluated, 0)
        self.assertEqual(summary.marketplaces[0].economics_deferred, 1)
        self.assertIn(f"{ECONOMICS_DEFERRED_CURRENCY_POLICY}: 1", rendered)
        cost_factory.assert_not_called()

    def test_chf_and_gbp_are_also_deferred_and_reported_separately(self):
        currencies = {"EBAY_CH": "CHF", "EBAY_GB": "GBP"}
        session = make_session({"EBAY_CH": 1, "EBAY_GB": 1}, currencies=currencies)
        summary = LiveRawPipelineDiagnostic(
            "client",
            "secret",
            config=LiveRawPipelineConfig(
                result_limit=20, marketplaces=("EBAY_CH", "EBAY_GB")
            ),
            session=session,
            offline_market_sources=(FixtureMarketSource(),),
            cost_factory=Mock(side_effect=AssertionError("regional costs deferred")),
        ).run()
        self.assertEqual(summary.economic.deferred_currency_policy, 2)
        self.assertEqual(
            [value.currency_counts for value in summary.marketplaces],
            [{"CHF": 1}, {"GBP": 1}],
        )

    def test_rendered_diagnostics_are_aggregate_and_keep_safety_zeroes(self):
        item = marketplace_item("EBAY_FR", 1, "EUR")
        session = make_session({"EBAY_FR": 1})
        summary = LiveRawPipelineDiagnostic(
            "client",
            "secret",
            config=LiveRawPipelineConfig(
                result_limit=20, marketplaces=("EBAY_FR",)
            ),
            session=session,
        ).run()
        rendered = render_live_raw_pipeline_summary(summary)
        for forbidden in (
            item["itemId"],
            item["title"],
            item["itemWebUrl"],
            item["price"]["value"],
        ):
            self.assertNotIn(forbidden, rendered)
        for safe_line in (
            "taxonomy: OK",
            "unique selected global:",
            "cross-market duplicates:",
            "ship-to-CH eligible:",
            "currency distribution: EUR=1",
            "CardGrader calls: 0",
            "Purchases: 0",
            "Bids: 0",
            "Checkout: 0",
            "Persisted eBay records: 0",
        ):
            self.assertIn(safe_line, rendered)


if __name__ == "__main__":
    unittest.main()
