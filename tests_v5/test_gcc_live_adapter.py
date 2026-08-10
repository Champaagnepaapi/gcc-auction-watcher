import unittest
import io
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date
from decimal import Decimal

import watcher
from ecb_fx import ECBCurrencyConverter, ECB_PROVIDER, parse_ecb_snapshot
from v5.gcc_live_adapter import (
    GCC_V4_ACCESS_MECHANISM,
    V4RenderedGCCHistorySource,
)
from v5.ebay_live_diagnostic import MarketplaceAggregate, OAuthAggregate
from v5.live_raw_pipeline import (
    LiveRawPipelineDiagnostic,
    render_live_raw_pipeline_summary,
)
from v5.market_values.gcc_history.models import Grader, ValuationType
from v5.market_values.gcc_history.normalization import GCCSaleParser
from v5.market_values.gcc_history.provider import (
    GCCHistoryProvider,
    GCCProviderConfig,
)
from v5.models import CardIdentity


ECB_XML = (
    '<?xml version="1.0"?><gesmes:Envelope '
    'xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
    'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
    '<Cube><Cube time="2026-08-07">'
    '<Cube currency="USD" rate="1.2000"/>'
    '<Cube currency="CHF" rate="0.9500"/>'
    '</Cube></Cube></gesmes:Envelope>'
)


class FakeResponse:
    text = ECB_XML

    def raise_for_status(self):
        return None


def target_identity(set_name="Base Set"):
    return CardIdentity(
        game="Pokemon",
        card_name="Charizard",
        set=set_name,
        card_number="4/102",
        year=1999,
        language="English",
    )


def inventory_lot():
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/anonymized-fixture",
        title="PSA 10 Charizard",
        current_price=80,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_set="Base Set",
        card_number="4/102",
        language="English",
        year=1999,
        set_family="Base Set",
    )


HISTORY_BODY = (
    "Historique des ventes\n"
    "Non graded\nDate: 01/08/2026\n20 €\n"
    "PSA 9\nDate: 02/08/2026\n50 €\n"
    "PSA 10\nDate: 03/08/2026\n100 €\n"
    "PCA 10\nDate: 04/08/2026\n80 €"
)


def source_for(lot=None, body=HISTORY_BODY):
    chosen = lot or inventory_lot()

    def inventory(diagnostics):
        diagnostics.fixed_coverage.pages_requested = 1
        return (chosen,)

    def inspect(_page, value, *, log_listing_errors=True):
        if log_listing_errors:
            raise AssertionError("live adapter must suppress listing-level errors")
        return replace(value, body=body, inspection_error="")

    return V4RenderedGCCHistorySource(
        object(), inventory_fetcher=inventory, item_inspector=inspect
    )


