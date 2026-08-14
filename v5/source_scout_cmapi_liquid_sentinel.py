from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from . import source_scout_benchmark as scout
from . import source_scout_cmapi_v2_entrypoint as v2
from . import source_scout_cmapi_v3_entrypoint as cmapi
from .models import CardIdentity


# Deliberately fixed, highly liquid vintage sentinel. The identity is strict:
# English Charizard, Base Set, collector number 4/102. No fuzzy rescue.
SENTINEL_IDENTITY = CardIdentity(
    game="Pokemon",
    card_name="Charizard",
    set="Base Set",
    card_number="4/102",
    year=1999,
    language="en",
)
SEARCH_QUERY = "Charizard 4"
MAX_CMAPI_CALLS = 4
STOP_IF_REMAINING_AT_OR_BELOW = 20
CALL_INTERVAL_SECONDS = 2.2


def _strict_match(row: Mapping[str, object]) -> bool:
    return (
        scout.candidate_identity(
            SENTINEL_IDENTITY,
            name=row.get("name"),
            set_name=v2._set_name(row),
            number=v2._number(row),
        )
        == "EXACT"
    )


def _safe_lookup(row: Mapping[str, object]) -> dict[str, object]:
    provider_id = cmapi._provider_id(row)
    if provider_id is not None:
        return {"id": provider_id}
    provider_tcgid = cmapi._tcgid(row)
    if provider_tcgid:
        return {"tcgid": provider_tcgid}
    raise RuntimeError("CMAPI liquid sentinel matched row has no provider id/tcgid")


