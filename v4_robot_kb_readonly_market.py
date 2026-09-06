from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from datetime import datetime, timezone
from statistics import median
from typing import Any, Mapping, Optional
from urllib.parse import urlencode, urlparse

import requests

import watcher
import v4_canonical_multimarket as multimarket

_INSTALL_MARKER = "_v4_robot_kb_readonly_market_installed"
_DEFAULT_TIMEOUT_SECONDS = 2.5
_DEFAULT_MAX_REQUESTS = 50
_CACHE: dict[str, watcher.ExternalMarketEvidence] = {}
_REQUESTS_USED = 0


def _config() -> tuple[str, str, float, int]:
    url = os.getenv("ROBOT_KB_V4_READONLY_URL", "").strip().rstrip("/")
    token = os.getenv("ROBOT_KB_V4_READONLY_TOKEN", "").strip()
    try:
        timeout = max(0.5, min(float(os.getenv("ROBOT_KB_V4_READONLY_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS))), 8.0))
    except ValueError:
        timeout = _DEFAULT_TIMEOUT_SECONDS
    try:
        max_requests = max(1, min(int(os.getenv("ROBOT_KB_V4_READONLY_MAX_REQUESTS_PER_RUN", str(_DEFAULT_MAX_REQUESTS))), 120))
    except ValueError:
        max_requests = _DEFAULT_MAX_REQUESTS
    return url, token, timeout, max_requests


def _endpoint_is_safe(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    return parsed.scheme == "http" and (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}


def _grade_text(lot: watcher.Lot) -> str:
    try:
        value = float(lot.grade) if lot.grade is not None else None
    except (TypeError, ValueError):
        return ""
    if value is None or not math.isfinite(value):
        return ""
    return str(int(value)) if value.is_integer() else str(value)


def _parse_time(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _dispersion(low: float, central: float, high: float) -> str:
    if central <= 0:
        return "élevée"
    ratio = max(0.0, high - low) / central
    if ratio <= 0.30:
        return "faible"
    if ratio <= 0.60:
        return "moyenne"
    return "élevée"


def _evidence_from_payload(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> watcher.ExternalMarketEvidence:
    key = watcher.external_commercial_identity_key(lot)
    if int(payload.get("schema_version") or 0) != 1:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge schema unsupported", fetched_at=now)
    identity = payload.get("identity")
    if not isinstance(identity, Mapping):
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge identity missing", fetched_at=now)
    expected_grader = str(lot.grader or "").strip().upper()
    expected_grade = _grade_text(lot)
    if (
        str(identity.get("tcgdex_card_id") or "") != canonical.card_id
        or str(identity.get("grader") or "").strip().upper() != expected_grader
        or str(identity.get("grade") or "").strip() != expected_grade
        or str(identity.get("proof") or "") != "PROVEN_TCGDEX_AND_GRADE"
    ):
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge identity proof mismatch", fetched_at=now)

    rows = payload.get("sales")
    if not isinstance(rows, list):
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge sales payload invalid", fetched_at=now)

    parsed: list[tuple[float, datetime, str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        # GCC historical SOLD remains diagnostics/KB only under the external-FV policy.
        source_code = str(row.get("source_code") or "").strip().casefold()
        if not source_code or source_code == "gcc":
            continue
        if str(row.get("transaction_status") or "") != "COMPLETED":
            continue
        if str(row.get("currency") or "").upper() != "EUR":
            continue
        try:
            amount_minor = int(row.get("amount_minor"))
        except (TypeError, ValueError):
            continue
        sold_at = _parse_time(row.get("sold_at"))
        if amount_minor <= 0 or sold_at is None or sold_at > now:
            continue
        component = str(row.get("component_type") or "")
        if component not in {"ITEM_PRICE", "HAMMER_PRICE", "ACCEPTED_OFFER", "TOTAL"}:
            continue
        parsed.append((amount_minor / 100.0, sold_at, source_code, component))

    recent = [row for row in parsed if (now - row[1]).days <= 90]
    dated = recent if len(recent) >= 2 else [row for row in parsed if (now - row[1]).days <= 365]
    if len(dated) < 2:
        status = watcher.EXTERNAL_CLEAN_INSUFFICIENT if parsed else watcher.EXTERNAL_CLEAN_NO_MATCH
        strength = watcher.EVIDENCE_WEAK if parsed else watcher.EVIDENCE_UNAVAILABLE
        return watcher.ExternalMarketEvidence(
            key,
            status,
            strength,
            "robot_kb",
            note=f"Robot KB exact SOLD: {len(parsed)} usable non-GCC EUR sale(s), <2 within 365d",
            fetched_at=now,
        )

    prices = sorted(row[0] for row in dated)
    central = float(median(prices))
    low = min(prices)
    high = max(prices)
    dispersion = _dispersion(low, central, high)
    liquidity = "élevée" if len(dated) >= 5 else "moyenne" if len(dated) >= 3 else "faible"
    threshold = watcher.adaptive_discount_threshold(
        len(dated), dispersion, liquidity, len(recent), len(dated), len(dated), True, False
    )
    comparables = [
        watcher.ComparableSale(
            price=row[0],
            source="robot_kb",
            grader=expected_grader,
            grade=float(expected_grade),
            sold_at=row[1],
            context=f"Robot KB proven SOLD source={row[2]} component={row[3]}",
            exact_card=True,
            match_score=100,
            identity_provenance="PROVEN_TCGDEX_AND_GRADE",
        )
        for row in dated
    ]
    estimate = watcher.MarketEstimate(
        low=low,
        central=central,
        high=high,
        kept_comparables=comparables,
        rejected_outliers=[],
        recent_90_count=len(recent),
        dated_count=len(dated),
        liquidity=liquidity,
        dispersion=dispersion,
        confidence="moyenne" if dispersion != "élevée" else "faible",
        adaptive_discount_pct=threshold,
        rationale=(
            f"Robot KB exact completed SOLD, {len(dated)} sale(s) <=365d "
            f"({len(recent)} <=90d); GCC history excluded from V4 fair value"
        ),
        source_counts={f"robot_kb:{source}": sum(1 for item in dated if item[2] == source) for source in sorted({item[2] for item in dated})},
        exact_grade_count=len(dated),
        same_grader_count=len(dated),
        source_consistent=True,
        grade_arbitrage=False,
    )
    strength = watcher.EVIDENCE_STRONG if dispersion != "élevée" else watcher.EVIDENCE_WEAK
    status = watcher.EXTERNAL_MATCHED if strength == watcher.EVIDENCE_STRONG else watcher.EXTERNAL_CLEAN_INSUFFICIENT
    return watcher.ExternalMarketEvidence(
        key,
        status,
        strength,
        "robot_kb",
        estimate=estimate,
        comparables=comparables,
        note="Robot KB local read-only: exact TCGdex + exact grader/grade + COMPLETED SOLD only; ASK/snapshot/provider metric excluded",
        fetched_at=now,
    )


def robot_kb_evidence_for_lot(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    *,
    now: Optional[datetime] = None,
    session=requests,
) -> watcher.ExternalMarketEvidence:
    global _REQUESTS_USED
    effective_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key = watcher.external_commercial_identity_key(lot)
    url, token, timeout, max_requests = _config()
    if not url and not token:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_CLEAN_NO_MATCH, source="robot_kb", note="Robot KB V4 bridge disabled", fetched_at=effective_now)
    if not url or not token or not _endpoint_is_safe(url):
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB V4 bridge configuration invalid", fetched_at=effective_now)
    if canonical.status != "EXACT" or not canonical.card_id:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_CLEAN_NO_MATCH, source="robot_kb", note="Robot KB requires exact TCGdex identity", fetched_at=effective_now)
    grader = str(lot.grader or "").strip().upper()
    grade = _grade_text(lot)
    if not grader or not grade:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_CLEAN_NO_MATCH, source="robot_kb", note="Robot KB requires exact grader/grade", fetched_at=effective_now)

    cache_key = f"{canonical.card_id}|{grader}|{grade}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    if _REQUESTS_USED >= max_requests:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PENDING, source="robot_kb", note="Robot KB read-only request budget exhausted", fetched_at=effective_now)
    _REQUESTS_USED += 1
    query = urlencode({"tcgdex_card_id": canonical.card_id, "grader": grader, "grade": grade, "limit": 30})
    try:
        response = session.get(
            f"{url}/v1/exact-sold?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )
    except Exception as error:
        result = watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note=f"Robot KB bridge {type(error).__name__}", fetched_at=effective_now)
        return result
    if response.status_code in {401, 403}:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge authorization failed", fetched_at=effective_now)
    if response.status_code == 429:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_RATE_LIMITED, source="robot_kb", note="Robot KB bridge rate limited", fetched_at=effective_now)
    if response.status_code != 200:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note=f"Robot KB bridge HTTP {response.status_code}", fetched_at=effective_now)
    try:
        payload = response.json()
    except Exception:
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge invalid JSON", fetched_at=effective_now)
    if not isinstance(payload, Mapping):
        return watcher.ExternalMarketEvidence(key, watcher.EXTERNAL_PROVIDER_ERROR, source="robot_kb", note="Robot KB bridge invalid payload", fetched_at=effective_now)
    result = _evidence_from_payload(lot, canonical, payload, now=effective_now)
    if result.status in watcher.EXTERNAL_CACHEABLE_STATUSES or result.status == watcher.EXTERNAL_MATCHED:
        _CACHE[cache_key] = result
    return result


def reset_run_state() -> None:
    global _REQUESTS_USED
    _REQUESTS_USED = 0
    _CACHE.clear()


def install_v4_robot_kb_readonly_market() -> None:
    current = multimarket._poketrace_evidence
    if getattr(current, _INSTALL_MARKER, False):
        return
    reset_run_state()

    def robot_kb_then_existing(
        lot: watcher.Lot,
        canonical: multimarket.CanonicalCard,
        budget: multimarket.RequestBudget,
        now: datetime,
    ) -> watcher.ExternalMarketEvidence:
        kb = robot_kb_evidence_for_lot(lot, canonical, now=now)
        if kb.status == watcher.EXTERNAL_MATCHED and kb.strength == watcher.EVIDENCE_STRONG and kb.estimate is not None:
            return kb
        existing = current(lot, canonical, budget, now)
        if kb.note and "disabled" not in kb.note:
            existing = replace(existing, note=f"{existing.note}; Robot KB: {kb.status} {kb.note}".strip("; "))
        return existing

    setattr(robot_kb_then_existing, _INSTALL_MARKER, True)
    setattr(robot_kb_then_existing, "_wrapped_fetch", current)
    multimarket._poketrace_evidence = robot_kb_then_existing
    watcher.log(
        "Robot KB V4 bridge: optional read-only exact-SOLD authority before aggregate providers; "
        "GCC history excluded; disabled unless secure endpoint+token configured"
    )
