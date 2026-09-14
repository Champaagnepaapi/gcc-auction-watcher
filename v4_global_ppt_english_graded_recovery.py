"""Bounded Global recovery for exact English PSA 8/9/10 PPT aggregates.

PokemonPriceTracker documents English card coverage and grade-specific eBay sold
aggregates beyond PSA 10. The legacy Global adapter was intentionally narrower
(Japanese PSA 10 only). This module widens retrieval only after an exact TCGdex
canonical exists and reuses the same fail-closed macro/material matcher.

It never turns marketplace ASK data into valuation evidence and never bypasses a
provider restriction. PPT remains SOLD_AGGREGATED in the existing correlated
eBay family.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Optional

from ecb_fx import ECBCurrencyConverter
import v4_canonical_multimarket as multimarket
import v4_global_live_confirmed as confirmed
import v4_global_ppt_confirmation as ppt
from v4_global_market_core import CommercialIdentity


_ORIGINAL_FETCH = confirmed.fetch_snapshot
_INSTALLED = False
_SUPPORTED_PSA_GRADES = frozenset({8.0, 9.0, 10.0})


def _grade_value(identity: CommercialIdentity) -> Optional[float]:
    try:
        value = float(str(identity.grade).strip())
    except (TypeError, ValueError):
        return None
    return value if value in _SUPPORTED_PSA_GRADES else None


def _eligible(identity: CommercialIdentity) -> bool:
    return bool(
        ppt._language_code(identity.language) == "en"
        and ppt._norm(identity.grader) == "psa"
        and _grade_value(identity) is not None
    )


def _provider_error(status: int, *, provider_set_id: str = "", resolution: str = "") -> ppt.PptSnapshot:
    if status == 429:
        return ppt.PptSnapshot(
            "RATE_LIMIT",
            note="HTTP 429",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    return ppt.PptSnapshot(
        "PROVIDER_ERROR",
        note=f"HTTP {status}",
        provider_set_id=provider_set_id,
        identity_resolution=resolution,
    )


def fetch_english_graded_snapshot(
    identity: CommercialIdentity,
    *,
    api_key: str,
    budget: ppt.PptBudget,
    session,
    fx: ECBCurrencyConverter,
    timeout: float = 15.0,
    now=None,
    canonical: Optional[multimarket.CanonicalCard] = None,
) -> ppt.PptSnapshot:
    """Recover exact English PSA 8/9/10 through the existing strict PPT gate."""
    baseline = _ORIGINAL_FETCH(
        identity,
        api_key=api_key,
        budget=budget,
        session=session,
        fx=fx,
        timeout=timeout,
        now=now,
        canonical=canonical,
    )
    if baseline.status not in {"BLOCKED_LANGUAGE", "BLOCKED_GRADE"}:
        return baseline
    if not _eligible(identity):
        return baseline
    if not api_key:
        return ppt.PptSnapshot("PROVIDER_DISABLED", note="PPT key unavailable")
    if canonical is None or canonical.status != "EXACT" or not canonical.card_id:
        return ppt.PptSnapshot(
            "TCGDEX_UNRESOLVED",
            note="exact canonical required before English PPT; no network",
        )

    # PPT search is documented as multi-word across name/set/number. Retrieval is
    # deliberately narrow, but proof comes only from _match_canonical below.
    query = " ".join(
        value.strip()
        for value in (identity.name, identity.set_name, identity.number)
        if str(value or "").strip()
    )
    status, payload = ppt._request(
        session,
        api_key,
        budget,
        {"language": "english", "search": query, "limit": 5},
        timeout,
    )
    if status is None:
        return ppt.PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
    if status != 200:
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
        return _provider_error(status)

    match_status, row, proof = ppt._match_canonical(
        identity,
        canonical,
        ppt._rows(payload),
    )
    if match_status != "EXACT" or row is None:
        return ppt.PptSnapshot(
            match_status,
            match_proof=proof,
            note=proof or match_status,
            identity_resolution=proof,
        )

    tcgplayer_id = row.get("tcgPlayerId") or row.get("tcgplayerId")
    provider_set_id = str(row.get("setId") or row.get("set_id") or "").strip()
    if not tcgplayer_id:
        return ppt.PptSnapshot(
            "CLEAN_INSUFFICIENT",
            note="TCGPLAYER_ID_MISSING",
            provider_set_id=provider_set_id,
            identity_resolution=proof,
        )

    status, deep_payload = ppt._request(
        session,
        api_key,
        budget,
        {
            "language": "english",
            "tcgPlayerId": str(tcgplayer_id),
            "includeHistory": "true",
            "includeEbay": "true",
            "includeCardmarket": "false",
            "days": 180,
            "maxDataPoints": 180,
        },
        timeout,
    )
    if status is None:
        return ppt.PptSnapshot(
            "PENDING_BUDGET",
            note=budget.blocked_reason,
            provider_set_id=provider_set_id,
            identity_resolution=proof,
        )
    if status != 200:
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
        return _provider_error(
            status,
            provider_set_id=provider_set_id,
            resolution=proof,
        )

    deep_status, deep_row, deep_proof = ppt._match_canonical(
        identity,
        canonical,
        ppt._rows(deep_payload),
        provider_set_id=provider_set_id,
    )
    if deep_status != "EXACT" or deep_row is None:
        return ppt.PptSnapshot(
            deep_status,
            match_proof=deep_proof,
            note="deep identity not exact",
            provider_set_id=provider_set_id,
            identity_resolution=proof or deep_proof,
        )
    if not ppt._deep_coordinate_consistent(deep_row, tcgplayer_id):
        return ppt.PptSnapshot(
            "CLEAN_NO_MATCH",
            note="DEEP_COORDINATE_CONFLICT",
            provider_set_id=provider_set_id,
            identity_resolution=proof,
        )

    snapshot = ppt._snapshot_from_deep_row(
        identity,
        deep_row,
        fx=fx,
        observed_at=now,
        provider_set_id=provider_set_id,
        resolution=proof or deep_proof,
    )
    return replace(
        snapshot,
        note=(
            "PPT English eBay graded aggregate; exact TCGdex macro/material gate; "
            "ASK/current auction never used"
        ),
    )


def install_global_ppt_english_graded_recovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    confirmed.fetch_snapshot = fetch_english_graded_snapshot
    _INSTALLED = True
