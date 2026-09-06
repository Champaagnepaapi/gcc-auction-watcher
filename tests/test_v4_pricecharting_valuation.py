from __future__ import annotations

from datetime import datetime, timezone

import watcher
import v4_pricecharting_valuation as pc


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payloads.pop(0))


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


def _provider(*, grade="10", value_key="manual-only-price", value=5000):
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


def test_pricecharting_psa10_is_strong_guide_not_fake_sold(monkeypatch):
    provider, session = _provider()
    monkeypatch.setattr(watcher, "get_psa_apr_usd_per_eur", lambda: 1.0)

    evidence = pc.pricecharting_evidence_for_lot(
        _lot(),
        now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        provider=provider,
    )

    assert evidence.status == watcher.EXTERNAL_MATCHED
    assert evidence.strength == watcher.EVIDENCE_STRONG
    assert evidence.source == "pricecharting"
    assert evidence.estimate is not None
    assert evidence.estimate.central == 50.0
    assert evidence.estimate.adaptive_discount_pct >= 40.0
    assert evidence.comparables == []
    assert evidence.estimate.kept_comparables == []
    assert evidence.estimate.exact_grade_count == 0
    assert "aucune vente item-level" in evidence.estimate.rationale
    assert len(session.calls) == 2
    assert "test-token-never-log" not in repr(provider.config)
    assert all("test-token-never-log" not in url for url, _ in session.calls)


def test_pricecharting_generic_grade9_stays_weak(monkeypatch):
    provider, _session = _provider(
        grade="9", value_key="graded-price", value=8000
    )
    monkeypatch.setattr(watcher, "get_psa_apr_usd_per_eur", lambda: 1.0)

    evidence = pc.pricecharting_evidence_for_lot(
        _lot(grade="9"), provider=provider
    )

    assert evidence.status == watcher.EXTERNAL_MATCHED
    assert evidence.strength == watcher.EVIDENCE_WEAK
    assert evidence.estimate is not None
    assert evidence.estimate.central == 80.0
    assert "générique" in evidence.estimate.rationale


def test_missing_token_is_fail_visible_without_network():
    session = _Session([])
    provider = pc.PriceChartingProvider(
        config=pc.PriceChartingConfig(
            enabled=True,
            token=None,
            minimum_request_interval_seconds=0.0,
        ),
        session=session,
    )

    evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)

    assert evidence.status == watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
    assert evidence.source == "pricecharting"
    assert "token absent" in evidence.note
    assert session.calls == []


def test_source_role_installer_never_allows_direct_ebay_valuation(monkeypatch):
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

    monkeypatch.setattr(watcher, "fetch_external_market_evidence", fake_existing)
    monkeypatch.setattr(pc, "pricecharting_evidence_for_lot", lambda lot, now=None: pc_evidence)
    monkeypatch.setattr(watcher, "EBAY_ENABLED", True)
    pc.install_v4_pricecharting_valuation_source_roles()

    result = watcher.fetch_external_market_evidence(
        None,
        _candidate(),
        watcher.ValidationBudgets(),
        watcher.ExternalMarketDiagnostics(),
        now,
    )

    assert observed["ebay_enabled_during_fallback"] is False
    assert watcher.EBAY_ENABLED is True
    assert result.source == "pricecharting"
    assert result.strength == watcher.EVIDENCE_STRONG


def test_strong_psa_apr_still_precedes_pricecharting(monkeypatch):
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    called = {"pc": 0}
    estimate = watcher.MarketEstimate(
        low=45.0,
        central=50.0,
        high=55.0,
        kept_comparables=[
            watcher.ComparableSale(50.0, source="psa", grader="PSA", grade=10.0)
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
        assert watcher.EBAY_ENABLED is False
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

    monkeypatch.setattr(watcher, "fetch_external_market_evidence", fake_existing)
    monkeypatch.setattr(pc, "pricecharting_evidence_for_lot", fake_pc)
    monkeypatch.setattr(watcher, "EBAY_ENABLED", True)
    pc.install_v4_pricecharting_valuation_source_roles()

    result = watcher.fetch_external_market_evidence(
        None,
        _candidate(),
        watcher.ValidationBudgets(),
        watcher.ExternalMarketDiagnostics(),
        now,
    )

    assert result.source == "psa"
    assert called["pc"] == 0
