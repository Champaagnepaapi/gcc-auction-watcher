from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence

import requests

from .pokemonpricetracker_adapter import (
    CanonicalPptIdentity,
    cardmarket_eur,
    graded_aggregate,
    match_macro_identity,
    raw_usd,
    total_ebay_sales,
)

BASE_URL = "https://www.pokemonpricetracker.com/api/v2/cards"
HTTP_CALL_CAP = 50
CREDIT_CAP = 500
STOP_DAILY_REMAINING = 15_000
INTERVAL_SECONDS = 1.10
REPORT_JSON = Path("pokemonpricetracker_full_benchmark.json")
REPORT_MD = Path("pokemonpricetracker_full_benchmark.md")

# High-value/liquid prints plus vintage sentinels. These are macro identities only;
# microvariant/edition proof is evaluated from provider fields and never inferred.
PANEL: tuple[CanonicalPptIdentity, ...] = (
    CanonicalPptIdentity("swsh7-215", "Umbreon VMAX", "Evolving Skies", "215", "en"),
    CanonicalPptIdentity("swsh8-271", "Gengar VMAX", "Fusion Strike", "271", "en"),
    CanonicalPptIdentity("swsh11-186", "Giratina V", "Lost Origin", "186", "en"),
    CanonicalPptIdentity("swsh12-186", "Lugia V", "Silver Tempest", "186", "en"),
    CanonicalPptIdentity("swsh9-154", "Charizard V", "Brilliant Stars", "154", "en"),
    CanonicalPptIdentity("swsh7-218", "Rayquaza VMAX", "Evolving Skies", "218", "en"),
    CanonicalPptIdentity("swsh7-205", "Leafeon VMAX", "Evolving Skies", "205", "en"),
    CanonicalPptIdentity("swsh7-212", "Sylveon VMAX", "Evolving Skies", "212", "en"),
    CanonicalPptIdentity("swsh8-270", "Espeon VMAX", "Fusion Strike", "270", "en"),
    CanonicalPptIdentity("swsh7-192", "Dragonite V", "Evolving Skies", "192", "en"),
    CanonicalPptIdentity("swsh6-201", "Blaziken VMAX", "Chilling Reign", "201", "en"),
    CanonicalPptIdentity("swsh5-155", "Tyranitar V", "Battle Styles", "155", "en"),
    CanonicalPptIdentity("swsh10-172", "Machamp V", "Astral Radiance", "172", "en"),
    CanonicalPptIdentity("swsh11-180", "Aerodactyl V", "Lost Origin", "180", "en"),
    CanonicalPptIdentity("swsh4-188", "Pikachu VMAX", "Vivid Voltage", "188", "en"),
    CanonicalPptIdentity("base1-4", "Charizard", "Base Set", "4", "en"),
    CanonicalPptIdentity("neo1-9", "Lugia", "Neo Genesis", "9", "en"),
    CanonicalPptIdentity("base1-58", "Pikachu", "Base Set", "58", "en"),
)


def payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, Mapping):
        return [data]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return [row for row in data if isinstance(row, Mapping)]
    return []


def quota_headers(headers: Mapping[str, object]) -> dict[str, str]:
    keep: dict[str, str] = {}
    for key, value in headers.items():
        lowered = str(key).casefold()
        if any(token in lowered for token in ("rate", "quota", "api-call", "credit")):
            keep[str(key)] = str(value)
    return keep


def _header_int(headers: Mapping[str, object], name: str) -> int | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() != wanted:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
    return None


def search_attempts(card: CanonicalPptIdentity) -> tuple[dict[str, object], ...]:
    # First query is set-constrained and fixes the Lugia/collector-number failure
    # observed in contract run 31899734290. Later attempts broaden retrieval only;
    # acceptance still requires externalCatalogId or exact set+number proof.
    return (
        {"search": card.name, "setName": card.set_name, "limit": 5},
        {"search": f"{card.name} {card.number}", "setName": card.set_name, "limit": 5},
        {"search": card.name, "limit": 10},
    )


