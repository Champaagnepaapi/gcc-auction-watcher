from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import requests

HOST = "pokemon-tcg-api.p.rapidapi.com"
BASE = f"https://{HOST}"
CALL_CAP = 12
STOP_REMAINING = 80
PANEL = (
    "swsh7-215",   # Umbreon VMAX
    "swsh8-271",   # Gengar VMAX
    "swsh12-186",  # Lugia V
    "swsh8-270",   # Espeon VMAX
    "swsh7-192",   # Dragonite V
)
HISTORY_SENTINELS = PANEL[:2]
REPORT_JSON = Path("pokemon_tcg_rapidapi_probe.json")
REPORT_MD = Path("pokemon_tcg_rapidapi_probe.md")
CMAPI_PATH = Path("prior-cmapi/cmapi_opportunity_evidence.json")


def quota_remaining(headers: Mapping[str, object]) -> int | None:
    lowered = {str(k).casefold(): str(v) for k, v in headers.items()}
    preferred = (
        "x-ratelimit-requests-remaining",
        "x-ratelimit-rapid-free-plans-requests-remaining",
        "x-ratelimit-remaining",
    )
    for key in preferred:
        raw = lowered.get(key)
        if raw is None:
            continue
        try:
            return int(float(raw))
        except ValueError:
            pass
    for key, raw in lowered.items():
        if "requests-remaining" not in key:
            continue
        try:
            return int(float(raw))
        except ValueError:
            pass
    return None


def _rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        return [data]
    return []


def _domain(value: object) -> str | None:
    try:
        host = urlparse(str(value or "")).hostname
    except ValueError:
        return None
    return host.casefold() if host else None


def _load_cmapi() -> dict[str, Mapping[str, object]]:
    if not CMAPI_PATH.exists():
        return {}
    try:
        doc = json.loads(CMAPI_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, Mapping[str, object]] = {}
    cards = doc.get("cards") if isinstance(doc, Mapping) else None
    if not isinstance(cards, list):
        return out
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        sold = card.get("ebay_psa10_sold_offers")
        payload = sold.get("payload") if isinstance(sold, Mapping) else None
        offers = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(offers, list):
            continue
        for offer in offers:
            if not isinstance(offer, Mapping):
                continue
            item_id = str(offer.get("ebay_item_id") or "").strip()
            if item_id:
                out[item_id] = offer
    return out


