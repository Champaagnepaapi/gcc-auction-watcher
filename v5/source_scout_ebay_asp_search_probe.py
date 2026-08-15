from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Mapping

import requests

from .source_scout_ebay_asp_rapidapi_probe import _domain, strict_card_match

HOST = "ebay-average-selling-price.p.rapidapi.com"
URL = f"https://{HOST}/search"
CALL_CAP = 8
MIN_REMAINING = 35
RATE_INTERVAL_SECONDS = 1.05
CATEGORY_ID = "183454"  # Collectible Card Games > Single Cards
SITES = {"US": "0", "UK": "3"}
CARDS = (
    {
        "tcgdex_id": "swsh7-215",
        "name": "Umbreon VMAX",
        "set": "Evolving Skies",
        "numerator": "215",
        "denominator": "203",
    },
    {
        "tcgdex_id": "swsh8-271",
        "name": "Gengar VMAX",
        "set": "Fusion Strike",
        "numerator": "271",
        "denominator": "264",
    },
    {
        "tcgdex_id": "swsh12-186",
        "name": "Lugia V",
        "set": "Silver Tempest",
        "numerator": "186",
        "denominator": "195",
    },
    {
        "tcgdex_id": "swsh7-192",
        "name": "Dragonite V",
        "set": "Evolving Skies",
        "numerator": "192",
        "denominator": "203",
    },
)

REPORT_JSON = Path("ebay_asp_search_probe.json")
REPORT_MD = Path("ebay_asp_search_probe.md")
OLD_ASP_PATH = Path("prior-asp/ebay_asp_rapidapi_probe.json")
CMAPI_PATH = Path("prior-cmapi/cmapi_opportunity_evidence.json")


def _quota_remaining(headers: Mapping[str, object]) -> int | None:
    lowered = {str(k).casefold(): str(v) for k, v in headers.items()}
    for key, raw in lowered.items():
        if "requests-remaining" not in key:
            continue
        try:
            return int(float(raw))
        except ValueError:
            continue
    return None


