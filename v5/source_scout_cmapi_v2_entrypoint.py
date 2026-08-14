from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base


CMAPI_HOST = "cardmarket-api-tcg.p.rapidapi.com"
CMAPI_PATH = "/pokemon/cards/search"


def _rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("data", "cards", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, Mapping):
            return [value]
    if payload.get("name"):
        return [payload]
    return []


def _set_name(row: Mapping[str, object]) -> object:
    for key in ("episode", "set"):
        value = row.get(key)
        if isinstance(value, Mapping):
            return value.get("name") or value.get("set_name")
    return row.get("set_name") or row.get("setName")


def _number(row: Mapping[str, object]) -> object:
    return row.get("card_number") or row.get("cardNumber") or row.get("number")


def _candidate_summary(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows[:10]:
        output.append(
            {
                "name": row.get("name"),
                "set_name": _set_name(row),
                "card_number": _number(row),
                "keys": sorted(str(key) for key in row.keys()),
            }
        )
    return output


def _safe_rate_headers(response: object) -> dict[str, str]:
    headers = getattr(response, "headers", {})
    output: dict[str, str] = {}
    for key in (
        "x-ratelimit-requests-limit",
        "x-ratelimit-requests-remaining",
        "x-ratelimit-requests-reset",
        "retry-after",
    ):
        value = headers.get(key)
        if value is not None:
            output[key] = str(value)
    return output


def _error_message(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("message", "error", "detail", "description"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return None


def main() -> int:
    key = os.getenv("CMAPI_RAPIDAPI_KEY", "").strip()
    if not key:
        print("CMAPI_PROBE_FAILED: CMAPI_RAPIDAPI_KEY missing")
        return 1

    panel, diagnostics = base.build_language_panel("", "", base.PANEL_SIZE)
    card = next(
        (card for card in panel if scout.lang(card.identity.language) == "en"),
        None,
    )
    if card is None:
        print("CMAPI_PROBE_FAILED: no English canonical sample")
        return 1

    host = os.getenv("CMAPI_RAPIDAPI_HOST", CMAPI_HOST).strip() or CMAPI_HOST
    client = scout.SafeClient(
        "cmapi_endpoint_probe",
        call_cap=1,
        interval=0.0,
        response_cap=1_000_000,
        total_cap=1_000_000,
    )
    query = " ".join(
        filter(None, (card.identity.card_name, card.identity.card_number))
    )
    response, payload = client.request(
        "GET",
        f"https://{host}{CMAPI_PATH}",
        headers={
            "X-RapidAPI-Key": key,
            "X-RapidAPI-Host": host,
            "Content-Type": "application/json",
        },
        params={"search": query, "sort": "relevance"},
    )

    rows = _rows(payload)
    exact = [
        row
        for row in rows
        if scout.candidate_identity(
            card.identity,
            name=row.get("name"),
            set_name=_set_name(row),
            number=_number(row),
        )
        == "EXACT"
    ]

    report = {
        "mode": "CMAPI_SINGLE_CALL_ENDPOINT_PROBE",
        "endpoint": f"https://{host}{CMAPI_PATH}",
        "request": {"search": query, "sort": "relevance"},
        "canonical_sample": {
            "name": card.identity.card_name,
            "set": card.identity.set,
            "card_number": card.identity.card_number,
            "language": card.identity.language,
            "tcgdex_id": card.tcgdex_id,
        },
        "http_status": getattr(response, "status_code", None),
        "calls": client.runtime.calls,
        "bytes_read": client.runtime.bytes_read,
        "rate_headers": _safe_rate_headers(response),
        "error_message": _error_message(payload),
        "candidate_count": len(rows),
        "exact_identity_matches": len(exact),
        "candidates": _candidate_summary(rows),
        "tcgdex_seed_calls": diagnostics.get("tcgdex_seed_calls"),
    }

    Path("cmapi_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    rendered = "\n".join(
        [
            "# CMAPI single-call endpoint probe",
            "",
            f"- Endpoint: `{CMAPI_PATH}`",
            f"- HTTP: `{report['http_status']}`",
            f"- CMAPI calls: `{report['calls']}` (hard cap = 1)",
            f"- Candidate rows: `{report['candidate_count']}`",
            f"- Exact identity matches: `{report['exact_identity_matches']}`",
            f"- Remaining quota header: `{report['rate_headers'].get('x-ratelimit-requests-remaining', 'NOT_EXPOSED')}`",
            f"- Error: `{report['error_message'] or 'NONE'}`",
            "",
            "No purchase, bid, checkout or payment action is present in this probe.",
        ]
    ) + "\n"
    Path("cmapi_probe.md").write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
