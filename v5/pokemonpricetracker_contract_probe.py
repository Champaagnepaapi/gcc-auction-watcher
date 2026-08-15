from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Mapping, Sequence

import requests

from .pokemonpricetracker_adapter import CanonicalPptIdentity, match_macro_identity

BASE_URL = "https://www.pokemonpricetracker.com/api/v2/cards"
CALL_CAP = 6
INTERVAL_SECONDS = 2.20
REPORT_JSON = Path("pokemonpricetracker_contract_probe.json")
REPORT_MD = Path("pokemonpricetracker_contract_probe.md")

SENTINELS = (
    CanonicalPptIdentity("swsh7-215", "Umbreon VMAX", "Evolving Skies", "215", "en"),
    CanonicalPptIdentity("swsh8-271", "Gengar VMAX", "Fusion Strike", "271", "en"),
    CanonicalPptIdentity("swsh12-186", "Lugia V", "Silver Tempest", "186", "en"),
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


def _request(key: str, params: Mapping[str, object]) -> tuple[int | None, object | None, dict[str, str]]:
    try:
        response = requests.get(
            BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            params=dict(params),
            timeout=30,
        )
    except requests.RequestException:
        return None, None, {}
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, quota_headers(response.headers)


def _row_summary(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": row.get("name"),
        "setName": row.get("setName") or row.get("set_name"),
        "setId": row.get("setId") or row.get("set_id"),
        "cardNumber": row.get("cardNumber") or row.get("number"),
        "externalCatalogId": row.get("externalCatalogId"),
        "tcgPlayerId": row.get("tcgPlayerId") or row.get("tcgplayerId"),
        "language": row.get("language"),
        "printing": row.get("printing"),
        "keys": sorted(str(key) for key in row.keys()),
    }


def _has_data(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return bool(value)
    return value not in (None, "")


def _markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# PokemonPriceTracker contract probe",
        "",
        f"- Calls: `{report.get('calls')}/{CALL_CAP}`",
        f"- Search exact cards: `{report.get('search_exact')}/{len(SENTINELS)}`",
        f"- Deep payloads: `{report.get('deep_payloads')}`",
        f"- History payloads: `{report.get('history_payloads')}`",
        f"- eBay graded payloads: `{report.get('ebay_payloads')}`",
        f"- Cardmarket payloads: `{report.get('cardmarket_payloads')}`",
        "",
    ]
    for probe in report.get("probes", []):
        if not isinstance(probe, Mapping):
            continue
        lines.append(
            f"- {probe.get('card')}: search HTTP `{probe.get('search_http')}`, "
            f"rows `{probe.get('search_rows')}`, exact `{probe.get('exact_count')}`, "
            f"proof `{probe.get('match_proof')}`, deep HTTP `{probe.get('deep_http')}`"
        )
    lines += [
        "",
        "Raw provider payloads are preserved in the JSON artifact for schema diagnosis.",
        "No CMAPI/eBay ASP call, purchase, bid, checkout, payment or paid grading action is performed.",
    ]
    return "\n".join(lines)


def main() -> int:
    key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("POKEMONPRICETRACKER_API_KEY missing")

    calls = 0
    probes: list[dict[str, object]] = []
    search_exact = 0
    deep_payloads = history_payloads = ebay_payloads = cardmarket_payloads = 0

    for card in SENTINELS:
        if calls >= CALL_CAP:
            break
        if calls:
            time.sleep(INTERVAL_SECONDS)
        search_params = {"search": f"{card.name} {card.number}", "limit": 5}
        status, payload, headers = _request(key, search_params)
        calls += 1
        rows = payload_rows(payload)
        match = match_macro_identity(card, rows)
        probe: dict[str, object] = {
            "card": card.tcgdex_id,
            "canonical": {
                "tcgdex_id": card.tcgdex_id,
                "name": card.name,
                "set": card.set_name,
                "number": card.number,
                "language": card.language,
            },
            "search_http": status,
            "search_params": search_params,
            "search_headers": headers,
            "search_rows": len(rows),
            "exact_count": match.candidate_count if match.status == "EXACT" else 0,
            "match_status": match.status,
            "match_proof": match.proof,
            "candidate_summaries": [_row_summary(row) for row in rows[:5]],
            "search_payload": payload,
        }
        if match.status == "EXACT" and match.row is not None:
            search_exact += 1
            tcg_id = match.row.get("tcgPlayerId") or match.row.get("tcgplayerId")
            if tcg_id and calls < CALL_CAP:
                time.sleep(INTERVAL_SECONDS)
                deep_params = {
                    "tcgPlayerId": str(tcg_id),
                    "includeHistory": "true",
                    "includeEbay": "true",
                    "includeCardmarket": "true",
                    "days": 180,
                    "maxDataPoints": 180,
                }
                deep_status, deep_payload, deep_headers = _request(key, deep_params)
                calls += 1
                deep_rows = payload_rows(deep_payload)
                probe.update(
                    {
                        "deep_http": deep_status,
                        "deep_headers": deep_headers,
                        "deep_rows": len(deep_rows),
                        "deep_payload": deep_payload,
                    }
                )
                if deep_rows:
                    deep_payloads += 1
                    deep = deep_rows[0]
                    if _has_data(deep, "priceHistory"):
                        history_payloads += 1
                    if _has_data(deep, "ebay"):
                        ebay_payloads += 1
                    if _has_data(deep, "cardmarketPrices"):
                        cardmarket_payloads += 1
        probes.append(probe)

    report = {
        "provider": "pokemonpricetracker",
        "endpoint": BASE_URL,
        "calls": calls,
        "call_cap": CALL_CAP,
        "search_exact": search_exact,
        "deep_payloads": deep_payloads,
        "history_payloads": history_payloads,
        "ebay_payloads": ebay_payloads,
        "cardmarket_payloads": cardmarket_payloads,
        "probes": probes,
        "safety": {
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "paid_grading": 0,
            "cmapi_calls": 0,
            "ebay_asp_calls": 0,
        },
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = _markdown(report)
    REPORT_MD.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