def main() -> int:
    key = os.getenv("CMAPI_RAPIDAPI_KEY", "").strip()
    if not key:
        print("CMAPI_LIQUID_SENTINEL_FAILED: CMAPI_RAPIDAPI_KEY missing")
        return 1

    # Reuse the provider's proven endpoint wrapper, but with a much tighter cap.
    cmapi.MAX_CMAPI_CALLS = MAX_CMAPI_CALLS
    cmapi.STOP_IF_REMAINING_AT_OR_BELOW = STOP_IF_REMAINING_AT_OR_BELOW
    cmapi.CALL_TRACE.clear()

    host = os.getenv("CMAPI_RAPIDAPI_HOST", cmapi.CMAPI_HOST).strip() or cmapi.CMAPI_HOST
    client = scout.SafeClient(
        "cmapi_liquid_charizard_sentinel",
        call_cap=MAX_CMAPI_CALLS,
        interval=CALL_INTERVAL_SECONDS,
        response_cap=2_000_000,
        total_cap=8_000_000,
    )

    search_response, search_payload = cmapi._request(
        client,
        key,
        host,
        cmapi.SEARCH_PATH,
        {"search": SEARCH_QUERY, "sort": "relevance"},
    )
    rows = v2._rows(search_payload)
    exact = [row for row in rows if _strict_match(row)]

    report: dict[str, object] = {
        "mode": "CMAPI_LIQUID_CHARIZARD_BASE_SET_SENTINEL",
        "canonical_identity": {
            "name": SENTINEL_IDENTITY.card_name,
            "set": SENTINEL_IDENTITY.set,
            "number": SENTINEL_IDENTITY.card_number,
            "language": SENTINEL_IDENTITY.language,
            "year": SENTINEL_IDENTITY.year,
        },
        "search": {
            "http": getattr(search_response, "status_code", None),
            "query": SEARCH_QUERY,
            "candidate_count": len(rows),
            "exact_matches": len(exact),
            "error": cmapi._safe_error(search_payload),
            "candidates": v2._candidate_summary(rows),
        },
        "matched_card": None,
        "ebay_graded": None,
        "psa10_sold_offers": None,
        "history_jan_2024": None,
        "provider_payloads": {},
    }

    if len(exact) == 1 and not client.runtime.blocked:
        row = exact[0]
        lookup = _safe_lookup(row)
        report["matched_card"] = {
            "id": row.get("id"),
            "name": row.get("name"),
            "set_name": v2._set_name(row),
            "card_number": v2._number(row),
            "tcgid": cmapi._tcgid(row),
            "cardmarket_id": row.get("cardmarket_id") or row.get("cardmarketId"),
            "tcgplayer_id": row.get("tcgplayer_id") or row.get("tcgplayerId"),
        }
        payloads = report["provider_payloads"]
        if isinstance(payloads, dict):
            payloads["search_matched_row"] = row

        graded_response, graded_payload = cmapi._request(
            client, key, host, cmapi.EBAY_GRADED_PATH, lookup
        )
        report["ebay_graded"] = {
            "http": getattr(graded_response, "status_code", None),
            "error": cmapi._safe_error(graded_payload),
            **cmapi._ebay_graded_summary(graded_payload),
        }
        if isinstance(payloads, dict) and getattr(graded_response, "status_code", None) == 200:
            payloads["ebay_sold_graded"] = graded_payload

        if not client.runtime.blocked:
            offers_response, offers_payload = cmapi._request(
                client,
                key,
                host,
                cmapi.EBAY_OFFERS_PATH,
                {**lookup, "company": "PSA", "grade": "10", "per_page": 20, "page": 1},
            )
            report["psa10_sold_offers"] = {
                "http": getattr(offers_response, "status_code", None),
                "error": cmapi._safe_error(offers_payload),
                **cmapi._offers_summary(offers_payload),
            }
            if isinstance(payloads, dict) and getattr(offers_response, "status_code", None) == 200:
                payloads["ebay_psa10_sold_offers"] = offers_payload

        if not client.runtime.blocked:
            history_response, history_payload = cmapi._request(
                client,
                key,
                host,
                cmapi.HISTORY_PATH,
                {
                    **lookup,
                    "date_from": "2024-01-01",
                    "date_to": "2024-01-31",
                    "sort": "desc",
                    "lang": "en",
                    "page": 1,
                },
            )
            report["history_jan_2024"] = {
                "http": getattr(history_response, "status_code", None),
                "error": cmapi._safe_error(history_payload),
                **cmapi._history_summary(history_payload),
            }
            if isinstance(payloads, dict) and getattr(history_response, "status_code", None) == 200:
                payloads["history_jan_2024"] = history_payload

    elif len(exact) > 1:
        report["search"]["identity_status"] = "AMBIGUOUS"  # type: ignore[index]
    else:
        report["search"]["identity_status"] = "UNRESOLVED"  # type: ignore[index]

    report["safety"] = {
        "purchase": 0,
        "bid": 0,
        "checkout": 0,
        "payment": 0,
        "max_cmapi_calls": MAX_CMAPI_CALLS,
        "actual_cmapi_calls": client.runtime.calls,
        "stop_if_remaining_at_or_below": STOP_IF_REMAINING_AT_OR_BELOW,
        "quota_remaining": client.runtime.quota_remaining,
        "blocked": client.runtime.blocked,
        "errors": client.runtime.errors,
        "call_trace": cmapi.CALL_TRACE,
    }

    Path("cmapi_liquid_sentinel.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    graded = report.get("ebay_graded") if isinstance(report.get("ebay_graded"), Mapping) else {}
    offers = report.get("psa10_sold_offers") if isinstance(report.get("psa10_sold_offers"), Mapping) else {}
    history = report.get("history_jan_2024") if isinstance(report.get("history_jan_2024"), Mapping) else {}
    search = report["search"] if isinstance(report.get("search"), Mapping) else {}
    lines = [
        "# CMAPI liquid Charizard sentinel",
        "",
        f"- Search HTTP: `{search.get('http')}`",
        f"- Exact identity matches: `{search.get('exact_matches')}`",
        f"- eBay graded HTTP: `{graded.get('http', 'NOT_RUN')}`",
        f"- Graded rows: `{graded.get('grade_rows', 0)}`",
        f"- Total graded sample size: `{graded.get('total_sample_size', 0)}`",
        f"- PSA10 aggregate rows: `{len(graded.get('psa10') or [])}`",
        f"- PSA10 sold-offers HTTP: `{offers.get('http', 'NOT_RUN')}`",
        f"- PSA10 individual sold offers: `{offers.get('offer_count', 0)}`",
        f"- Jan 2024 history HTTP: `{history.get('http', 'NOT_RUN')}`",
        f"- Jan 2024 history points: `{history.get('point_count', 0)}`",
        f"- CMAPI calls: `{client.runtime.calls}/{MAX_CMAPI_CALLS}`",
        f"- Remaining quota: `{client.runtime.quota_remaining}`",
        "",
        "No purchase, bid, checkout or payment action is present in this sentinel.",
    ]
    rendered = "\n".join(lines) + "\n"
    Path("cmapi_liquid_sentinel.md").write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
