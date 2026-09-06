from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watcher
import v4_pricecharting_valuation as pc


class _Response:
    def __init__(self, payload=None, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        return response if isinstance(response, _Response) else _Response(response)


def _lot(*, grade="10"):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test",
        title="Poochyena",
        current_price=30.0,
        source_type="auction",
        grader="PSA",
        grade=grade,
        card_set="VSTAR Universe",
        card_number="208/172",
        language="Japanese",
    )


def _candidate(lot=None):
    lot = lot or _lot()
    gcc = watcher.GccMarketEvidence(
        lot=lot,
        sales=[],
        estimate=None,
        opportunity=None,
        branch=watcher.GCC_BRANCH_UNAVAILABLE,
        strength=watcher.EVIDENCE_UNAVAILABLE,
    )
    return watcher.ValuationCandidate(gcc)


def _provider(*, value_key="manual-only-price", value=5000):
    product = {
        "status": "success",
        "id": "pc-208",
        "product-name": "Poochyena #208",
        "console-name": "Pokemon Japanese VSTAR Universe",
        value_key: value,
    }
    session = _Session(
        [
            {"status": "success", "products": [product]},
            product,
        ]
    )
    config = pc.PriceChartingConfig(
        enabled=True,
        token="test-token-never-log",
        max_cards_per_run=8,
        minimum_request_interval_seconds=0.0,
    )
    return pc.PriceChartingProvider(config=config, session=session), session