def _history_points(container: object) -> list[Mapping[str, object]]:
    if isinstance(container, Sequence) and not isinstance(container, (str, bytes)):
        return [row for row in container if isinstance(row, Mapping)]
    if isinstance(container, Mapping):
        history = container.get("history")
        if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
            return [row for row in history if isinstance(row, Mapping)]
    return []


def _series_span(points: Sequence[Mapping[str, object]]) -> dict[str, object]:
    dates = sorted(str(row.get("date")) for row in points if row.get("date"))
    return {
        "points": len(points),
        "oldest": dates[0] if dates else None,
        "newest": dates[-1] if dates else None,
    }


def _raw_history_summary(row: Mapping[str, object]) -> dict[str, object]:
    history = row.get("priceHistory") if isinstance(row.get("priceHistory"), Mapping) else {}
    conditions = history.get("conditions") if isinstance(history.get("conditions"), Mapping) else {}
    variants = history.get("variants") if isinstance(history.get("variants"), Mapping) else {}
    condition_series = {
        str(name): _series_span(_history_points(payload))
        for name, payload in conditions.items()
    }
    variant_series: dict[str, object] = {}
    for variant, condition_map in variants.items():
        if not isinstance(condition_map, Mapping):
            continue
        for condition, payload in condition_map.items():
            variant_series[f"{variant}/{condition}"] = _series_span(_history_points(payload))
    return {
        "totalDataPoints": history.get("totalDataPoints"),
        "lastUpdated": history.get("lastUpdated"),
        "conditions": condition_series,
        "variants": variant_series,
    }


def _grade_prefix(key: object) -> str:
    match = re.match(r"([a-z]+)", str(key or "").casefold())
    return match.group(1).upper() if match else "UNKNOWN"


def _ebay_summary(row: Mapping[str, object]) -> dict[str, object]:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    grades = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    histories = ebay.get("priceHistory") if isinstance(ebay.get("priceHistory"), Mapping) else {}
    psa10 = graded_aggregate(row, grader="PSA", grade=10)
    history_spans: dict[str, object] = {}
    for grade_key, days in histories.items():
        if not isinstance(days, Mapping):
            continue
        dates = sorted(str(value) for value in days.keys())
        try:
            sale_count = sum(
                int(payload.get("count") or 0)
                for payload in days.values()
                if isinstance(payload, Mapping)
            )
        except (TypeError, ValueError):
            sale_count = 0
        history_spans[str(grade_key)] = {
            "days": len(days),
            "sale_count_in_daily_history": sale_count,
            "oldest": dates[0] if dates else None,
            "newest": dates[-1] if dates else None,
        }
    return {
        "totalSales": total_ebay_sales(row),
        "totalValue": ebay.get("totalValue"),
        "gradesTracked": list(ebay.get("gradesTracked") or []),
        "gradeBuckets": len(grades),
        "graders": sorted({_grade_prefix(key) for key in grades.keys()}),
        "dateRangeStart": ebay.get("dateRangeStart"),
        "dateRangeEnd": ebay.get("dateRangeEnd"),
        "salesByGrade": grades,
        "dailyGradeHistory": history_spans,
        "psa10": asdict(psa10) if psa10 is not None else None,
        "semantics": "PROVIDER_AGGREGATED_EBAY_SOLD_BY_GRADE_NOT_ITEM_LEVEL_SALE",
    }


def _cardmarket_summary(row: Mapping[str, object]) -> dict[str, object]:
    cm = row.get("cardmarketPrices") if isinstance(row.get("cardmarketPrices"), Mapping) else {}
    variants = cm.get("variants") if isinstance(cm.get("variants"), Mapping) else {}
    variant_history: dict[str, object] = {}
    for name, payload in variants.items():
        if not isinstance(payload, Mapping):
            continue
        variant_history[str(name)] = {
            "latestPrice": payload.get("latestPrice"),
            "latestDate": payload.get("latestDate"),
            **_series_span(_history_points(payload)),
        }
    return {
        "marketEur": cm.get("marketEur"),
        "lowEur": cm.get("lowEur"),
        "trendEur": cm.get("trendEur"),
        "lastUpdated": cm.get("lastUpdated"),
        "variants": variant_history,
    }


