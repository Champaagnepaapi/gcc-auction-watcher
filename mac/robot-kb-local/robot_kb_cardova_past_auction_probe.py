#!/usr/bin/env python3
"""Read-only anonymous probe for Cardova past-auction transaction semantics.

This diagnostic reuses the public/sessionless Cardova access model already used
by V4. It inspects only public GET JSON generated while visiting the Past
Auctions page and reports whether explicit transaction/payment semantics are
present alongside final auction fields.

It does NOT classify a row as a paid sale and never writes Robot KB.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PAST_AUCTIONS_URL = "https://www.cardova.co.jp/en/auction/close?kind=1&page=1"
ALLOWED_HOST_SUFFIX = "cardova.co.jp"
MAX_RESPONSES = 80
MAX_ROWS = 80
MAX_DEPTH = 7
MAX_LIST = 60
MAX_TEXT = 500

PUBLIC_FIELDS = frozenset(
    {
        "ulid", "listing_type", "bid_price", "start_price", "finished",
        "end_date", "scheduled_end_date", "status", "auction_status",
        "payment_status", "transaction_status", "paymentStatus",
        "transactionStatus", "paid", "paid_at", "payment_at",
        "completed_at", "sold_at", "authentication_company_code", "grade",
        "language", "player", "variety", "variety_short", "card_number",
        "category", "category_name", "series", "title", "item_name",
        "card_ulid",
    }
)

STATUS_KEYS = frozenset(
    {
        "status", "auction_status", "payment_status", "transaction_status",
        "paymentStatus", "transactionStatus", "paid", "paid_at", "payment_at",
        "completed_at", "sold_at",
    }
)


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _allowed_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").casefold()
    return parsed.scheme.casefold() == "https" and (
        host == ALLOWED_HOST_SUFFIX or host.endswith("." + ALLOWED_HOST_SUFFIX)
    )


def _safe(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_DEPTH:
        return "<depth-capped>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for i, (key, item) in enumerate(value.items()):
            if i >= MAX_LIST:
                out["<truncated>"] = True
                break
            name = _norm(key)[:120]
            low = name.casefold()
            if any(
                token in low
                for token in (
                    "token", "cookie", "authorization", "password", "secret",
                    "email", "phone", "address", "member", "customer", "user",
                    "account",
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


def _looks_like_past_auction_row(obj: Mapping[str, Any]) -> bool:
    if not _norm(obj.get("ulid")):
        return False
    has_price = obj.get("bid_price") not in (None, "")
    has_end = obj.get("end_date") not in (None, "") or obj.get("scheduled_end_date") not in (None, "")
    has_card = obj.get("card_number") not in (None, "") or obj.get("player") not in (None, "")
    return bool(has_price and has_end and has_card)


def _project_row(obj: Mapping[str, Any]) -> Mapping[str, Any]:
    projected = {key: obj.get(key) for key in PUBLIC_FIELDS if key in obj}
    projected["status_fields_present"] = {
        key: projected.get(key) for key in STATUS_KEYS if key in projected
    }
    return _safe(projected)


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PAST_AUCTION_PROBE",
        "public_anonymous_only": True,
        "credentials_used": False,
        "cookies_supplied": False,
        "authentication_headers_supplied": False,
        "public_past_auction_rows_promoted_to_sale": False,
        "payment_semantics_proven": False,
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


def run_probe(*, url: str, wait_ms: int) -> Mapping[str, Any]:
    if not _allowed_url(url):
        raise ValueError(f"unsupported Cardova URL: {url}")

    summary = safe_summary()
    rows: list[Mapping[str, Any]] = []
    response_meta: list[Mapping[str, Any]] = []
    status_field_names: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_response(response):
            if len(response_meta) >= MAX_RESPONSES:
                return
            response_url = str(response.url or "")
            if not _allowed_url(response_url):
                return
            try:
                method = str(response.request.method or "").upper()
            except Exception:
                method = ""
            if method != "GET":
                return
            try:
                content_type = str(response.headers.get("content-type", "")).casefold()
            except Exception:
                content_type = ""
            if "json" not in content_type:
                return
            try:
                payload = response.json()
            except Exception:
                return

            found = 0
            for obj in _walk(payload):
                if not _looks_like_past_auction_row(obj):
                    continue
                projected = _project_row(obj)
                if len(rows) < MAX_ROWS:
                    rows.append(projected)
                for key in STATUS_KEYS:
                    if key in obj:
                        status_field_names.add(key)
                found += 1
                if found >= MAX_ROWS:
                    break
            response_meta.append(
                {
                    "url": response_url[:500],
                    "status": int(response.status),
                    "past_auction_rows_found": found,
                }
            )

        page.on("response", on_response)
        response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(wait_ms)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(min(wait_ms, 1500))
        except Exception:
            pass
        final_url = str(page.url)[:500]
        page_status = int(response.status) if response is not None else 0
        context.close()
        browser.close()

    unique: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        ulid = _norm(row.get("ulid"))
        if ulid:
            unique[ulid] = row

    summary.update(
        {
            "url": url,
            "final_url": final_url,
            "page_http_status": page_status,
            "json_responses_seen": len(response_meta),
            "response_meta": response_meta,
            "past_auction_row_count": len(unique),
            "status_field_names": sorted(status_field_names),
            "rows": list(unique.values()),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Cardova public past-auction schema probe")
    parser.add_argument("--url", default=PAST_AUCTIONS_URL)
    parser.add_argument("--wait-ms", type=int, default=1200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 250 <= args.wait_ms <= 5000:
        parser.error("--wait-ms must be between 250 and 5000")
    try:
        payload = run_probe(url=args.url, wait_ms=args.wait_ms)
        code = 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
