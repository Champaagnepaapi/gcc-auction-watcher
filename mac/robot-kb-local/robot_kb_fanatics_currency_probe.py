#!/usr/bin/env python3
"""Anonymous read-only Fanatics sold-listing currency semantics probe.

The Sales History API exposes purchasePrice without a currency field. This probe
opens exact public Fanatics listing pages and inspects only Fanatics-owned JSON
responses plus bounded page text for an explicit ISO-4217 currency signal.

It does not infer USD from a dollar glyph and never writes Robot KB.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ALLOWED_HOST = "www.fanaticscollect.com"
ALLOWED_PREFIXES = ("/premier/", "/weekly/", "/buy-now/")
CURRENCY_CODES = frozenset({"USD", "GBP", "EUR", "CAD", "AUD", "JPY", "CHF"})
CURRENCY_KEY_RE = re.compile(r"(?:currency|pricecurrency|currencycode|iso.?4217)", re.I)
PRICE_KEY_RE = re.compile(r"(?:price|amount|total|hammer|premium)", re.I)
MAX_JSON_BYTES = 2_000_000
MAX_HITS = 100


def validate_listing_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("only public https://www.fanaticscollect.com listing URLs are allowed")
    if not any(parsed.path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise ValueError("URL must be a Premier, Weekly, or Buy Now listing")
    return parsed.geturl()


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = " ".join(str(value).split())
    return text[:300]


def currency_hits(value: Any, *, path: str = "$", output: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    hits = output if output is not None else []
    if len(hits) >= MAX_HITS:
        return hits
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key)
            if CURRENCY_KEY_RE.search(key_text):
                hits.append({"path": child_path, "kind": "currency_key", "value": _safe_scalar(child)})
            if isinstance(child, str) and child.strip().upper() in CURRENCY_CODES:
                hits.append({"path": child_path, "kind": "iso_currency_value", "value": child.strip().upper()})
            if len(hits) >= MAX_HITS:
                break
            currency_hits(child, path=child_path, output=hits)
        # Capture objects where a currency and a price-like field coexist.
        currencies = {
            str(v).strip().upper()
            for k, v in value.items()
            if (CURRENCY_KEY_RE.search(str(k)) or (isinstance(v, str) and v.strip().upper() in CURRENCY_CODES))
            and isinstance(v, str)
            and v.strip().upper() in CURRENCY_CODES
        }
        price_fields = {str(k): _safe_scalar(v) for k, v in value.items() if PRICE_KEY_RE.search(str(k))}
        if currencies and price_fields and len(hits) < MAX_HITS:
            hits.append({"path": path, "kind": "price_currency_object", "currency": sorted(currencies), "price_fields": price_fields})
    elif isinstance(value, list):
        for index, child in enumerate(value):
            currency_hits(child, path=f"{path}[{index}]", output=hits)
            if len(hits) >= MAX_HITS:
                break
    elif isinstance(value, str) and value.strip().upper() in CURRENCY_CODES:
        hits.append({"path": path, "kind": "iso_currency_value", "value": value.strip().upper()})
    return hits


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_FANATICS_CURRENCY_PROBE",
        "public_anonymous_only": True,
        "credentials_used": False,
        "headers_captured": False,
        "cookies_captured": False,
        "currency_inferred_from_dollar_glyph": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_probe(urls: Sequence[str], *, wait_ms: int) -> Mapping[str, Any]:
    checked = [validate_listing_url(url) for url in urls]
    results: list[dict[str, Any]] = []
    all_codes: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        for listing_url in checked:
            response_hits: list[dict[str, Any]] = []

            def on_response(response) -> None:
                parsed = urlparse(response.url)
                if not parsed.hostname or not parsed.hostname.endswith("fanaticscollect.com"):
                    return
                ctype = str(response.headers.get("content-type") or "")
                if "json" not in ctype.casefold():
                    return
                try:
                    body = response.body()
                except Exception:
                    return
                if len(body) > MAX_JSON_BYTES:
                    return
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    return
                hits = currency_hits(payload)
                if hits:
                    response_hits.append({"response_url": response.url, "hits": hits[:MAX_HITS]})

            page.on("response", on_response)
            nav = page.goto(listing_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(wait_ms)
            body_text = " ".join((page.locator("body").inner_text(timeout=5_000) or "").split())
            dom_codes = sorted({code for code in CURRENCY_CODES if re.search(rf"\b{re.escape(code)}\b", body_text)})
            for code in dom_codes:
                all_codes.add(code)
            for response in response_hits:
                for hit in response["hits"]:
                    value = hit.get("value")
                    if isinstance(value, str) and value in CURRENCY_CODES:
                        all_codes.add(value)
                    for code in hit.get("currency", []) if isinstance(hit.get("currency"), list) else []:
                        if code in CURRENCY_CODES:
                            all_codes.add(code)
            results.append({
                "url": listing_url,
                "page_http_status": int(nav.status) if nav is not None else 0,
                "dom_currency_codes": dom_codes,
                "response_currency_hits": response_hits[:30],
                "dollar_glyph_present": "$" in body_text,
            })
            page.remove_listener("response", on_response)
        context.close()
        browser.close()

    summary = safe_summary()
    summary.update({
        "urls_checked": len(checked),
        "explicit_currency_codes": sorted(all_codes),
        "currency_semantics_proven": len(all_codes) == 1,
        "proven_currency": next(iter(all_codes)) if len(all_codes) == 1 else "",
        "results": results,
    })
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Anonymous Fanatics sold-listing currency semantics probe")
    parser.add_argument("--url", action="append", dest="urls", required=True)
    parser.add_argument("--wait-ms", type=int, default=1500)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 250 <= args.wait_ms <= 5000:
        parser.error("--wait-ms must be between 250 and 5000")
    try:
        payload = run_probe(args.urls, wait_ms=args.wait_ms)
        rc = 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        rc = 1
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
