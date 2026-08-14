from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base
from . import source_scout_cmapi_v2_entrypoint as v2


CMAPI_HOST = "cardmarket-api-tcg.p.rapidapi.com"
SEARCH_PATH = "/pokemon/cards/search"
HISTORY_PATH = "/pokemon/history-prices"
EBAY_GRADED_PATH = "/pokemon/ebay-sold-prices"
EBAY_OFFERS_PATH = "/pokemon/ebay-sold-offers"

# Basic plan has paid overage after 100 requests/day. Keep this diagnostic far
# below that boundary and stop early if RapidAPI reports a low remaining quota.
MAX_CMAPI_CALLS = 22
STOP_IF_REMAINING_AT_OR_BELOW = 10
RESPONSE_CAP_BYTES = 2_000_000
TOTAL_CAP_BYTES = 12_000_000
CALL_INTERVAL_SECONDS = 2.2  # < 30 requests/minute even for fast responses.
SAMPLES_PER_LANGUAGE = 2
SAMPLE_POSITIONS = (0, 4)

CALL_TRACE: list[dict[str, object]] = []


def _rate_remaining(response: object) -> int | None:
    headers = getattr(response, "headers", {})
    for key in (
        "x-ratelimit-requests-remaining",
        "X-RateLimit-Requests-Remaining",
    ):
        value = headers.get(key)
        if value is None:
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    return None


def _safe_error(payload: object) -> str | None:
    return v2._error_message(payload)


def _request(
    client: scout.SafeClient,
    key: str,
    host: str,
    path: str,
    params: Mapping[str, object],
) -> tuple[object | None, object | None]:
    if client.runtime.blocked:
        return None, None
    if (
        client.runtime.quota_remaining is not None
        and client.runtime.quota_remaining <= STOP_IF_REMAINING_AT_OR_BELOW
    ):
        client.runtime.blocked = True
        client.runtime.errors.append("CMAPI_QUOTA_SAFETY_STOP")
        return None, None

    response, payload = client.request(
        "GET",
        f"https://{host}{path}",
        headers={
            "X-RapidAPI-Key": key,
            "X-RapidAPI-Host": host,
            "Content-Type": "application/json",
        },
        params=dict(params),
    )
    remaining = _rate_remaining(response)
    if remaining is not None:
        client.runtime.quota_remaining = remaining

    status = getattr(response, "status_code", None)
    error = _safe_error(payload)
    CALL_TRACE.append(
        {
            "path": path,
            "http": status,
            "remaining": remaining,
            "error": error,
            "params": {
                key: value
                for key, value in params.items()
                if key not in {"api_key", "key", "token"}
            },
        }
    )

    if status == 429:
        client.runtime.blocked = True
        client.runtime.errors.append("CMAPI_RATE_LIMIT")
    if status == 403 and error and "not subscribed" in error.casefold():
        client.runtime.blocked = True
        client.runtime.errors.append("CMAPI_SUBSCRIPTION_BLOCK")
    if (
        client.runtime.quota_remaining is not None
        and client.runtime.quota_remaining <= STOP_IF_REMAINING_AT_OR_BELOW
    ):
        client.runtime.blocked = True
        client.runtime.errors.append("CMAPI_QUOTA_SAFETY_STOP")
    return response, payload


def _select_samples(panel: Sequence[scout.PanelCard]) -> list[scout.PanelCard]:
    selected: list[scout.PanelCard] = []
    for language in base.LANGUAGES:
        rows = [
            card for card in panel if scout.lang(card.identity.language) == language
        ]
        seen: set[str] = set()
        for position in SAMPLE_POSITIONS:
            if len(selected) >= len(base.LANGUAGES) * SAMPLES_PER_LANGUAGE:
                break
            if not rows:
                break
            index = min(max(position, 0), len(rows) - 1)
            card = rows[index]
            if card.tcgdex_id in seen:
                continue
            seen.add(card.tcgdex_id)
            selected.append(card)
    return selected