def summarize_deep_row(row: Mapping[str, object]) -> dict[str, object]:
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    return {
        "name": row.get("name"),
        "setName": row.get("setName"),
        "cardNumber": row.get("cardNumber"),
        "externalCatalogId": row.get("externalCatalogId"),
        "tcgPlayerId": row.get("tcgPlayerId") or row.get("tcgplayerId"),
        "rawUsd": raw_usd(row),
        "rawLowUsd": prices.get("low"),
        "rawSellers": prices.get("sellers"),
        "rawListings": prices.get("listings"),
        "rawRecentSales": prices.get("recentSales"),
        "primaryPrinting": prices.get("primaryPrinting"),
        "printingsAvailable": row.get("printingsAvailable"),
        "variants": row.get("variants"),
        "rawHistory": _raw_history_summary(row),
        "ebay": _ebay_summary(row),
        "cardmarket": _cardmarket_summary(row),
        "cardmarketEur": cardmarket_eur(row),
    }


class Runtime:
    def __init__(self) -> None:
        self.http_calls = 0
        self.credits = 0
        self.daily_remaining: int | None = None
        self.blocked = False
        self.errors: list[str] = []
        self._last_call: float | None = None

    def can_call(self) -> bool:
        if self.blocked:
            return False
        if self.http_calls >= HTTP_CALL_CAP:
            self.blocked = True
            self.errors.append("HTTP_CALL_CAP")
            return False
        if self.credits >= CREDIT_CAP:
            self.blocked = True
            self.errors.append("CREDIT_CAP")
            return False
        if self.daily_remaining is not None and self.daily_remaining <= STOP_DAILY_REMAINING:
            self.blocked = True
            self.errors.append("DAILY_REMAINING_SAFETY_FLOOR")
            return False
        return True

    def wait(self) -> None:
        if self._last_call is None:
            return
        delay = INTERVAL_SECONDS - (time.monotonic() - self._last_call)
        if delay > 0:
            time.sleep(delay)

    def record(self, headers: Mapping[str, object]) -> None:
        self.http_calls += 1
        self._last_call = time.monotonic()
        consumed = _header_int(headers, "X-Api-Calls-Consumed")
        if consumed is None:
            self.blocked = True
            self.errors.append("CREDIT_HEADER_REQUIRED")
            return
        self.credits += consumed
        remaining = _header_int(headers, "X-Ratelimit-Daily-Remaining")
        if remaining is None:
            self.blocked = True
            self.errors.append("DAILY_REMAINING_HEADER_REQUIRED")
            return
        self.daily_remaining = remaining
        if self.credits > CREDIT_CAP:
            self.blocked = True
            self.errors.append("CREDIT_CAP_EXCEEDED")


def _request(
    key: str,
    runtime: Runtime,
    params: Mapping[str, object],
) -> tuple[int | None, object | None, dict[str, str]]:
    if not runtime.can_call():
        return None, None, {}
    runtime.wait()
    try:
        response = requests.get(
            BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            params=dict(params),
            timeout=35,
        )
    except requests.RequestException as exc:
        runtime.blocked = True
        runtime.errors.append(f"REQUEST_ERROR:{type(exc).__name__}")
        return None, None, {}
    filtered = quota_headers(response.headers)
    runtime.record(response.headers)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, filtered


