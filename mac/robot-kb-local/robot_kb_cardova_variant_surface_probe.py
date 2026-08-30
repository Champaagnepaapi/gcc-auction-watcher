#!/usr/bin/env python3
"""Read-only Cardova native variant-surface probe.

The paid-SOLD harvest intentionally kept only the identity fields needed for the
first canonicalization attempts. Production Cardova capture already whitelists
structured provider fields ``attribute``, ``attribute2`` and ``attribute3``.
This diagnostic temporarily adds those same public fields to the closed-auction
projection, then reports them only for rows that independently pass the existing
PAID_COMPLETED gate.

The fields are evidence surfaces only. They do not prove finish, edition,
printing or any other microvariant by themselves. No fuzzy interpretation,
Robot KB write, SALE_TRANSACTION, V4 economic use, notification or commercial
action is possible here.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_closed_api_probe as closed_probe  # noqa: E402
import robot_kb_cardova_paid_sold_harvest as paid_harvest  # noqa: E402
import robot_kb_cardova_number_namespace_probe as namespace_probe  # noqa: E402


EXTRA_PUBLIC_FIELDS = frozenset({"attribute", "attribute2", "attribute3"})
DEFAULT_MAX_RECORDS = 24
HARD_MAX_RECORDS = 50


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _project_paid_row(row: Mapping[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    paid, reason = paid_harvest.classify_paid_sold_row(row)
    if paid is None:
        return None, reason

    _local_id, namespace, _parse_status = namespace_probe.printed_number_namespace(
        paid.get("collector_number")
    )
    language = _norm(paid.get("language")).casefold()
    promo_candidate = bool(namespace and language in {"japanese", "ja", "jp"})

    return (
        {
            "source_native_record_id": _norm(paid.get("source_native_record_id")),
            "certification_number": _norm(paid.get("certification_number")),
            "card_name": _norm(paid.get("card_name")),
            "collector_number": _norm(paid.get("collector_number")),
            "language": _norm(paid.get("language")),
            "grader": _norm(paid.get("grader")),
            "grade": _norm(paid.get("grade")),
            "provider_set_name": _norm(paid.get("set_name")),
            "provider_set_name_short": _norm(paid.get("provider_set_name_short")),
            "provider_attribute": _norm(row.get("attribute")),
            "provider_attribute2": _norm(row.get("attribute2")),
            "provider_attribute3": _norm(row.get("attribute3")),
            "japanese_structured_promo_candidate": promo_candidate,
            "microvariant_status": "UNPROVEN",
            "sale_transaction_ready": False,
        },
        "PAID_ROW_SURFACES_CAPTURED",
    )


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_NATIVE_VARIANT_SURFACE_PROBE",
        "public_anonymous_only": True,
        "fresh_browser_context": True,
        "extra_public_fields": sorted(EXTRA_PUBLIC_FIELDS),
        "provider_fields_are_identity_proof": False,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "microvariant_inferred": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def summarize_rows(rows: Sequence[Mapping[str, Any]], *, max_records: int) -> Mapping[str, Any]:
    records: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    nonempty: Counter[str] = Counter()
    promo_count = 0

    for row in rows:
        projected, reason = _project_paid_row(row)
        if projected is None:
            blocked[reason] += 1
            continue
        if len(records) >= max_records:
            break
        records.append(projected)
        if projected["japanese_structured_promo_candidate"]:
            promo_count += 1
        for key in ("provider_attribute", "provider_attribute2", "provider_attribute3"):
            if projected.get(key):
                nonempty[key] += 1

    return {
        "rows_seen": len(rows),
        "selected_paid_records": len(records),
        "japanese_structured_promo_candidate_count": promo_count,
        "nonempty_surface_counts": dict(sorted(nonempty.items())),
        "blocked": dict(sorted(blocked.items())),
        "records": records,
    }


def run(page_url: str, *, wait_ms: int, max_records: int) -> Mapping[str, Any]:
    original_fields = closed_probe.PUBLIC_FIELDS
    try:
        closed_probe.PUBLIC_FIELDS = frozenset(set(original_fields) | set(EXTRA_PUBLIC_FIELDS))
        captured = closed_probe.run_probe(page_url, wait_ms=wait_ms)
    finally:
        closed_probe.PUBLIC_FIELDS = original_fields

    out = dict(safe_summary())
    out.update(
        {
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
    out.update(
        summarize_rows(
            [row for row in rows if isinstance(row, Mapping)],
            max_records=max_records,
        )
    )
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect public Cardova variant surfaces")
    parser.add_argument("--page-url", default=closed_probe.DEFAULT_PAGE_URL)
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 500 <= args.wait_ms <= 8000:
        parser.error("--wait-ms must be between 500 and 8000")
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")

    try:
        payload = run(args.page_url, wait_ms=args.wait_ms, max_records=args.max_records)
        code = 0 if "error" not in payload else 1
    except Exception as error:
        payload = safe_summary()
        payload["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