class PriceChartingValuationTests(unittest.TestCase):
    def test_pricecharting_psa10_is_strong_guide_not_fake_sold(self):
        provider, session = _provider()
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(
                _lot(),
                now=datetime(2026, 9, 6, tzinfo=timezone.utc),
                provider=provider,
            )

        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(evidence.source, "pricecharting")
        self.assertIsNotNone(evidence.estimate)
        self.assertEqual(evidence.estimate.central, 50.0)
        self.assertGreaterEqual(evidence.estimate.adaptive_discount_pct, 40.0)
        self.assertEqual(evidence.comparables, [])
        self.assertEqual(evidence.estimate.kept_comparables, [])
        self.assertEqual(evidence.estimate.exact_grade_count, 0)
        self.assertIn("aucune vente item-level", evidence.estimate.rationale)
        self.assertEqual(len(session.calls), 2)
        self.assertNotIn("test-token-never-log", repr(provider.config))
        self.assertTrue(
            all("test-token-never-log" not in url for url, _ in session.calls)
        )

    def test_pricecharting_generic_grade9_stays_weak(self):
        provider, _session = _provider(value_key="graded-price", value=8000)
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(
                _lot(grade="9"), provider=provider
            )

        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_WEAK)
        self.assertIsNotNone(evidence.estimate)
        self.assertEqual(evidence.estimate.central, 80.0)
        self.assertIn("générique", evidence.estimate.rationale)

    def test_public_pricecharting_fallback_works_without_paid_token(self):
        search_html = """
        <html><body>
          <a href="/game/pokemon-japanese-vstar-universe/poochyena-208">Poochyena #208</a>
        </body></html>
        """
        product_html = """
        <html><body>
          <h1>Poochyena #208 Pokemon Japanese VSTAR Universe</h1>
          <div>Card Number: #208</div>
          <h2>Full Price Guide</h2>
          <div>Grade 9 $13.87</div>
          <div>PSA 10 $47.71</div>
        </body></html>
        """
        session = _Session(
            [
                _Response(text=search_html),
                _Response(text=product_html),
            ]
        )
        provider = pc.PriceChartingProvider(
            config=pc.PriceChartingConfig(
                enabled=True,
                token=None,
                max_cards_per_run=8,
                public_request_interval_seconds=0.0,
            ),
            session=session,
        )
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)

        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertIsNotNone(evidence.estimate)
        self.assertEqual(evidence.estimate.central, 47.71)
        self.assertEqual(evidence.comparables, [])
        self.assertIn("public price guide", evidence.note)
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.calls[0][0].endswith("/search-products"))
        self.assertTrue(
            session.calls[1][0].endswith(
                "/game/pokemon-japanese-vstar-universe/poochyena-208"
            )
        )

    def test_source_role_installer_never_allows_direct_ebay_valuation(self):
        observed = {}
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)

        def fake_existing(page, candidate, budgets, diagnostics, when):
            observed["ebay_enabled_during_fallback"] = watcher.EBAY_ENABLED
            return watcher.ExternalMarketEvidence(
                watcher.external_commercial_identity_key(candidate.lot),
                watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
                source="psa",
                note="APR unavailable",
                fetched_at=when,
            )

        estimate = watcher.MarketEstimate(
            low=50.0,
            central=50.0,
            high=50.0,
            kept_comparables=[],
            rejected_outliers=[],
            recent_90_count=0,
            dated_count=0,
            liquidity="non mesurée",
            dispersion="guide ponctuel",
            confidence="moyenne",
            adaptive_discount_pct=40.0,
            rationale="PriceCharting guide",
            source_counts={"pricecharting_guide": 1},
            exact_grade_count=0,
            same_grader_count=0,
            source_consistent=True,
        )
        pc_evidence = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(_lot()),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "pricecharting",
            estimate=estimate,
            note="guide",
            fetched_at=now,
        )

        with (
            patch.object(watcher, "fetch_external_market_evidence", fake_existing),
            patch.object(pc, "pricecharting_evidence_for_lot", return_value=pc_evidence),
            patch.object(watcher, "EBAY_ENABLED", True),
        ):
            pc.install_v4_pricecharting_valuation_source_roles()
            result = watcher.fetch_external_market_evidence(
                None,
                _candidate(),
                watcher.ValidationBudgets(),
                watcher.ExternalMarketDiagnostics(),
                now,
            )
            self.assertFalse(observed["ebay_enabled_during_fallback"])
            self.assertTrue(watcher.EBAY_ENABLED)
            self.assertEqual(result.source, "pricecharting")
            self.assertEqual(result.strength, watcher.EVIDENCE_STRONG)

    def test_strong_psa_apr_still_precedes_pricecharting(self):
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        called = {"pc": 0}
        estimate = watcher.MarketEstimate(
            low=45.0,
            central=50.0,
            high=55.0,
            kept_comparables=[
                watcher.ComparableSale(
                    50.0, source="psa", grader="PSA", grade=10.0
                )
            ],
            rejected_outliers=[],
            recent_90_count=1,
            dated_count=1,
            liquidity="faible",
            dispersion="faible",
            confidence="moyenne",
            adaptive_discount_pct=30.0,
            rationale="APR",
            source_counts={"psa": 1},
            exact_grade_count=1,
            same_grader_count=1,
            source_consistent=True,
        )

        def fake_existing(page, candidate, budgets, diagnostics, when):
            self.assertFalse(watcher.EBAY_ENABLED)
            return watcher.ExternalMarketEvidence(
                watcher.external_commercial_identity_key(candidate.lot),
                watcher.EXTERNAL_MATCHED,
                watcher.EVIDENCE_STRONG,
                "psa",
                estimate=estimate,
                fetched_at=when,
            )

        def fake_pc(lot, now=None):
            called["pc"] += 1
            raise AssertionError("PriceCharting should not run after strong APR")

        with (
            patch.object(watcher, "fetch_external_market_evidence", fake_existing),
            patch.object(pc, "pricecharting_evidence_for_lot", fake_pc),
            patch.object(watcher, "EBAY_ENABLED", True),
        ):
            pc.install_v4_pricecharting_valuation_source_roles()
            result = watcher.fetch_external_market_evidence(
                None,
                _candidate(),
                watcher.ValidationBudgets(),
                watcher.ExternalMarketDiagnostics(),
                now,
            )
            self.assertEqual(result.source, "psa")
            self.assertEqual(called["pc"], 0)


if __name__ == "__main__":
    unittest.main()
