"""Exact-set PokemonPriceTracker shadow adapter for Japan Edge.

This module hardens the experimental PPT Japanese shadow without changing the
production Japan Edge decision path:
- versioned exact Japanese set-code mapping (provider setId), never fuzzy set proof;
- bounded provider candidate diagnostics when a lookup does not match;
- exact Japanese + setId + collector number + sensitive-variant proof before use;
- universal non-economic safety fields, including PENDING_BUDGET rows;
- SOLD_AGGREGATED only, correlated with the PokeTrace/eBay aggregate family.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Optional, Sequence

import requests

import japan_edge_ppt_shadow as legacy
from ecb_fx import ECBCurrencyConverter

# Exact official Japanese set codes for the current live leads. New sets must be
# added deliberately; an unmapped set fails closed and consumes no PPT credit.
JP_SET_ID_MAP: dict[tuple[str, int], str] = {
    ("151", 2023): "sv2a",
    ("pokemon card 151", 2023): "sv2a",
    ("vstar universe", 2022): "s12a",
}

DIAGNOSTIC_FIELDS = (
    "name",
    "setId",
    "setName",
    "cardNumber",
    "language",
    "tcgPlayerId",
    "externalCatalogId",
    "printing",
    "variant",
    "rarity",
)
MAX_DIAGNOSTIC_CANDIDATES = 10


def expected_provider_set_id(identity: legacy.base.Identity) -> Optional[str]:
    return JP_SET_ID_MAP.get((legacy._norm(identity.set_name), int(identity.year)))


def _row_set_id(row: Mapping[str, object]) -> str:
    return legacy._norm(row.get("setId") or row.get("set_id"))


def provider_candidate_diagnostics(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        item = {field: row.get(field) for field in DIAGNOSTIC_FIELDS if row.get(field) is not None}
        fingerprint = tuple(str(item.get(field) or "") for field in DIAGNOSTIC_FIELDS)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        output.append(item)
        if len(output) >= MAX_DIAGNOSTIC_CANDIDATES:
            break
    return output


def match_japanese_catalog_identity(
    identity: legacy.base.Identity,
    rows: Sequence[Mapping[str, object]],
    expected_set_id: str,
) -> legacy.PptMatch:
    if not legacy._language_is_japanese(identity.language):
        return legacy.PptMatch("BLOCKED_LANGUAGE", reason="PHYSICAL_CARD_NOT_JAPANESE")

    expected_id = legacy._norm(expected_set_id)
    expected_number = legacy._collector(identity.number)
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        if not legacy._language_is_japanese(row.get("language")):
            continue
        if _row_set_id(row) != expected_id:
            continue
        if legacy._collector(row.get("cardNumber") or row.get("number")) != expected_number:
            continue
        candidates.append(row)

    if not candidates:
        return legacy.PptMatch("CLEAN_NO_MATCH", reason="JP_SET_ID_NUMBER_NOT_FOUND")
    if len(candidates) > 1:
        return legacy.PptMatch("AMBIGUOUS", reason="MULTIPLE_JP_SET_ID_NUMBER_ROWS")

    row = candidates[0]
    provider_blob = legacy._provider_identity_blob(row)
    for claim in legacy._sensitive_claims(identity):
        if claim not in provider_blob:
            return legacy.PptMatch("MICROVARIANT_UNPROVEN", reason=f"MISSING_PROVIDER_CLAIM:{claim}")
    return legacy.PptMatch("EXACT", row=row, reason="JP_LANGUAGE_SET_ID_NUMBER_AND_VARIANT")


def _request_cards(
    session: requests.Session,
    api_key: str,
    budget: legacy.PptBudget,
    params: Mapping[str, object],
    timeout: float,
) -> tuple[Optional[int], object | None]:
    return legacy._request(session, api_key, budget, params, timeout)


def fetch_japanese_snapshot_catalog(
    identity: legacy.base.Identity,
    *,
    api_key: str,
    budget: legacy.PptBudget,
    session: requests.Session,
    fx: ECBCurrencyConverter,
    timeout: float = 15.0,
    now=None,
) -> tuple[legacy.PptJapaneseSnapshot, dict[str, object]]:
    observed_at = now or legacy.datetime.now(legacy.timezone.utc)
    diagnostics: dict[str, object] = {
        "provider_set_id_expected": expected_provider_set_id(identity),
        "provider_candidates": [],
        "lookup_strategy": "EXACT_SET_ID",
    }

    if not legacy._language_is_japanese(identity.language):
        return legacy.PptJapaneseSnapshot(status="BLOCKED_LANGUAGE", note="physical card is not Japanese"), diagnostics
    if legacy._norm(identity.grader) != "psa" or str(identity.grade).strip() not in {"10", "10.0"}:
        return legacy.PptJapaneseSnapshot(status="BLOCKED_GRADE", grader=identity.grader, grade=identity.grade, note="Japan Edge PPT shadow currently requires exact PSA 10"), diagnostics

    set_id = expected_provider_set_id(identity)
    if not set_id:
        return legacy.PptJapaneseSnapshot(status="CATALOG_SET_ID_UNMAPPED", note="Japanese set has no reviewed exact PPT setId mapping"), diagnostics

    scoped_params = {
        "language": "japanese",
        "setId": set_id,
        "search": identity.number,
        "limit": 10,
    }
    status, payload = _request_cards(session, api_key, budget, scoped_params, timeout)
    if status is None:
        return legacy.PptJapaneseSnapshot(status="PENDING_BUDGET", note=budget.blocked_reason), diagnostics
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return legacy.PptJapaneseSnapshot(status="RATE_LIMIT", note="HTTP 429"), diagnostics
    if status != 200:
        return legacy.PptJapaneseSnapshot(status="PROVIDER_ERROR", note=f"HTTP {status}"), diagnostics

    rows = legacy._rows(payload)
    diagnostics["provider_candidates"] = provider_candidate_diagnostics(rows)
    match = match_japanese_catalog_identity(identity, rows, set_id)

    # Diagnostic-only broad retry: useful when PPT's catalog uses an unexpected
    # setId. It may enrich the artifact but can become evidence only if the row
    # independently proves the reviewed expected setId above.
    if match.status == "CLEAN_NO_MATCH" and budget.can_call():
        broad_status, broad_payload = _request_cards(
            session,
            api_key,
            budget,
            {"language": "japanese", "search": identity.number, "limit": 10},
            timeout,
        )
        if broad_status == 200:
            broad_rows = legacy._rows(broad_payload)
            diagnostics["lookup_strategy"] = "EXACT_SET_ID_THEN_BROAD_DIAGNOSTIC"
            diagnostics["provider_candidates"] = provider_candidate_diagnostics([*rows, *broad_rows])
            match = match_japanese_catalog_identity(identity, broad_rows, set_id)
        elif broad_status == 429:
            budget.blocked_reason = "RATE_LIMIT"

    if match.status != "EXACT" or match.row is None:
        return legacy.PptJapaneseSnapshot(status=match.status, match_proof=match.reason, note=match.reason), diagnostics

    tcgplayer_id = match.row.get("tcgPlayerId") or match.row.get("tcgplayerId")
    if not tcgplayer_id:
        return legacy.PptJapaneseSnapshot(status="CLEAN_INSUFFICIENT", match_proof=match.reason, note="TCGPLAYER_ID_MISSING"), diagnostics

    deep_params = {
        "language": "japanese",
        "tcgPlayerId": str(tcgplayer_id),
        "includeHistory": "true",
        "includeEbay": "true",
        "days": 180,
        "maxDataPoints": 180,
    }
    status, payload = _request_cards(session, api_key, budget, deep_params, timeout)
    if status is None:
        return legacy.PptJapaneseSnapshot(status="PENDING_BUDGET", match_proof=match.reason, note=budget.blocked_reason), diagnostics
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return legacy.PptJapaneseSnapshot(status="RATE_LIMIT", match_proof=match.reason, note="HTTP 429"), diagnostics
    if status != 200:
        return legacy.PptJapaneseSnapshot(status="PROVIDER_ERROR", match_proof=match.reason, note=f"HTTP {status}"), diagnostics

    deep_rows = legacy._rows(payload)
    diagnostics["deep_provider_candidates"] = provider_candidate_diagnostics(deep_rows)
    deep_match = match_japanese_catalog_identity(identity, deep_rows, set_id)
    if deep_match.status != "EXACT" or deep_match.row is None:
        return legacy.PptJapaneseSnapshot(status=deep_match.status, match_proof=deep_match.reason, note="DEEP_IDENTITY_NOT_EXACT"), diagnostics

    aggregate = legacy._aggregate(deep_match.row, identity.grader, identity.grade)
    if aggregate is None:
        return legacy.PptJapaneseSnapshot(status="CLEAN_NO_MATCH", match_proof=deep_match.reason, note="PSA10_BUCKET_MISSING"), diagnostics

    centers = [value for value in (aggregate["median"], aggregate["smart"], aggregate["average"]) if isinstance(value, (int, float)) and value > 0]
    fair_usd = float(median(centers)) if centers else None
    fair_eur = None
    if fair_usd is not None:
        converted = fx.convert(Decimal(str(fair_usd)), "USD", "EUR", observed_at.date())
        if converted is not None and converted > 0:
            fair_eur = round(float(converted), 2)

    history = legacy._history(deep_match.row, identity.grader, identity.grade)
    m30, v30 = legacy._window_metrics(history, 30, observed_at)
    m90, v90 = legacy._window_metrics(history, 90, observed_at)
    m180, v180 = legacy._window_metrics(history, 180, observed_at)

    if fair_usd is not None and fair_eur is None:
        final_status = "FX_UNAVAILABLE"
    elif fair_eur is None or int(aggregate["count"]) <= 0:
        final_status = "CLEAN_INSUFFICIENT"
    else:
        final_status = "MATCHED"

    return legacy.PptJapaneseSnapshot(
        status=final_status,
        fair_value_usd=round(fair_usd, 2) if fair_usd is not None else None,
        fair_value_eur=fair_eur,
        median_price_usd=aggregate["median"],
        average_price_usd=aggregate["average"],
        smart_market_price_usd=aggregate["smart"],
        sales_count=int(aggregate["count"]),
        last_sale_date=aggregate["last_sale_date"],
        momentum_30d_pct=m30,
        momentum_90d_pct=m90,
        momentum_180d_pct=m180,
        sales_velocity_30d=v30,
        sales_velocity_90d=v90,
        sales_velocity_180d=v180,
        match_proof=deep_match.reason,
        note="PPT Japanese eBay graded aggregate; exact reviewed setId; same upstream family as PokeTrace eBay aggregate",
    ), diagnostics


def _safe_shadow_payload(
    snapshot: legacy.PptJapaneseSnapshot,
    *,
    diagnostics: Optional[Mapping[str, object]] = None,
    poketrace_fair: Optional[float] = None,
) -> dict[str, object]:
    consistency, ratio = legacy._provider_consistency(snapshot.fair_value_eur, poketrace_fair)
    output = asdict(snapshot)
    if diagnostics:
        output.update(dict(diagnostics))
    output.update(
        {
            "poketrace_provider_consistency": consistency,
            "ppt_vs_poketrace_center_ratio": ratio,
            "independent_market_increment": 0,
            "production_decision_use": False,
            "notification_use": False,
        }
    )
    return output


def enrich_report_catalog(
    report: Mapping[str, object],
    *,
    api_key: str,
    budget: legacy.PptBudget,
    session: requests.Session,
    fx: ECBCurrencyConverter,
    max_candidates: int,
    timeout: float = 15.0,
) -> dict[str, object]:
    output = dict(report)
    raw_rows = report.get("opportunities") if isinstance(report.get("opportunities"), Sequence) else []
    rows: list[dict[str, object]] = []
    attempted = 0
    matched = 0

    for raw_row in raw_rows:
        row = dict(raw_row) if isinstance(raw_row, Mapping) else {}
        identity = legacy._identity_from_row(row)
        external = row.get("external_reference") if isinstance(row.get("external_reference"), Mapping) else {}
        try:
            poketrace_fair = float(external.get("fair_eur")) if external.get("fair_eur") is not None else None
        except (TypeError, ValueError):
            poketrace_fair = None

        if identity is None or not legacy._language_is_japanese(identity.language):
            row["ppt_japanese_shadow"] = _safe_shadow_payload(
                legacy.PptJapaneseSnapshot(status="BLOCKED_IDENTITY", note="Japanese physical identity missing"),
                poketrace_fair=poketrace_fair,
            )
            rows.append(row)
            continue

        if attempted >= max(0, max_candidates):
            row["ppt_japanese_shadow"] = _safe_shadow_payload(
                legacy.PptJapaneseSnapshot(status="PENDING_BUDGET", note="candidate cap reached"),
                diagnostics={"provider_set_id_expected": expected_provider_set_id(identity), "provider_candidates": [], "lookup_strategy": "NOT_ATTEMPTED_CANDIDATE_CAP"},
                poketrace_fair=poketrace_fair,
            )
            rows.append(row)
            continue

        attempted += 1
        snapshot, diagnostics = fetch_japanese_snapshot_catalog(
            identity,
            api_key=api_key,
            budget=budget,
            session=session,
            fx=fx,
            timeout=timeout,
        )
        if snapshot.status == "MATCHED":
            matched += 1
        row["ppt_japanese_shadow"] = _safe_shadow_payload(
            snapshot, diagnostics=diagnostics, poketrace_fair=poketrace_fair
        )
        rows.append(row)

    output["opportunities"] = rows
    output["ppt_japanese_shadow"] = {
        "enabled": True,
        "provider": legacy.PROVIDER,
        "evidence_class": legacy.EVIDENCE_CLASS,
        "correlation_group": legacy.CORRELATION_GROUP,
        "language": "Japanese",
        "identity_contract": "JP_LANGUAGE_EXACT_SET_ID_COLLECTOR_NUMBER_VARIANT",
        "attempted": attempted,
        "matched": matched,
        "http_calls": budget.http_calls,
        "credits": budget.credits,
        "daily_remaining": budget.daily_remaining,
        "blocked_reason": budget.blocked_reason,
        "independent_market_increment": 0,
        "production_decision_use": False,
        "notification_use": False,
    }
    return output


def main() -> None:
    parser = legacy.argparse.ArgumentParser()
    parser.add_argument("--input", default="japan_edge_report.json")
    parser.add_argument("--output", default="japan_edge_ppt_shadow_report.json")
    args = parser.parse_args()

    api_key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("POKEMONPRICETRACKER_API_KEY is required for an explicit Japan Edge PPT shadow run")

    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    budget = legacy.PptBudget(
        max_http_calls=legacy._env_int("JAPAN_EDGE_PPT_MAX_HTTP_CALLS", 8, 1),
        max_credits=legacy._env_int("JAPAN_EDGE_PPT_MAX_CREDITS", 40, 1),
        daily_remaining_floor=legacy._env_int("JAPAN_EDGE_PPT_DAILY_REMAINING_FLOOR", 15_000, 0),
        interval_seconds=legacy._env_float("JAPAN_EDGE_PPT_INTERVAL_SECONDS", 1.10, 0.0),
    )
    output = enrich_report_catalog(
        report,
        api_key=api_key,
        budget=budget,
        session=requests.Session(),
        fx=ECBCurrencyConverter(),
        max_candidates=legacy._env_int("JAPAN_EDGE_PPT_MAX_CANDIDATES", 4, 0),
        timeout=legacy._env_float("JAPAN_EDGE_PPT_TIMEOUT_SECONDS", 15.0, 1.0),
    )
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output.get("ppt_japanese_shadow", {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