def _products(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    products = payload.get("products")
    if not isinstance(products, list):
        return []
    return [row for row in products if isinstance(row, Mapping)]


def _load_old_asp_ids() -> set[str]:
    if not OLD_ASP_PATH.exists():
        return set()
    try:
        doc = json.loads(OLD_ASP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    ids: set[str] = set()
    evidence = doc.get("evidence") if isinstance(doc, Mapping) else None
    if not isinstance(evidence, list):
        return ids
    for row in evidence:
        payload = row.get("payload") if isinstance(row, Mapping) else None
        for product in _products(payload):
            item_id = str(product.get("item_id") or "").strip()
            if item_id:
                ids.add(item_id)
    return ids


def _load_cmapi_ids() -> set[str]:
    if not CMAPI_PATH.exists():
        return set()
    try:
        doc = json.loads(CMAPI_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    ids: set[str] = set()
    cards = doc.get("cards") if isinstance(doc, Mapping) else None
    if not isinstance(cards, list):
        return ids
    for card in cards:
        sold = card.get("ebay_psa10_sold_offers") if isinstance(card, Mapping) else None
        payload = sold.get("payload") if isinstance(sold, Mapping) else None
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, list):
            continue
        for offer in data:
            if not isinstance(offer, Mapping):
                continue
            item_id = str(offer.get("ebay_item_id") or "").strip()
            if item_id:
                ids.add(item_id)
    return ids


def price_confidence(product: Mapping[str, object]) -> str:
    buying_format = str(product.get("buying_format") or "").strip().casefold()
    if buying_format == "auction":
        return "PROVIDER_REPORTED_SOLD_STRONG_AUCTION"
    if buying_format == "buy it now":
        return "PROVIDER_REPORTED_SOLD_STRONG_BIN"
    if "offer" in buying_format:
        return "PROVIDER_REPORTED_SOLD_BEST_OFFER_PRICE_UNVERIFIED"
    return "PROVIDER_REPORTED_SOLD_FORMAT_UNKNOWN"


def _request(key: str, body: Mapping[str, object]) -> tuple[int | None, object | None, int | None]:
    try:
        response = requests.post(
            URL,
            headers={
                "Content-Type": "application/json",
                "x-rapidapi-host": HOST,
                "x-rapidapi-key": key,
            },
            json=dict(body),
            timeout=30,
        )
    except requests.RequestException:
        return None, None, None
    remaining = _quota_remaining(response.headers)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, remaining


def _markdown(report: Mapping[str, object]) -> str:
    sites = report.get("sites") if isinstance(report.get("sites"), Mapping) else {}
    lines = [
        "# eBay ASP /search probe",
        "",
        f"- Calls: `{report.get('calls')}/{CALL_CAP}`",
        f"- Quota remaining: `{report.get('quota_remaining')}`",
        f"- /search schema usable: `{report.get('search_schema_usable')}`",
        f"- Raw products: `{report.get('raw_products')}`",
        f"- Strict PSA10 matches: `{report.get('strict_matches')}`",
        f"- Unique strict item IDs: `{report.get('strict_unique_item_ids')}`",
        f"- Overlap with old /findCompletedItems artifact: `{report.get('old_asp_overlap')}`",
        f"- Overlap with CMAPI: `{report.get('cmapi_overlap')}`",
        f"- New vs CMAPI: `{report.get('new_vs_cmapi')}`",
        f"- Buying formats: `{report.get('buying_formats')}`",
        f"- Evidence confidence: `{report.get('confidence_counts')}`",
        "",
        "| Site | Calls | Raw | Strict | Currency | Domains |",
        "|---|---:|---:|---:|---|---|",
    ]
    for site in ("US", "UK"):
        row = sites.get(site) if isinstance(sites.get(site), Mapping) else {}
        lines.append(
            f"| {site} | {row.get('calls', 0)} | {row.get('raw', 0)} | {row.get('strict', 0)} | "
            f"{row.get('currencies', {})} | {row.get('domains', {})} |"
        )
    lines += [
        "",
        "Best Offer prices remain explicitly unverified until the provider/original eBay semantics are proven.",
        "No CMAPI call, purchase, bid, checkout, payment or grading action is performed.",
    ]
    return "\n".join(lines)


def main() -> int:
    key = os.getenv("EBAY_ASP_RAPIDAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("EBAY_ASP_RAPIDAPI_KEY missing")

    old_asp_ids = _load_old_asp_ids()
    cmapi_ids = _load_cmapi_ids()
    calls = 0
    quota_remaining: int | None = None
    schema_usable = False
    evidence: list[dict[str, object]] = []
    all_strict: list[Mapping[str, object]] = []
    site_summary: dict[str, dict[str, object]] = {
        site: {"calls": 0, "raw": 0, "strict": 0, "currencies": {}, "domains": {}}
        for site in SITES
    }

    for card in CARDS:
        for site_name, site_id in SITES.items():
            if calls >= CALL_CAP:
                break
            if quota_remaining is not None and quota_remaining <= MIN_REMAINING:
                break
            if calls:
                time.sleep(RATE_INTERVAL_SECONDS)

            body = {
                "keywords": f"{card['name']} {card['numerator']}/{card['denominator']} PSA 10",
                "excluded_keywords": "signed autograph autographed proxy custom metal jumbo lot bundle mystery",
                "category_id": CATEGORY_ID,
                "site_id": site_id,
            }
            status, payload, remaining = _request(key, body)
            calls += 1
            if remaining is not None:
                quota_remaining = remaining

            products = _products(payload)
            if calls == 1:
                schema_usable = status == 200 and isinstance(payload, Mapping) and isinstance(payload.get("products"), list)
                if not schema_usable:
                    evidence.append(
                        {
                            "card": dict(card),
                            "site": site_name,
                            "http": status,
                            "quota_remaining": remaining,
                            "payload": payload,
                        }
                    )
                    break

            strict = [row for row in products if strict_card_match(card, row)]
            all_strict.extend(strict)
            summary = site_summary[site_name]
            summary["calls"] = int(summary["calls"]) + 1
            summary["raw"] = int(summary["raw"]) + len(products)
            summary["strict"] = int(summary["strict"]) + len(strict)
            currencies = summary["currencies"] if isinstance(summary["currencies"], dict) else {}
            domains = summary["domains"] if isinstance(summary["domains"], dict) else {}
            for row in strict:
                currency = str(row.get("currency") or "UNKNOWN")
                domain = _domain(row.get("link"))
                currencies[currency] = currencies.get(currency, 0) + 1
                domains[domain] = domains.get(domain, 0) + 1
            summary["currencies"] = currencies
            summary["domains"] = domains
            evidence.append(
                {
                    "card": dict(card),
                    "site": site_name,
                    "site_id": site_id,
                    "request": body,
                    "http": status,
                    "quota_remaining": remaining,
                    "raw_count": len(products),
                    "strict_count": len(strict),
                    "response_url": payload.get("response_url") if isinstance(payload, Mapping) else None,
                    "payload": payload,
                }
            )
        if calls and not schema_usable:
            break
        if quota_remaining is not None and quota_remaining <= MIN_REMAINING:
            break

    strict_ids = {str(row.get("item_id") or "").strip() for row in all_strict if row.get("item_id")}
    buying_formats = Counter(str(row.get("buying_format") or "UNKNOWN") for row in all_strict)
    confidence_counts = Counter(price_confidence(row) for row in all_strict)
    report = {
        "provider": "ebay_average_selling_price_rapidapi",
        "endpoint": "/search",
        "host": HOST,
        "calls": calls,
        "quota_remaining": quota_remaining,
        "search_schema_usable": schema_usable,
        "raw_products": sum(int(row["raw"]) for row in site_summary.values()),
        "strict_matches": len(all_strict),
        "strict_unique_item_ids": len(strict_ids),
        "old_asp_overlap": len(strict_ids & old_asp_ids),
        "cmapi_overlap": len(strict_ids & cmapi_ids),
        "new_vs_cmapi": len(strict_ids - cmapi_ids),
        "buying_formats": dict(buying_formats),
        "confidence_counts": dict(confidence_counts),
        "sites": site_summary,
        "evidence": evidence,
        "safety": {
            "call_cap": CALL_CAP,
            "minimum_remaining_guard": MIN_REMAINING,
            "plan_request_limit": 50,
            "plan_limit_type": "HARD_LIMIT",
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
    return 0 if schema_usable else 2


if __name__ == "__main__":
    raise SystemExit(main())
