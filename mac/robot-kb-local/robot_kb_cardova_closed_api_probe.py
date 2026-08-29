#!/usr/bin/env python3
"""Bounded anonymous probe for Cardova's public closed-auction API.

The endpoint was observed live from Cardova's public Past Auctions page. This
probe performs one public HTTPS GET and emits only a strict whitelist of
market/card/status fields. It does not classify any row as a completed paid sale
and never writes Robot KB.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_URL = (
    "https://bg.cardova.co.jp/api/v1/auction/list"
    "?page=1&limit=24&sort=price_desc&status=close&lang_code=en"
)
ALLOWED_HOST = "bg.cardova.co.jp"
MAX_BYTES = 2_000_000
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


def _allowed_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme.casefold() == "https" and (parsed.hostname or "").casefold() == ALLOWED_HOST


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
    price = obj.get("bid_price")
    has_price = price not in (None, "")
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
        "mode": "READ_ONLY_CARDOVA_CLOSED_API_PROBE",
        "public_anonymous_only": True,
        "credentials_used": False,
        "cookies_supplied": False,
        "authentication_headers_supplied": False,
        "posts_issued": False,
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


def run_probe(url: str, *, timeout_seconds: float) -> Mapping[str, Any]:
    if not _allowed_url(url):
        raise ValueError(f"unsupported Cardova URL: {url}")
    req = Request(url, method="GET", headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", 0) or 0)
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Cardova response exceeded byte cap")
    payload = json.loads(raw.decode("utf-8"))

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

    summary = safe_summary()
    summary.update(
        {
            "url": url,
            "http_status": status,
            "closed_row_count": len(rows),
            "status_field_names": sorted(status_names),
            "currency_field_names": sorted(currency_names),
            "top_level_type": type(payload).__name__,
            "observed_key_names": sorted(all_keys)[:300],
            "rows": list(rows.values()),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Cardova closed-auction API schema probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1.0 <= args.timeout_seconds <= 30.0:
        parser.error("--timeout-seconds must be between 1 and 30")
    try:
        payload = run_probe(args.url, timeout_seconds=args.timeout_seconds)
        code = 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
