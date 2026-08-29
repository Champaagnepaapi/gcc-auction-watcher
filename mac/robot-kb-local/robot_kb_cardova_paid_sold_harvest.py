#!/usr/bin/env python3
"""Read-only Cardova paid-SOLD evidence harvest.

This module is the first semantic layer after the public Past Auctions probes.
It reuses the production Cardova single-card scope and the already-validated
anonymous browser capture; it does not introduce another Cardova identity
resolver.

Reviewed public Cardova evidence (2026-08-29) established the following:
- the Past Auctions page is public and its page-generated GET JSON exposes
  ``bid_payment_status``;
- the public UI renders ``WEEKLY.TEXT_103 == \"Payment Pending\"`` only while
  ``bid_payment_status <= 4``;
- reviewed historical rows use ``bid_payment_status == 5`` together with
  ``finished == 1``, ``canceled_at == null``, ``re_listed == 0`` and
  ``re_listing_count == 0``;
- Cardova's public auction guide states auction bidding currency is JPY and an
  unpaid winning transaction is invalidated/relisted rather than retained as a
  completed transaction.

Accordingly this harvest may classify a row as provider-level PAID/COMPLETED
sale evidence only when the exact reviewed status-5 state and all cancellation /
relisting guards agree. It still does NOT write ``SALE_TRANSACTION``: canonical
TCGdex identity is not resolved here and the API does not expose the exact
payment-completion timestamp. ``end_date`` is retained only as auction end time.

Identity-facing public Cardova surfaces are preserved losslessly enough for the
next read-only canonicalization phase: verbose/short set labels, provider title,
series and native card id. They remain retrieval/provenance only and cannot by
themselves prove a TCGdex identity.

No credentials, supplied cookies, request-header replay, POST, purchase, bid,
checkout, payment, Robot KB write, V4 economic use or notification occurs.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import v4_cardova_public_inventory as cardova_inventory  # noqa: E402
import robot_kb_cardova_closed_api_probe as closed_probe  # noqa: E402


PROVEN_PAID_BID_STATUS = 5
PAYMENT_PENDING_MAX_STATUS = 4
PROVEN_CURRENCY = "JPY"
_CERT_RE = re.compile(r"^\d{6,14}$")


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _int(value: object) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_iso(value: object) -> str:
    raw = _norm(value)
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat()


def _cert_number(row: Mapping[str, Any]) -> str:
    for key in (
        "certificate_number",
        "certification_number",
        "cert_number",
        "certification_no",
        "psa_cert_number",
    ):
        value = re.sub(r"\s+", "", str(row.get(key) or ""))
        if _CERT_RE.fullmatch(value):
            return value
    return ""


def classify_paid_sold_row(row: Mapping[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    """Classify one already-sanitized Cardova closed-auction row.

    The payment gate is deliberately exact: status 5 is accepted; <=4 is
    explicit pending according to the reviewed public UI; every other value is
    unproven. Cancellation/relisting state must independently agree.
    """
    if not isinstance(row, Mapping):
        return None, "ROW_NOT_OBJECT"

    accepted, scope_reason = cardova_inventory._supported_single_scope(row)
    if not accepted:
        return None, f"SCOPE_{scope_reason.upper()}"
    if cardova_inventory._listing_type(row.get("listing_type")) != 1:
        return None, "NOT_AUCTION"

    bid_payment_status = _int(row.get("bid_payment_status"))
    if bid_payment_status is None:
        return None, "BID_PAYMENT_STATUS_MISSING"
    if bid_payment_status <= PAYMENT_PENDING_MAX_STATUS:
        return None, "PAYMENT_PENDING"
    if bid_payment_status != PROVEN_PAID_BID_STATUS:
        return None, "BID_PAYMENT_STATUS_UNPROVEN"

    if _int(row.get("finished")) != 1:
        return None, "AUCTION_NOT_FINISHED"
    if row.get("canceled_at") not in (None, ""):
        return None, "CANCELED"
    if _int(row.get("re_listed")) not in (0, None):
        return None, "RELISTED"
    if _int(row.get("re_listing_count")) not in (0, None):
        return None, "RELISTED"

    ulid = _norm(row.get("ulid"))
    if not ulid:
        return None, "ULID_MISSING"
    final_bid_jpy = _int(row.get("bid_price"))
    if final_bid_jpy is None or final_bid_jpy <= 0:
        return None, "FINAL_BID_INVALID"
    auction_end_raw = _norm(row.get("end_date"))
    auction_end_utc = _utc_iso(auction_end_raw)
    if not auction_end_raw or not auction_end_utc:
        return None, "AUCTION_END_INVALID"
    cert = _cert_number(row)
    if not cert:
        return None, "CERT_NUMBER_UNPROVEN"

    return (
        {
            "source": "cardova_public_past_auction",
            "source_native_record_id": ulid,
            "source_url": f"https://www.cardova.co.jp/en/auction/card/{ulid}",
            "provider_sale_status": "PAID_COMPLETED",
            "provider_sale_status_proven": True,
            "bid_payment_status": bid_payment_status,
            "finished": 1,
            "canceled_at": None,
            "re_listed": 0,
            "re_listing_count": 0,
            "final_bid_jpy": final_bid_jpy,
            "currency": PROVEN_CURRENCY,
            "currency_proven": True,
            "price_component": "PROVIDER_FINAL_WINNING_BID",
            "all_in_price_proven": False,
            "auction_end_at_raw": auction_end_raw,
            "auction_end_at_utc": auction_end_utc,
            "payment_completed_at": "",
            "payment_completed_at_proven": False,
            "grader": "PSA",
            "grade": cardova_inventory._grade(row.get("grade")),
            "certification_number": cert,
            "language": _norm(row.get("language")),
            "card_name": _norm(row.get("player")),
            "set_name": _norm(row.get("variety") or row.get("variety_short")),
            "collector_number": _norm(row.get("card_number")),
            # Public provider-native identity surfaces. These are preserved for
            # deterministic retrieval only; none is accepted as canonical proof.
            "provider_set_name_short": _norm(row.get("variety_short")),
            "provider_series": _norm(row.get("series")),
            "provider_title": _norm(row.get("title")),
            "provider_item_name": _norm(row.get("item_name")),
            "provider_card_ulid": _norm(row.get("card_ulid")),
            "identity_status": "PENDING_TCGDEX",
            "microvariant_status": "PENDING_TCGDEX",
            "tcgdex_requests": 0,
            "sale_evidence_ready": True,
            "sale_transaction_ready": False,
        },
        "PAID_SOLD_EVIDENCE_READY",
    )


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PAID_SOLD_HARVEST",
        "public_anonymous_only": True,
        "fresh_browser_context": True,
        "credentials_used": False,
        "cookies_supplied": False,
        "storage_state_supplied": False,
        "authentication_headers_supplied": False,
        "request_headers_captured": False,
        "posts_issued": False,
        "direct_api_replay_used": False,
        "payment_pending_max_status": PAYMENT_PENDING_MAX_STATUS,
        "paid_bid_status_required": PROVEN_PAID_BID_STATUS,
        "payment_semantics_proven": True,
        "currency_semantics_proven": True,
        "proven_currency": PROVEN_CURRENCY,
        "identity_surfaces_preserved": True,
        "identity_resolution_attempted": False,
        "tcgdex_requests": 0,
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


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    records: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    for row in rows:
        record, reason = classify_paid_sold_row(row)
        if record is None:
            blocked[reason] += 1
            continue
        records.append(record)
    return {
        "rows_seen": len(rows),
        "paid_sold_evidence_count": len(records),
        "blocked": dict(sorted(blocked.items())),
        "records": records,
    }


def run(page_url: str, *, wait_ms: int) -> Mapping[str, Any]:
    captured = closed_probe.run_probe(page_url, wait_ms=wait_ms)
    out = safe_summary()
    out.update(
        {
            "page_url": page_url,
            "page_http_status": captured.get("page_http_status"),
            "captured_api_http_status": captured.get("captured_api_http_status"),
            "target_api_responses_captured": captured.get("target_api_responses_captured", 0),
        }
    )
    if captured.get("error"):
        out["error"] = captured.get("error")
        return out
    rows = captured.get("rows")
    if not isinstance(rows, list):
        out["error"] = "CLOSED_ROWS_NOT_AVAILABLE"
        return out
    out.update(summarize_rows([row for row in rows if isinstance(row, Mapping)]))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Cardova paid-SOLD evidence harvest")
    parser.add_argument("--page-url", default=closed_probe.DEFAULT_PAGE_URL)
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 500 <= args.wait_ms <= 8000:
        parser.error("--wait-ms must be between 500 and 8000")
    try:
        payload = run(args.page_url, wait_ms=args.wait_ms)
        code = 0 if "error" not in payload else 1
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
