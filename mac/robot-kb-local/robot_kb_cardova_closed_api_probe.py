#!/usr/bin/env python3
"""Capture Cardova closed-auction JSON from the public Past Auctions page.

A naked HTTP request to ``bg.cardova.co.jp/api/v1/auction/list`` returns 403,
while Cardova's public anonymous Past Auctions page itself issues the same GET
and receives HTTP 200. This diagnostic therefore observes that page-generated
GET response in a fresh Playwright context. It does not replay request headers,
import cookies/session state, classify a sale, or write Robot KB.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


DEFAULT_PAGE_URL = (
    "https://www.cardova.co.jp/en/auction/close"
    "?limit=24&page=1&sort=price_desc&status=close"
)
ALLOWED_PAGE_HOST = "www.cardova.co.jp"
ALLOWED_API_HOST = "bg.cardova.co.jp"
TARGET_API_PATH = "/api/v1/auction/list"
MAX_DEPTH = 8
MAX_LIST = 100
MAX_ROWS = 80
MAX_TEXT = 500

PUBLIC_FIELDS = frozenset(
    {
        "ulid", "listing_type", "bid_price", "start_price", "asking_price",
        "finished", "end_date", "scheduled_end_date", "status",
        "auction_status", "payment_status", "transaction_status",
        "paymentStatus", "transactionStatus", "paid", "paid_at",
        "payment_at", "completed_at", "sold_at", "currency", "currency_code",
        "currencyCode", "authentication_company_code", "grade", "language",
        "player", "variety", "variety_short", "card_number", "category",
        "category_name", "series", "title", "item_name", "card_ulid",
        "certification_number", "certificate_number", "cert_number",
        "certification_no", "psa_cert_number",
    }
)
STATUS_FIELDS = frozenset(
    {
        "status", "auction_status", "payment_status", "transaction_status",
        "paymentStatus", "transactionStatus", "paid", "paid_at", "payment_at",
        "completed_at", "sold_at",
    }
)
CURRENCY_FIELDS = frozenset({"currency", "currency_code", "currencyCode"})


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _allowed_page_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme.casefold() == "https" and (parsed.hostname or "").casefold() == ALLOWED_PAGE_HOST


def _target_closed_api_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() != ALLOWED_API_HOST:
        return False
    if parsed.path != TARGET_API_PATH:
        return False
    query = parse_qs(parsed.query)
    return query.get("status") == ["close"]


def _safe(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_DEPTH:
        return "<depth-capped>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_LIST:
                out["<truncated>"] = True
                break
            name = _norm(key)[:120]
            low = name.casefold()
            if any(
                token in low
                for token in (
                    "token", "cookie", "authorization", "password", "secret",
                    "email", "phone", "address", "member", "customer", "user",
                    "account", "seller", "buyer",
                )
            ):
                continue
            out[name] = _safe(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_safe(item, depth=depth + 1) for item in value[:MAX_LIST]]
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _norm(value)[:MAX_TEXT]


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _looks_like_closed_row(obj: Mapping[str, Any]) -> bool:
    if not _norm(obj.get("ulid")):
        return False
    has_price = obj.get("bid_price") not in (None, "")
    has_end = obj.get("end_date") not in (None, "") or obj.get("scheduled_end_date") not in (None, "")
    has_identity = any(obj.get(key) not in (None, "") for key in ("card_number", "player", "title", "item_name"))
    return bool(has_price and has_end and has_identity)


def _project(obj: Mapping[str, Any]) -> Mapping[str, Any]:
    row = {key: obj.get(key) for key in PUBLIC_FIELDS if key in obj}
    row["status_fields_present"] = {key: row.get(key) for key in STATUS_FIELDS if key in row}
    row["currency_fields_present"] = {key: row.get(key) for key in CURRENCY_FIELDS if key in row}
    return _safe(row)


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_CLOSED_BROWSER_CAPTURE",
        "public_anonymous_only": True,
        "fresh_browser_context": True,
        "credentials_used": False,
        "cookies_supplied": False,
        "storage_state_supplied": False,
        "authentication_headers_supplied": False,
        "request_headers_captured": False,
        "posts_issued": False,
        "direct_api_replay_used": False,
        "closed_rows_promoted_to_sale": False,
        "payment_semantics_proven": False,
        "currency_semantics_proven": False,
        "sale_transaction_ready": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def _summarize_payload(payload: Any) -> Mapping[str, Any]:
    rows: dict[str, Mapping[str, Any]] = {}
    all_keys: set[str] = set()
    status_names: set[str] = set()
    currency_names: set[str] = set()
    for obj in _walk(payload):
        for key in obj.keys():
            name = _norm(key)
            if name:
                all_keys.add(name)
        if not _looks_like_closed_row(obj):
            continue
        row = _project(obj)
        ulid = _norm(row.get("ulid"))
        if not ulid:
            continue
        rows[ulid] = row
        status_names.update(key for key in STATUS_FIELDS if key in obj)
        currency_names.update(key for key in CURRENCY_FIELDS if key in obj)
        if len(rows) >= MAX_ROWS:
            break
    return {
        "closed_row_count": len(rows),
        "status_field_names": sorted(status_names),
        "currency_field_names": sorted(currency_names),
        "top_level_type": type(payload).__name__,
        "observed_key_names": sorted(all_keys)[:300],
        "rows": list(rows.values()),
    }


def run_probe(page_url: str, *, wait_ms: int) -> Mapping[str, Any]:
    if not _allowed_page_url(page_url):
        raise ValueError(f"unsupported Cardova page URL: {page_url}")

    captured: list[tuple[str, int, Any]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_response(response):
            response_url = str(response.url or "")
            if not _target_closed_api_url(response_url):
                return
            try:
                method = str(response.request.method or "").upper()
            except Exception:
                method = ""
            if method != "GET":
                return
            try:
                payload = response.json()
            except Exception:
                return
            captured.append((response_url[:700], int(response.status), payload))

        page.on("response", on_response)
        page_response = page.goto(page_url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(wait_ms)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(min(wait_ms, 1500))
        except Exception:
            pass
        page_http_status = int(page_response.status) if page_response is not None else 0
        final_url = str(page.url)[:700]
        context.close()
        browser.close()

    summary = safe_summary()
    summary.update(
        {
            "page_url": page_url,
            "final_url": final_url,
            "page_http_status": page_http_status,
            "target_api_responses_captured": len(captured),
        }
    )
    if not captured:
        summary["error"] = "TARGET_CLOSED_API_RESPONSE_NOT_OBSERVED"
        return summary

    response_url, status, payload = captured[-1]
    summary.update(
        {
            "captured_api_url": response_url,
            "captured_api_http_status": status,
            **_summarize_payload(payload),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Cardova closed-auction browser response probe")
    parser.add_argument("--page-url", default=DEFAULT_PAGE_URL)
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 500 <= args.wait_ms <= 8000:
        parser.error("--wait-ms must be between 500 and 8000")
    try:
        payload = run_probe(args.page_url, wait_ms=args.wait_ms)
        code = 0 if "error" not in payload else 1
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