class ECBFXTests(unittest.TestCase):
    def test_official_snapshot_preserves_rate_date_and_cross_rate(self):
        snapshot = parse_ecb_snapshot(ECB_XML)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.provider, ECB_PROVIDER)
        self.assertEqual(snapshot.rate_date.isoformat(), "2026-08-07")
        self.assertEqual(snapshot.rate("EUR", "USD"), Decimal("1.2000"))
        self.assertEqual(
            snapshot.rate("CHF", "USD"), Decimal("1.2000") / Decimal("0.9500")
        )

    def test_converter_fetches_once_and_never_assumes_missing_fx(self):
        calls = []

        def get(*args, **kwargs):
            calls.append((args, kwargs))
            return FakeResponse()

        converter = ECBCurrencyConverter(get)
        self.assertEqual(
            converter.convert(Decimal("100"), "EUR", "USD", None),
            Decimal("120.0000"),
        )
        self.assertEqual(
            converter.convert(Decimal("120"), "USD", "EUR", None),
            Decimal("1E+2"),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(converter.fetches, 1)
        self.assertGreaterEqual(converter.cache_hits, 1)
        self.assertIsNone(converter.convert(Decimal("1"), "XXX", "USD", None))

    def test_fx_failure_returns_none_without_fallback_constant(self):
        converter = ECBCurrencyConverter(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down"))
        )
        self.assertIsNone(converter.convert(Decimal("10"), "EUR", "USD", None))
        self.assertEqual(converter.failures, 1)


class V4ToV5LiveAdapterTests(unittest.TestCase):
    def test_existing_v4_path_normalizes_raw_psa_and_pca_eur_sales(self):
        source = source_for()
        provider = GCCHistoryProvider(
            GCCProviderConfig(enabled=True, default_currency="USD"),
            source,
            converter=ECBCurrencyConverter(lambda *_args, **_kwargs: FakeResponse()),
            today=date(2026, 8, 10),
        )
        result = provider.market_for(target_identity(), "USD")
        buckets = {(sale.grader, sale.grade) for sale in result.sales}
        self.assertTrue(
            {
                (Grader.RAW, None),
                (Grader.PSA, Decimal("9")),
                (Grader.PSA, Decimal("10")),
                (Grader.PCA, Decimal("10")),
            }.issubset(buckets)
        )
        self.assertTrue(all(sale.currency == "EUR" for sale in result.sales))
        self.assertEqual(
            result.valuation(Grader.RAW, None).valuation_type,
            ValuationType.DIRECT_MARKET_VALUE,
        )
        self.assertEqual(result.valuation(Grader.RAW, None).mid, Decimal("24.0000"))
        self.assertEqual(source.mode, "LIVE")
        self.assertEqual(source.access_mechanism, GCC_V4_ACCESS_MECHANISM)
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(source.inventory_pages_requested, 1)

        diagnostic = LiveRawPipelineDiagnostic(
            "client", "secret", session=object(), gcc_history_provider=provider
        )
        rendered = render_live_raw_pipeline_summary(
            diagnostic._summary(
                OAuthAggregate("200", True, 7200),
                (MarketplaceAggregate("EBAY_US"),),
            )
        )
        self.assertIn("=== V5 LIVE RAW → GCC MARKET SUMMARY ===", rendered)
        self.assertIn("mode: LIVE", rendered)
        self.assertIn(f"access mechanism: {GCC_V4_ACCESS_MECHANISM}", rendered)
        self.assertIn("provider: European Central Bank", rendered)
        self.assertIn("rate date: 2026-08-07", rendered)
        self.assertIn("CardGrader calls: 0", rendered)
        self.assertNotIn("anonymized-fixture", rendered)

    def test_source_reuses_identity_cache_in_memory(self):
        source = source_for()
        canonical = GCCSaleParser().parse_record(
            {
                "status": "sold",
                "price": "1",
                "currency": "EUR",
                "card_name": "Charizard",
                "set_name": "Base Set",
                "card_number": "4/102",
                "language": "English",
                "grader": "RAW",
            }
        ).identity
        first = source.fetch(canonical)
        second = source.fetch(canonical)
        self.assertEqual(first, second)
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(source.identity_cache_hits, 1)

    def test_adapter_suppresses_v4_listing_detail_logs(self):
        source = source_for()
        canonical = GCCSaleParser().parse_record(
            {
                "status": "sold",
                "price": "1",
                "currency": "EUR",
                "card_name": "Charizard",
                "set_name": "Base Set",
                "card_number": "4/102",
                "language": "English",
                "grader": "RAW",
            }
        ).identity
        output = io.StringIO()
        with redirect_stdout(output):
            source.fetch(canonical)
        self.assertEqual(output.getvalue(), "")

    def test_identity_conflict_never_opens_gcc_item_page(self):
        source = source_for()
        provider = GCCHistoryProvider(
            GCCProviderConfig(enabled=True), source, today=date(2026, 8, 10)
        )
        result = provider.market_for(target_identity("Base Set 2"), "USD")
        self.assertEqual(result.records_received, 0)
        self.assertEqual(source.live_calls, 0)
        self.assertGreaterEqual(source.identity_conflicts, 1)

    def test_ambiguous_grade_is_kept_but_not_an_exact_numeric_comp(self):
        source = source_for(body="Historique des ventes\nPSA 9 PCA 10\n100 €")
        records = source.fetch(
            GCCSaleParser().parse_record(
                {
                    "status": "sold",
                    "price": "1",
                    "currency": "EUR",
                    "card_name": "Charizard",
                    "set_name": "Base Set",
                    "card_number": "4/102",
                    "language": "English",
                    "grader": "RAW",
                }
            ).identity
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["grader"], "UNKNOWN")
        self.assertIsNone(records[0]["grade"])
        self.assertEqual(source.parsing.grade_ambiguous, 1)


if __name__ == "__main__":
    unittest.main()
