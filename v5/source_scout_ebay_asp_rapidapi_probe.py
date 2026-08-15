from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import requests

HOST = "ebay-average-selling-price.p.rapidapi.com"
URL = f"https://{HOST}/findCompletedItems"
CALL_CAP = 6
RATE_INTERVAL_SECONDS = 1.05
CATEGORY_ID = "183454"  # eBay Collectible Card Games > Single Cards
SITES = {"US": "0", "UK": "3", "FR": "71"}
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
)
REPORT_JSON = Path("ebay_asp_rapidapi_probe.json")
REPORT_MD = Path("ebay_asp_rapidapi_probe.md")
CMAPI_PATH = Path("prior-cmapi/cmapi_opportunity_evidence.json")


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _domain(value: object) -> str:
    try:
        host = urlparse(str(value or "")).hostname
    except ValueError:
        host = None
    return host.casefold() if host else "UNKNOWN"


def _signed_or_autographed(title: object) -> bool:
    text = _norm(title)
    tokens = set(text.split())
    return bool(tokens & {"signed", "autograph", "autographed", "auto"})


def strict_card_match(card: Mapping[str, str], product: Mapping[str, object]) -> bool:
    title = str(product.get("title") or "")
    norm = _norm(title)
    if not norm or _signed_or_autographed(title):
        return False
    if "psa" not in norm.split():
        return False
    if not re.search(r"\bpsa\s*(?:gem\s*mint\s*)?10\b", norm):
        return False
    for token in _norm(card["name"]).split():
        if token not in norm.split():
            return False
    numerator = re.escape(card["numerator"])
    denominator = re.escape(card["denominator"])
    # Accept 215, #215 or 215/203. If a denominator is explicitly present it
    # must be the canonical one. Name+numerator is unique for these sentinels.
    if not re.search(rf"(?<!\d){numerator}(?!\d)", title):
        return False
    explicit = re.search(rf"(?<!\d){numerator}\s*/\s*(\d+)", title)
    if explicit and explicit.group(1) != card["denominator"]:
        return False
    if re.search(r"\b(?:proxy|custom|metal|jumbo|lot|bundle|mystery)\b", norm):
        return False
    return True


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


def _products(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    products = payload.get("products")
    if not isinstance(products, list):
        return []
    return [row for row in products if isinstance(row, Mapping)]


def _markdown(report: Mapping[str, object]) -> str:
    sites = report.get("sites") if isinstance(report.get("sites"), Mapping) else {}
    lines = [
        "# eBay Average Selling Price RapidAPI probe",
        "",
        f"- Calls: `{report.get('calls')}/{CALL_CAP}`",
        f"- Last quota remaining header: `{report.get('quota_remaining')}`",
        f"- Raw SOLD products returned: `{report.get('raw_products')}`",
        f"- Strict PSA10 card matches: `{report.get('strict_matches')}`",
        f"- CMAPI item-id overlap: `{report.get('cmapi_overlap')}`",
        f"- New item IDs vs CMAPI: `{report.get('new_vs_cmapi')}`",
        "",
        "| Site | Calls | Raw | Strict | Currency | Domains | CMAPI overlap |",
        "|---|---:|---:|---:|---|---|---:|",
    ]
    for site in ("US", "UK", "FR"):
        row = sites.get(site) if isinstance(sites.get(site), Mapping) else {}
        lines.append(
            f"| {site} | {row.get('calls', 0)} | {row.get('raw', 0)} | {row.get('strict', 0)} | "
            f"{row.get('currencies', {})} | {row.get('domains', {})} | {row.get('cmapi_overlap', 0)} |"
        )
    lines += [
        "",
        "Provider Basic plan has a 50-request/month hard limit; this probe is capped at 6 calls.",
        "No CMAPI request, purchase, bid, checkout, payment or grading action is performed.",
    ]
    return "\n".join(lines)


def main() -> int:
    key = os.getenv("EBAY_ASP_RAPIDAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("EBAY_ASP_RAPIDAPI_KEY missing")

    old_by_id = _load_cmapi()
    calls = 0
    quota_remaining: int | None = None
    evidence: list[dict[str, object]] = []
    all_strict: list[Mapping[str, object]] = []
    raw_products = 0
    site_summary: dict[str, dict[str, object]] = {
        site: {"calls": 0, "raw": 0, "strict": 0, "currencies": {}, "domains": {}, "cmapi_overlap": 0}
        for site in SITES
    }

    for card in CARDS:
        for site_name, site_id in SITES.items():
            if calls >= CALL_CAP:
                break
            if calls:
                time.sleep(RATE_INTERVAL_SECONDS)
            keywords = f"{card['name']} {card['numerator']}/{card['denominator']} PSA 10"
            body = {
                "keywords": keywords,
                "excluded_keywords": "signed autograph autographed proxy custom metal jumbo lot bundle mystery",
                "max_search_results": 60,
                "category_id": CATEGORY_ID,
                "remove_outliers": False,
                "site_id": site_id,
            }
            status, payload, remaining = _request(key, body)
            calls += 1
            if remaining is not None:
                quota_remaining = remaining
            products = _products(payload)
            strict = [row for row in products if strict_card_match(card, row)]
            raw_products += len(products)
            all_strict.extend(strict)
            summary = site_summary[site_name]
            summary["calls"] = int(summary["calls"]) + 1
            summary["raw"] = int(summary["raw"]) + len(products)
            summary["strict"] = int(summary["strict"]) + len(strict)
            currencies = summary["currencies"] if isinstance(summary["currencies"], dict) else {}
            domains = summary["domains"] if isinstance(summary["domains"], dict) else {}
            overlap = 0
            for row in strict:
                currency = str(row.get("currency") or "UNKNOWN")
                domain = _domain(row.get("link"))
                currencies[currency] = currencies.get(currency, 0) + 1
                domains[domain] = domains.get(domain, 0) + 1
                item_id = str(row.get("item_id") or "").strip()
                if item_id and item_id in old_by_id:
                    overlap += 1
            summary["currencies"] = currencies
            summary["domains"] = domains
            summary["cmapi_overlap"] = int(summary["cmapi_overlap"]) + overlap
            evidence.append(
                {
                    "card": dict(card),
                    "site": site_name,
                    "site_id": site_id,
                    "request": {k: v for k, v in body.items() if k != "x-rapidapi-key"},
                    "http": status,
                    "quota_remaining": remaining,
                    "raw_count": len(products),
                    "strict_count": len(strict),
                    "response_url": payload.get("response_url") if isinstance(payload, Mapping) else None,
                    "payload": payload,
                }
            )

    strict_ids = {str(row.get("item_id") or "").strip() for row in all_strict if row.get("item_id")}
    cmapi_overlap = len(strict_ids & set(old_by_id))
    report = {
        "provider": "ebay_average_selling_price_rapidapi",
        "host": HOST,
        "calls": calls,
        "quota_remaining": quota_remaining,
        "raw_products": raw_products,
        "strict_matches": len(all_strict),
        "strict_unique_item_ids": len(strict_ids),
        "cmapi_overlap": cmapi_overlap,
        "new_vs_cmapi": len(strict_ids - set(old_by_id)),
        "sites": site_summary,
        "evidence": evidence,
        "safety": {
            "call_cap": CALL_CAP,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