def _markdown(report: Mapping[str, object]) -> str:
    c = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
    runtime = report.get("runtime") if isinstance(report.get("runtime"), Mapping) else {}
    lines = [
        "# PokemonPriceTracker full benchmark",
        "",
        f"- Cards: `{report.get('panel_size')}`",
        f"- Exact identities: `{c.get('identity_exact')}`",
        f"- Deep payloads: `{c.get('deep_exact')}`",
        f"- RAW current: `{c.get('raw_current')}`",
        f"- RAW 180d history: `{c.get('raw_history')}`",
        f"- eBay salesByGrade: `{c.get('ebay_sales_by_grade')}`",
        f"- eBay grade history: `{c.get('ebay_grade_history')}`",
        f"- Cardmarket current/history: `{c.get('cardmarket_current')}/{c.get('cardmarket_history')}`",
        f"- PSA10 aggregate: `{c.get('psa10')}`",
        f"- HTTP calls / credits: `{runtime.get('http_calls')}` / `{runtime.get('credits')}`",
        f"- Daily remaining: `{runtime.get('daily_remaining')}`",
        "",
        "| Card | Match | RAW hist | eBay grades | PSA10 sales | PSA10 daily hist | CM hist |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for probe in report.get("cards", []):
        if not isinstance(probe, Mapping):
            continue
        deep = probe.get("deep_summary") if isinstance(probe.get("deep_summary"), Mapping) else {}
        raw_hist = deep.get("rawHistory") if isinstance(deep.get("rawHistory"), Mapping) else {}
        ebay = deep.get("ebay") if isinstance(deep.get("ebay"), Mapping) else {}
        psa10 = ebay.get("psa10") if isinstance(ebay.get("psa10"), Mapping) else {}
        grade_hist = ebay.get("dailyGradeHistory") if isinstance(ebay.get("dailyGradeHistory"), Mapping) else {}
        psa10_hist = grade_hist.get("psa10") if isinstance(grade_hist.get("psa10"), Mapping) else {}
        cm = deep.get("cardmarket") if isinstance(deep.get("cardmarket"), Mapping) else {}
        cm_variants = cm.get("variants") if isinstance(cm.get("variants"), Mapping) else {}
        cm_points = max(
            (int(v.get("points") or 0) for v in cm_variants.values() if isinstance(v, Mapping)),
            default=0,
        )
        lines.append(
            f"| {probe.get('card')} | {probe.get('match_status')} | "
            f"{raw_hist.get('totalDataPoints') or 0} | {ebay.get('gradeBuckets') or 0} | "
            f"{psa10.get('sales_count') or 0} | {psa10_hist.get('days') or 0} | {cm_points} |"
        )
    lines += [
        "",
        "Important: `salesByGrade` and `ebay.priceHistory` are provider aggregates of sold data, not item-level sale records. They are market evidence, not fabricated exact SOLD transactions.",
        "No CMAPI/eBay ASP/Neon write, purchase, bid, checkout, payment or paid grading action is performed.",
    ]
    return "\n".join(lines)


def main() -> int:
    key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("POKEMONPRICETRACKER_API_KEY missing")

    runtime = Runtime()
    cards: list[dict[str, object]] = []
    coverage = {
        "identity_exact": 0,
        "deep_exact": 0,
        "raw_current": 0,
        "raw_history": 0,
        "ebay_sales_by_grade": 0,
        "ebay_grade_history": 0,
        "cardmarket_current": 0,
        "cardmarket_history": 0,
        "psa10": 0,
    }
    graders_seen: set[str] = set()

    for card in PANEL:
        if not runtime.can_call():
            break
        probe: dict[str, object] = {
            "card": card.tcgdex_id,
            "canonical": asdict(card),
            "search_attempts": [],
            "match_status": "UNRESOLVED",
            "match_proof": "",
        }
        matched_row: Mapping[str, object] | None = None
        for params in search_attempts(card):
            status, payload, headers = _request(key, runtime, params)
            rows = payload_rows(payload)
            match = match_macro_identity(card, rows)
            attempt = {
                "http": status,
                "params": params,
                "quota_headers": headers,
                "rows": len(rows),
                "match_status": match.status,
                "match_proof": match.proof,
                "payload": payload,
            }
            probe["search_attempts"].append(attempt)
            if match.status == "EXACT" and match.row is not None:
                matched_row = match.row
                probe["match_status"] = "EXACT"
                probe["match_proof"] = match.proof
                break
            if match.status == "AMBIGUOUS":
                probe["match_status"] = "AMBIGUOUS"
                probe["match_proof"] = match.proof
                break
            if runtime.blocked:
                break

        if matched_row is None:
            cards.append(probe)
            continue
        coverage["identity_exact"] += 1
        tcg_id = matched_row.get("tcgPlayerId") or matched_row.get("tcgplayerId")
        probe["provider_tcgplayer_id"] = str(tcg_id) if tcg_id else None
        if not tcg_id or not runtime.can_call():
            cards.append(probe)
            continue

        deep_params = {
            "tcgPlayerId": str(tcg_id),
            "includeHistory": "true",
            "includeEbay": "true",
            "includeCardmarket": "true",
            "days": 180,
            "maxDataPoints": 180,
        }
        deep_status, deep_payload, deep_headers = _request(key, runtime, deep_params)
        deep_rows = payload_rows(deep_payload)
        deep_match = match_macro_identity(card, deep_rows)
        probe["deep_http"] = deep_status
        probe["deep_quota_headers"] = deep_headers
        probe["deep_payload"] = deep_payload
        probe["deep_match_status"] = deep_match.status
        probe["deep_match_proof"] = deep_match.proof
        if deep_match.status != "EXACT" or deep_match.row is None:
            cards.append(probe)
            continue

        coverage["deep_exact"] += 1
        summary = summarize_deep_row(deep_match.row)
        probe["deep_summary"] = summary
        if summary.get("rawUsd") is not None:
            coverage["raw_current"] += 1
        raw_hist = summary.get("rawHistory") if isinstance(summary.get("rawHistory"), Mapping) else {}
        if int(raw_hist.get("totalDataPoints") or 0) > 0:
            coverage["raw_history"] += 1
        ebay = summary.get("ebay") if isinstance(summary.get("ebay"), Mapping) else {}
        if int(ebay.get("gradeBuckets") or 0) > 0:
            coverage["ebay_sales_by_grade"] += 1
            graders_seen.update(str(v) for v in ebay.get("graders") or [])
        if ebay.get("dailyGradeHistory"):
            coverage["ebay_grade_history"] += 1
        if ebay.get("psa10"):
            coverage["psa10"] += 1
        cm = summary.get("cardmarket") if isinstance(summary.get("cardmarket"), Mapping) else {}
        if cm.get("marketEur") is not None or cm.get("trendEur") is not None:
            coverage["cardmarket_current"] += 1
        cm_variants = cm.get("variants") if isinstance(cm.get("variants"), Mapping) else {}
        if any(int(v.get("points") or 0) > 0 for v in cm_variants.values() if isinstance(v, Mapping)):
            coverage["cardmarket_history"] += 1
        cards.append(probe)

    report = {
        "schema_version": 1,
        "provider": "pokemonpricetracker",
        "mode": "FULL_PAID_PLAN_EVIDENCE_BENCHMARK",
        "panel_size": len(PANEL),
        "coverage": coverage,
        "graders_seen": sorted(graders_seen),
        "runtime": {
            "http_calls": runtime.http_calls,
            "credits": runtime.credits,
            "daily_remaining": runtime.daily_remaining,
            "http_call_cap": HTTP_CALL_CAP,
            "credit_cap": CREDIT_CAP,
            "stop_daily_remaining": STOP_DAILY_REMAINING,
            "blocked": runtime.blocked,
            "errors": runtime.errors,
        },
        "evidence_semantics": {
            "raw_price_history": "DAILY_PROVIDER_MARKET_AGGREGATE",
            "ebay_sales_by_grade": "PROVIDER_AGGREGATED_SOLD_BY_GRADE_NOT_ITEM_LEVEL",
            "ebay_grade_history": "DAILY_PROVIDER_AGGREGATE_NOT_INDIVIDUAL_SALE",
            "cardmarket": "PROVIDER_CARDMARKET_EUR_MARKET_HISTORY",
        },
        "safety": {
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "paid_grading": 0,
            "cmapi_calls": 0,
            "ebay_asp_calls": 0,
            "neon_writes": 0,
        },
        "cards": cards,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = _markdown(report)
    REPORT_MD.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