def _provider_id(row: Mapping[str, object]) -> int | None:
    try:
        value = row.get("id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _tcgid(row: Mapping[str, object]) -> str | None:
    for key in ("tcgid", "tcg_id", "pokemon_tcg_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _identity_matches(
    card: scout.PanelCard,
    match_identity: object,
    row: Mapping[str, object],
    language: str,
) -> bool:
    provider_tcgid = _tcgid(row)
    if provider_tcgid and provider_tcgid.casefold() == card.tcgdex_id.casefold():
        return True
    return (
        scout.candidate_identity(
            match_identity,
            name=row.get("name"),
            set_name=v2._set_name(row),
            number=v2._number(row),
        )
        == "EXACT"
    )


def _numeric_mapping(value: object) -> object:
    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        for key, child in value.items():
            if isinstance(child, Mapping):
                nested = _numeric_mapping(child)
                if nested:
                    output[str(key)] = nested
            elif isinstance(child, (int, float)) and not isinstance(child, bool):
                output[str(key)] = child
            elif key in {"currency", "language", "condition"} and isinstance(child, str):
                output[str(key)] = child
        return output
    return None


def _current_price_summary(row: Mapping[str, object]) -> object:
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    return _numeric_mapping(prices)


def _history_points(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    points: list[dict[str, object]] = []
    if isinstance(data, Mapping):
        for day, values in data.items():
            if not isinstance(values, Mapping):
                continue
            row = {"date": str(day)}
            for key, value in values.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row[str(key)] = value
            points.append(row)
    elif isinstance(data, list):
        for values in data:
            if not isinstance(values, Mapping):
                continue
            row = {
                str(key): value
                for key, value in values.items()
                if isinstance(value, (str, int, float)) and not isinstance(value, bool)
            }
            points.append(row)
    return points


def _history_summary(payload: object) -> dict[str, object]:
    points = _history_points(payload)
    dated = sorted(
        points,
        key=lambda row: str(row.get("date") or ""),
        reverse=True,
    )
    return {
        "point_count": len(points),
        "newest_date": dated[0].get("date") if dated else None,
        "oldest_date": dated[-1].get("date") if dated else None,
        "latest_points": dated[:5],
    }


def _ebay_rows(payload: object) -> list[Mapping[str, object]]:
    return v2._rows(payload)


def _ebay_graded_summary(payload: object) -> dict[str, object]:
    rows = _ebay_rows(payload)
    psa10 = []
    total_sample = 0
    compact: list[dict[str, object]] = []
    for row in rows:
        company = str(row.get("company") or "").upper()
        grade = str(row.get("grade") or "")
        median = scout.num(row.get("median_price"), row.get("medianPrice"))
        try:
            sample = int(row.get("sample_size") or row.get("sampleSize") or 0)
        except (TypeError, ValueError):
            sample = 0
        total_sample += sample
        item = {
            "company": company or None,
            "grade": grade or None,
            "median_price": median,
            "sample_size": sample,
        }
        compact.append(item)
        if company == "PSA" and grade in {"10", "10.0"}:
            psa10.append(item)
    return {
        "grade_rows": len(rows),
        "total_sample_size": total_sample,
        "psa10": psa10,
        "grades": compact,
    }


def _offers_summary(payload: object) -> dict[str, object]:
    rows = _ebay_rows(payload)
    compact: list[dict[str, object]] = []
    for row in rows[:20]:
        compact.append(
            {
                "ebay_item_id": row.get("ebay_item_id") or row.get("ebayItemId"),
                "title": row.get("title"),
                "price": scout.num(row.get("price")),
                "currency": row.get("currency"),
                "company": row.get("company"),
                "grade": row.get("grade"),
                "ended_at": row.get("ended_at") or row.get("endedAt"),
            }
        )
    return {"offer_count": len(rows), "offers": compact}


def _lookup_params(row: Mapping[str, object], card: scout.PanelCard) -> dict[str, object]:
    provider_id = _provider_id(row)
    if provider_id is not None:
        return {"id": provider_id}
    provider_tcgid = _tcgid(row)
    if provider_tcgid:
        return {"tcgid": provider_tcgid}
    return {"tcgid": card.tcgdex_id}


def _search_one(
    client: scout.SafeClient,
    key: str,
    host: str,
    card: scout.PanelCard,
    anchor_client: scout.SafeClient,
    anchor_cache: dict[str, object],
) -> dict[str, object]:
    language = scout.lang(card.identity.language)
    match_identity = card.identity
    identity_status_if_matched = "EXACT"
    if language == "fr":
        anchor = base._english_anchor(card, anchor_client, anchor_cache)
        if anchor is not None:
            match_identity = anchor
            identity_status_if_matched = "ANCHOR_ONLY"

    search_name = getattr(match_identity, "card_name", None) or card.identity.card_name or ""
    search_number = getattr(match_identity, "card_number", None) or card.identity.card_number or ""
    queries = [" ".join(filter(None, (search_name, search_number)))]
    if language == "ja":
        set_code = card.tcgdex_id.rsplit("-", 1)[0]
        fallback = " ".join(filter(None, (set_code, card.identity.card_number)))
        if fallback and fallback not in queries:
            queries.append(fallback)

    attempts: list[dict[str, object]] = []
    matched: list[Mapping[str, object]] = []
    matched_payload: object | None = None
    for query in queries:
        if client.runtime.blocked:
            break
        response, payload = _request(
            client,
            key,
            host,
            SEARCH_PATH,
            {"search": query, "sort": "relevance"},
        )
        rows = v2._rows(payload)
        exact = [
            row
            for row in rows
            if _identity_matches(card, match_identity, row, language)
        ]
        attempts.append(
            {
                "query": query,
                "http": getattr(response, "status_code", None),
                "candidate_count": len(rows),
                "exact_matches": len(exact),
                "error": _safe_error(payload),
                "candidates": v2._candidate_summary(rows),
            }
        )
        if len(exact) == 1:
            matched = exact
            matched_payload = payload
            break
        if len(exact) > 1:
            matched = exact
            matched_payload = payload
            break

    result: dict[str, object] = {
        "language": language,
        "card_label": card.label,
        "tcgdex_id": card.tcgdex_id,
        "search_attempts": attempts,
        "identity_status": "UNRESOLVED",
        "matched_card": None,
        "current_prices": None,
        "history": None,
        "ebay_graded": None,
        "provider_payloads": {},
    }
    if len(matched) > 1:
        result["identity_status"] = "AMBIGUOUS"
        return result
    if not matched:
        return result

    row = matched[0]
    result["identity_status"] = identity_status_if_matched
    result["matched_card"] = {
        "id": row.get("id"),
        "name": row.get("name"),
        "set_name": v2._set_name(row),
        "card_number": v2._number(row),
        "tcgid": _tcgid(row),
        "cardmarket_id": row.get("cardmarket_id") or row.get("cardmarketId"),
        "tcgplayer_id": row.get("tcgplayer_id") or row.get("tcgplayerId"),
    }
    result["current_prices"] = _current_price_summary(row)
    payloads = result["provider_payloads"]
    if isinstance(payloads, dict):
        payloads["search_matched_row"] = row
        payloads["search_response_metadata"] = {
            "results": matched_payload.get("results") if isinstance(matched_payload, Mapping) else None,
            "paging": matched_payload.get("paging") if isinstance(matched_payload, Mapping) else None,
        }

    lookup = _lookup_params(row, card)
    history_params = dict(lookup)
    today = date.today()
    history_params.update(
        {
            "date_from": str(today - timedelta(days=90)),
            "date_to": str(today),
            "sort": "desc",
            "page": 1,
        }
    )
    if language in {"en", "fr"}:
        history_params["lang"] = language

    response, history_payload = _request(
        client, key, host, HISTORY_PATH, history_params
    )
    result["history"] = {
        "http": getattr(response, "status_code", None),
        "language_filter": history_params.get("lang") or "NOT_SUPPORTED_FOR_JA",
        "error": _safe_error(history_payload),
        **_history_summary(history_payload),
    }
    if isinstance(payloads, dict) and getattr(response, "status_code", None) == 200:
        payloads["history_90d"] = history_payload

    response, ebay_payload = _request(
        client, key, host, EBAY_GRADED_PATH, lookup
    )
    result["ebay_graded"] = {
        "http": getattr(response, "status_code", None),
        "error": _safe_error(ebay_payload),
        **_ebay_graded_summary(ebay_payload),
    }
    if isinstance(payloads, dict) and getattr(response, "status_code", None) == 200:
        payloads["ebay_sold_graded"] = ebay_payload
    return result


def main() -> int:
    key = os.getenv("CMAPI_RAPIDAPI_KEY", "").strip()
    if not key:
        print("CMAPI_BENCHMARK_FAILED: CMAPI_RAPIDAPI_KEY missing")
        return 1

    host = os.getenv("CMAPI_RAPIDAPI_HOST", CMAPI_HOST).strip() or CMAPI_HOST
    panel, diagnostics = base.build_language_panel("", "", base.PANEL_SIZE)
    samples = _select_samples(panel)
    if len(samples) != len(base.LANGUAGES) * SAMPLES_PER_LANGUAGE:
        print(f"CMAPI_BENCHMARK_FAILED: expected 6 samples, got {len(samples)}")
        return 1

    client = scout.SafeClient(
        "cmapi_bounded_benchmark",
        call_cap=MAX_CMAPI_CALLS,
        interval=CALL_INTERVAL_SECONDS,
        response_cap=RESPONSE_CAP_BYTES,
        total_cap=TOTAL_CAP_BYTES,
    )
    anchor_client = scout.SafeClient(
        "tcgdex_cmapi_anchor", call_cap=10, interval=0.03
    )
    anchor_cache: dict[str, object] = {}

    results: list[dict[str, object]] = []
    for card in samples:
        if client.runtime.blocked:
            break
        results.append(
            _search_one(client, key, host, card, anchor_client, anchor_cache)
        )

    # Highest-value source test for the Robot KB: one page of individual PSA 10
    # eBay sold offers on the first exact English sample, if available.
    sold_offer_sentinel: dict[str, object] | None = None
    for result in results:
        if result.get("language") != "en" or result.get("identity_status") != "EXACT":
            continue
        matched = result.get("matched_card")
        if not isinstance(matched, Mapping):
            continue
        lookup: dict[str, object]
        try:
            lookup = {"id": int(matched.get("id"))}
        except (TypeError, ValueError):
            lookup = {"tcgid": str(matched.get("tcgid") or result.get("tcgdex_id") or "")}
        params = {**lookup, "company": "PSA", "grade": "10", "per_page": 20, "page": 1}
        response, payload = _request(
            client, key, host, EBAY_OFFERS_PATH, params
        )
        sold_offer_sentinel = {
            "card_label": result.get("card_label"),
            "tcgdex_id": result.get("tcgdex_id"),
            "http": getattr(response, "status_code", None),
            "error": _safe_error(payload),
            **_offers_summary(payload),
            "provider_payload": payload if getattr(response, "status_code", None) == 200 else None,
        }
        break

    # Historical-depth sentinel on the older English sample, targeting Jan 2024.
    history_depth_sentinel: dict[str, object] | None = None
    english_exact = [
        result
        for result in results
        if result.get("language") == "en" and result.get("identity_status") == "EXACT"
    ]
    if english_exact and not client.runtime.blocked:
        result = english_exact[-1]
        matched = result.get("matched_card")
        if isinstance(matched, Mapping):
            try:
                lookup = {"id": int(matched.get("id"))}
            except (TypeError, ValueError):
                lookup = {"tcgid": str(matched.get("tcgid") or result.get("tcgdex_id") or "")}
            response, payload = _request(
                client,
                key,
                host,
                HISTORY_PATH,
                {
                    **lookup,
                    "date_from": "2024-01-01",
                    "date_to": "2024-01-31",
                    "sort": "desc",
                    "lang": "en",
                    "page": 1,
                },
            )
            history_depth_sentinel = {
                "card_label": result.get("card_label"),
                "tcgdex_id": result.get("tcgdex_id"),
                "http": getattr(response, "status_code", None),
                "error": _safe_error(payload),
                **_history_summary(payload),
                "provider_payload": payload if getattr(response, "status_code", None) == 200 else None,
            }

    by_language: dict[str, dict[str, int]] = {}
    for language in base.LANGUAGES:
        subset = [result for result in results if result.get("language") == language]
        by_language[language] = {
            "samples": len(subset),
            "exact": sum(result.get("identity_status") == "EXACT" for result in subset),
            "anchors": sum(result.get("identity_status") == "ANCHOR_ONLY" for result in subset),
            "history_200": sum(
                isinstance(result.get("history"), Mapping)
                and result["history"].get("http") == 200
                for result in subset
            ),
            "history_points": sum(
                int(result["history"].get("point_count") or 0)
                for result in subset
                if isinstance(result.get("history"), Mapping)
            ),
            "ebay_graded_200": sum(
                isinstance(result.get("ebay_graded"), Mapping)
                and result["ebay_graded"].get("http") == 200
                for result in subset
            ),
            "ebay_grade_rows": sum(
                int(result["ebay_graded"].get("grade_rows") or 0)
                for result in subset
                if isinstance(result.get("ebay_graded"), Mapping)
            ),
        }

    report = {
        "mode": "CMAPI_BOUNDED_EN_FR_JA_HISTORY_EBAY_SOLD_BENCHMARK",
        "provider_host": host,
        "endpoints": {
            "search": SEARCH_PATH,
            "history": HISTORY_PATH,
            "ebay_graded": EBAY_GRADED_PATH,
            "ebay_sold_offers": EBAY_OFFERS_PATH,
        },
        "safety": {
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "max_cmapi_calls": MAX_CMAPI_CALLS,
            "actual_cmapi_calls": client.runtime.calls,
            "stop_if_remaining_at_or_below": STOP_IF_REMAINING_AT_OR_BELOW,
            "response_cap_bytes": RESPONSE_CAP_BYTES,
            "total_cap_bytes": TOTAL_CAP_BYTES,
            "rate_interval_seconds": CALL_INTERVAL_SECONDS,
        },
        "quota_remaining": client.runtime.quota_remaining,
        "bytes_read": client.runtime.bytes_read,
        "blocked": client.runtime.blocked,
        "errors": client.runtime.errors,
        "tcgdex_seed_calls": diagnostics.get("tcgdex_seed_calls"),
        "samples": results,
        "by_language": by_language,
        "sold_offer_sentinel": sold_offer_sentinel,
        "history_depth_sentinel": history_depth_sentinel,
        "call_trace": CALL_TRACE,
    }

    Path("cmapi_benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# CMAPI bounded EN/FR/JP benchmark",
        "",
        f"- CMAPI calls: `{client.runtime.calls}/{MAX_CMAPI_CALLS}`",
        f"- Remaining quota: `{client.runtime.quota_remaining}`",
        f"- Safety stop: remaining <= `{STOP_IF_REMAINING_AT_OR_BELOW}`",
        f"- Bytes read: `{client.runtime.bytes_read}` / `{TOTAL_CAP_BYTES}`",
        f"- Blocked: `{client.runtime.blocked}`",
        "",
        "| Lang | Samples | Exact | Anchors | History 200 | History pts | eBay graded 200 | Grade rows |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for language in base.LANGUAGES:
        row = by_language[language]
        lines.append(
            f"| {language.upper()} | {row['samples']} | {row['exact']} | {row['anchors']} | "
            f"{row['history_200']} | {row['history_points']} | {row['ebay_graded_200']} | {row['ebay_grade_rows']} |"
        )
    lines += [
        "",
        "## SOLD sentinel",
        "",
        f"- HTTP: `{sold_offer_sentinel.get('http') if sold_offer_sentinel else 'NOT_RUN'}`",
        f"- PSA10 sold offers returned: `{sold_offer_sentinel.get('offer_count') if sold_offer_sentinel else 0}`",
        "",
        "## Historical depth sentinel",
        "",
        f"- HTTP: `{history_depth_sentinel.get('http') if history_depth_sentinel else 'NOT_RUN'}`",
        f"- Jan 2024 points: `{history_depth_sentinel.get('point_count') if history_depth_sentinel else 0}`",
        "",
        "No purchase, bid, checkout or payment action is present in this benchmark.",
    ]
    rendered = "\n".join(lines) + "\n"
    Path("cmapi_benchmark.md").write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