def compare_offers(new_offers: list[Mapping[str, object]], old_by_id: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    overlap = []
    domains: dict[str, int] = {}
    currencies: dict[str, int] = {}
    for offer in new_offers:
        item_id = str(offer.get("ebay_item_id") or "").strip()
        currency = str(offer.get("currency") or "UNKNOWN").upper()
        domain = _domain(offer.get("url")) or "UNKNOWN"
        currencies[currency] = currencies.get(currency, 0) + 1
        domains[domain] = domains.get(domain, 0) + 1
        previous = old_by_id.get(item_id)
        if previous is not None:
            overlap.append(
                {
                    "ebay_item_id": item_id,
                    "new_currency": currency,
                    "cmapi_currency": str(previous.get("currency") or "UNKNOWN").upper(),
                    "new_price": offer.get("price"),
                    "cmapi_price": previous.get("price"),
                    "new_domain": domain,
                    "cmapi_domain": _domain(previous.get("url")) or "UNKNOWN",
                }
            )
    return {
        "offers": len(new_offers),
        "currencies": currencies,
        "domains": domains,
        "cmapi_overlap": len(overlap),
        "overlap_examples": overlap[:20],
    }


class ProbeClient:
    def __init__(self, key: str) -> None:
        self.key = key
        self.calls = 0
        self.remaining: int | None = None
        self.blocked = False
        self.session = requests.Session()

    def get(self, path: str, params: Mapping[str, object]) -> tuple[int | None, object | None]:
        if self.blocked or self.calls >= CALL_CAP:
            self.blocked = True
            return None, None
        self.calls += 1
        try:
            response = self.session.get(
                BASE + path,
                headers={"x-rapidapi-key": self.key, "x-rapidapi-host": HOST, "accept": "application/json"},
                params=dict(params),
                timeout=20,
            )
        except requests.RequestException:
            self.blocked = True
            return None, None
        self.remaining = quota_remaining(response.headers)
        if self.calls == 1 and self.remaining is None:
            self.blocked = True
        if self.remaining is not None and self.remaining <= STOP_REMAINING:
            self.blocked = True
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return response.status_code, payload


def _markdown(report: Mapping[str, object]) -> str:
    comparison = report.get("comparison") if isinstance(report.get("comparison"), Mapping) else {}
    lines = [
        "# Pokémon TCG RapidAPI probe",
        "",
        f"- Calls: `{report.get('calls')}/{CALL_CAP}`",
        f"- Quota remaining: `{report.get('quota_remaining')}`",
        f"- Cards exact by tcgid: `{report.get('cards_exact')}/{len(PANEL)}`",
        f"- SOLD PSA10 returned: `{report.get('sold_offers')}`",
        f"- CMAPI item-id overlap: `{comparison.get('cmapi_overlap', 0)}`",
        f"- Currencies: `{comparison.get('currencies', {})}`",
        f"- Domains: `{comparison.get('domains', {})}`",
        f"- History sentinels with data: `{report.get('history_with_data')}/{len(HISTORY_SENTINELS)}`",
        "",
        "No CMAPI request, purchase, bid, checkout, payment or grading action is performed.",
    ]
    return "\n".join(lines)


def main() -> int:
    key = os.getenv("POKEMON_TCG_RAPIDAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("POKEMON_TCG_RAPIDAPI_KEY missing")
    confirmed = int(os.getenv("POKEMON_TCG_REMAINING_CONFIRMED", "0") or 0)
    if confirmed < 90:
        raise RuntimeError("Refusing to call provider: confirmed remaining quota must be >= 90")

    client = ProbeClient(key)
    cards_exact = 0
    sold_offers: list[Mapping[str, object]] = []
    evidence: list[dict[str, object]] = []

    for tcgid in PANEL:
        if client.blocked:
            break
        card_http, card_payload = client.get("/cards", {"tcgid": tcgid, "per_page": 5, "page": 1})
        rows = _rows(card_payload)
        exact = [row for row in rows if str(row.get("tcgid") or "").casefold() == tcgid.casefold()]
        if len(exact) == 1:
            cards_exact += 1
        if client.blocked:
            evidence.append({"tcgid": tcgid, "card_http": card_http, "card_payload": card_payload})
            break
        sold_http, sold_payload = client.get(
            "/ebay-sold-offers",
            {"tcgid": tcgid, "company": "PSA", "grade": "10", "per_page": 20, "page": 1},
        )
        offers = _rows(sold_payload)
        sold_offers.extend(offers)
        evidence.append(
            {
                "tcgid": tcgid,
                "card_http": card_http,
                "card_payload": card_payload,
                "sold_http": sold_http,
                "sold_payload": sold_payload,
                "sold_count": len(offers),
            }
        )

    history_with_data = 0
    for tcgid in HISTORY_SENTINELS:
        if client.blocked:
            break
        http, payload = client.get(
            "/history-prices",
            {"tcgid": tcgid, "date_from": "2026-06-01", "date_to": "2026-08-15", "lang": "fr", "page": 1},
        )
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if http == 200 and bool(data):
            history_with_data += 1
        evidence.append({"tcgid": tcgid, "history_http": http, "history_payload": payload})

    comparison = compare_offers(sold_offers, _load_cmapi())
    report = {
        "provider": "pokemon_tcg_rapidapi",
        "host": HOST,
        "panel": list(PANEL),
        "calls": client.calls,
        "quota_remaining": client.remaining,
        "blocked": client.blocked,
        "cards_exact": cards_exact,
        "sold_offers": len(sold_offers),
        "history_with_data": history_with_data,
        "comparison": comparison,
        "evidence": evidence,
        "safety": {
            "call_cap": CALL_CAP,
            "stop_remaining": STOP_REMAINING,
            "cmapi_calls": 0,
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "paid_grading": 0,
        },
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = _markdown(report)
    REPORT_MD.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
