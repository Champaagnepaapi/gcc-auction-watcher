from __future__ import annotations

import watcher
from v4_external_fair_value_authority import (
    gcc_without_economic_authority,
    install_v4_external_fair_value_authority,
)


def _gcc(*, terminal: bool = False) -> watcher.GccMarketEvidence:
    lot = watcher.Lot(
        url="https://gradedcardcenter.com/item/test",
        title="PSA 10 Poochyena",
        current_price=30.0,
        source_type="auction",
        grader="PSA",
        grade="10",
        card_set="VSTAR Universe",
        card_number="208/172",
        language="Japanese",
    )
    sale = watcher.ComparableSale(
        price=24.0,
        source="gcc",
        grader="PSA",
        grade=10.0,
    )
    return watcher.GccMarketEvidence(
        lot=lot,
        sales=[sale],
        estimate=object(),  # type: ignore[arg-type]
        opportunity=object(),  # type: ignore[arg-type]
        branch=watcher.GCC_BRANCH_SUPPORTED,
        strength=watcher.EVIDENCE_STRONG,
        rejection="",
        terminal=terminal,
    )


def _external(
    status: str = watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
) -> watcher.ExternalMarketEvidence:
    return watcher.ExternalMarketEvidence(
        identity_key="poochyena|208/172|ja|psa|10",
        status=status,
        note="provider unavailable",
    )


def test_nonterminal_gcc_history_loses_economic_authority() -> None:
    original = _gcc()
    neutral = gcc_without_economic_authority(original)

    assert neutral.lot is original.lot
    assert neutral.sales == []
    assert neutral.estimate is None
    assert neutral.opportunity is None
    assert neutral.branch == watcher.GCC_BRANCH_UNAVAILABLE
    assert neutral.strength == watcher.EVIDENCE_UNAVAILABLE
    assert "historique GCC ignoré" in neutral.rejection
    assert neutral.terminal is False


def test_terminal_gcc_rejection_is_preserved() -> None:
    terminal = _gcc(terminal=True)
    assert gcc_without_economic_authority(terminal) is terminal


def test_unavailable_external_cannot_fallback_to_gcc_economics() -> None:
    result = watcher.arbitrate_market_evidence(
        gcc_without_economic_authority(_gcc()),
        _external(watcher.EXTERNAL_TRANSIENT_UNAVAILABLE),
    )

    assert result.opportunity is None
    assert result.external_decision == "UNAVAILABLE"


def test_pending_external_cannot_fallback_to_gcc_economics() -> None:
    result = watcher.arbitrate_market_evidence(
        gcc_without_economic_authority(_gcc()),
        _external(watcher.EXTERNAL_PENDING),
    )

    assert result.opportunity is None
    assert result.path == watcher.PATH_EXTERNAL_PENDING
    assert result.external_decision == "PENDING"


def test_installer_passes_neutralized_gcc_to_existing_arbitration(monkeypatch) -> None:
    captured = {}
    sentinel = object()

    def fake_arbitration(gcc, external):
        captured["gcc"] = gcc
        captured["external"] = external
        return sentinel

    monkeypatch.setattr(watcher, "arbitrate_market_evidence", fake_arbitration)
    install_v4_external_fair_value_authority()

    external = _external()
    result = watcher.arbitrate_market_evidence(_gcc(), external)

    assert result is sentinel
    assert captured["external"] is external
    assert captured["gcc"].sales == []
    assert captured["gcc"].estimate is None
    assert captured["gcc"].opportunity is None
    assert captured["gcc"].branch == watcher.GCC_BRANCH_UNAVAILABLE


def test_installer_does_not_neutralize_terminal_rejection(monkeypatch) -> None:
    captured = {}
    sentinel = object()

    def fake_arbitration(gcc, external):
        captured["gcc"] = gcc
        return sentinel

    monkeypatch.setattr(watcher, "arbitrate_market_evidence", fake_arbitration)
    install_v4_external_fair_value_authority()

    terminal = _gcc(terminal=True)
    assert watcher.arbitrate_market_evidence(terminal, _external()) is sentinel
    assert captured["gcc"] is terminal


def test_installer_is_idempotent(monkeypatch) -> None:
    def fake_arbitration(gcc, external):
        return (gcc, external)

    monkeypatch.setattr(watcher, "arbitrate_market_evidence", fake_arbitration)
    install_v4_external_fair_value_authority()
    installed_once = watcher.arbitrate_market_evidence
    install_v4_external_fair_value_authority()

    assert watcher.arbitrate_market_evidence is installed_once
