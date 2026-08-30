#!/usr/bin/env python3
"""Bounded recurring Cardova paid/completed SOLD collector for local Robot KB.

This lane reuses the already validated #199 stack:

public Past Auctions browser capture -> strict paid/completed gate -> P3
SALE_TRANSACTION with unresolved identity.

Coverage strategy is intentionally independent of any unproven Cardova sort
semantics. Every run revisits a small front-page window and also advances a
bounded page-rotation cursor. The durable P3 sale key makes repeated sightings
idempotent, while the rotation gradually accumulates older history.

Safety contract:
- public anonymous Cardova pages only; page-generated GET JSON only;
- no login/session/cookies/request-header replay/POST;
- exact status-5 + finished + no cancellation/relist gate is unchanged;
- final bid is HAMMER_PRICE JPY only; buyer premium/all-in is not fabricated;
- canonical identity and commercial microvariant stay unresolved;
- durable write is allowed only with explicit --commit and only to the guarded
  local loopback robot_pokemon_kb PostgreSQL database;
- cursor state advances only after a successful durable ingest;
- no V4 economic use, notification or commerce action.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_closed_api_probe as closed_probe  # noqa: E402
import robot_kb_cardova_paid_sold_harvest as paid_harvest  # noqa: E402
import robot_kb_cardova_sale_transaction_dry_run as dry_run  # noqa: E402
import robot_kb_cardova_sale_transaction_ingest as durable_ingest  # noqa: E402

from robot_kb.repository import KnowledgeBase  # noqa: E402


SCHEMA_VERSION = 1
BASE_PAGE_URL = "https://www.cardova.co.jp/en/auction/close"
DEFAULT_PAGE_SIZE = 24
DEFAULT_FRONT_PAGES = 2
DEFAULT_ROTATION_PAGES = 4
DEFAULT_WAIT_MS = 1200
HARD_MAX_PAGE_SIZE = 24
HARD_MAX_PAGES_PER_RUN = 12
EXTRA_PUBLIC_FIELDS = frozenset({"attribute", "attribute2", "attribute3"})


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "next_rotation_page": 1,
        "successful_cycles": 0,
        "last_success_at": None,
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_state()
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        return empty_state()
    state = dict(payload)
    try:
        cursor = int(state.get("next_rotation_page", 1))
    except (TypeError, ValueError):
        cursor = 1
    state["next_rotation_page"] = max(1, cursor)
    return state


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(
        json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def page_url(page_number: int, *, page_size: int) -> str:
    page = int(page_number)
    limit = int(page_size)
    if page < 1:
        raise ValueError("Cardova page number must be >= 1")
    if not 1 <= limit <= HARD_MAX_PAGE_SIZE:
        raise ValueError(f"Cardova page size must be 1..{HARD_MAX_PAGE_SIZE}")
    query = urlencode(
        {
            "kind": "1",
            "limit": str(limit),
            "page": str(page),
            "status": "close",
        }
    )
    return f"{BASE_PAGE_URL}?{query}"


def _capture_page(url: str, *, wait_ms: int) -> Mapping[str, Any]:
    original_fields = closed_probe.PUBLIC_FIELDS
    try:
        closed_probe.PUBLIC_FIELDS = frozenset(set(original_fields) | set(EXTRA_PUBLIC_FIELDS))
        return closed_probe.run_probe(url, wait_ms=wait_ms)
    finally:
        closed_probe.PUBLIC_FIELDS = original_fields


def _paid_record(row: Mapping[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    record, reason = paid_harvest.classify_paid_sold_row(row)
    if record is None:
        return None, reason
    # Preserve provider-native surfaces as raw/provider evidence only. They are
    # deliberately not added to the P3 exact-identity claim set.
    record["provider_attribute"] = _norm(row.get("attribute"))
    record["provider_attribute2"] = _norm(row.get("attribute2"))
    record["provider_attribute3"] = _norm(row.get("attribute3"))
    return record, reason


def _page_plan(cursor: int, *, front_pages: int, rotation_pages: int) -> tuple[list[int], set[int]]:
    front = list(range(1, front_pages + 1))
    rotation = list(range(cursor, cursor + rotation_pages))
    ordered = list(dict.fromkeys(front + rotation))
    return ordered, set(rotation)


def collect_cycle(
    state: Mapping[str, Any],
    *,
    front_pages: int,
    rotation_pages: int,
    page_size: int,
    wait_ms: int,
    fetch_page: Optional[Callable[[str], Mapping[str, Any]]] = None,
) -> tuple[list[Mapping[str, Any]], dict[str, Any], dict[str, Any]]:
    """Collect one bounded front+rotation cycle without mutating durable state."""

    if front_pages < 1 or rotation_pages < 1:
        raise ValueError("front_pages and rotation_pages must be >= 1")
    if front_pages + rotation_pages > HARD_MAX_PAGES_PER_RUN:
        raise ValueError(f"at most {HARD_MAX_PAGES_PER_RUN} page slots are allowed per run")
    if not 500 <= wait_ms <= 8000:
        raise ValueError("wait_ms must be between 500 and 8000")

    try:
        cursor = max(1, int(state.get("next_rotation_page", 1)))
    except (TypeError, ValueError):
        cursor = 1
    plan, rotation_set = _page_plan(
        cursor,
        front_pages=front_pages,
        rotation_pages=rotation_pages,
    )

    if fetch_page is None:
        fetch_page = lambda url: _capture_page(url, wait_ms=wait_ms)

    records: dict[str, Mapping[str, Any]] = {}
    blocked: Counter[str] = Counter()
    page_summaries: list[dict[str, Any]] = []
    previous_rotation_ulids: Optional[tuple[str, ...]] = None
    next_cursor = cursor
    rotation_boundary = False
    rotation_pages_scanned = 0

    for page_number in plan:
        url = page_url(page_number, page_size=page_size)
        captured = fetch_page(url)
        if captured.get("error"):
            raise RuntimeError(
                f"Cardova page {page_number} capture failed: {captured.get('error')}"
            )
        rows = captured.get("rows")
        if not isinstance(rows, list):
            raise RuntimeError(f"Cardova page {page_number} returned no rows[]")

        clean_rows = [row for row in rows if isinstance(row, Mapping)]
        all_ulids = tuple(
            sorted(
                {
                    _norm(row.get("ulid"))
                    for row in clean_rows
                    if _norm(row.get("ulid"))
                }
            )
        )
        accepted = 0
        for row in clean_rows:
            record, reason = _paid_record(row)
            if record is None:
                blocked[reason] += 1
                continue
            native_id = _norm(record.get("source_native_record_id"))
            if not native_id:
                blocked["SOURCE_ID_MISSING"] += 1
                continue
            records[native_id] = record
            accepted += 1

        is_rotation = page_number in rotation_set
        page_summaries.append(
            {
                "page": page_number,
                "rows_seen": len(clean_rows),
                "paid_sold_ready": accepted,
                "rotation_page": is_rotation,
                "page_http_status": captured.get("page_http_status"),
                "captured_api_http_status": captured.get("captured_api_http_status"),
            }
        )

        if not is_rotation:
            continue
        rotation_pages_scanned += 1
        if not clean_rows:
            rotation_boundary = True
            next_cursor = 1
            break
        if previous_rotation_ulids is not None and all_ulids and all_ulids == previous_rotation_ulids:
            # Some pagers clamp beyond their final page instead of returning an
            # empty result. Identical consecutive page identity sets are treated
            # as a safe end-of-rotation signal, never as evidence of absence.
            rotation_boundary = True
            next_cursor = 1
            break
        previous_rotation_ulids = all_ulids
        next_cursor = page_number + 1

    next_state = dict(state)
    next_state.update(
        {
            "schema_version": SCHEMA_VERSION,
            "next_rotation_page": next_cursor,
        }
    )
    diagnostics = {
        "planned_pages": plan,
        "pages_scanned": len(page_summaries),
        "front_pages_configured": front_pages,
        "rotation_pages_configured": rotation_pages,
        "rotation_pages_scanned": rotation_pages_scanned,
        "rotation_start_page": cursor,
        "rotation_next_page": next_cursor,
        "rotation_boundary_detected": rotation_boundary,
        "rows_seen": sum(row["rows_seen"] for row in page_summaries),
        "unique_paid_sold_records": len(records),
        "blocked": dict(sorted(blocked.items())),
        "page_summaries": page_summaries,
    }
    return list(records.values()), diagnostics, next_state


def _prepare_records(
    records: Sequence[Mapping[str, Any]],
    *,
    observed_at: str,
) -> tuple[list[tuple[Any, Any]], dict[str, int]]:
    prepared: list[tuple[Any, Any]] = []
    blocked: Counter[str] = Counter()
    for record in records:
        built, reason = dry_run.build_p3_sale(record, observed_at=observed_at)
        if built is None:
            blocked[reason] += 1
            continue
        prepared.append(built)
    return prepared, dict(sorted(blocked.items()))


def safe_summary(*, commit: bool) -> dict[str, Any]:
    return {
        "mode": "RECURRING_LOCAL_CARDOVA_PAID_SOLD_P3_COLLECTOR",
        "public_anonymous_only": True,
        "fresh_browser_context": True,
        "front_plus_rotation_strategy": True,
        "unproven_sort_required": False,
        "provider_variant_fields_are_exact_identity": False,
        "durable_robot_kb_write": bool(commit),
        "local_postgres_only": True,
        "remote_cloud_write_allowed": False,
        "sale_event_semantics": "AUCTION_END_AT_UTC",
        "payment_completion_timestamp_fabricated": False,
        "price_component": "HAMMER_PRICE",
        "currency": "JPY",
        "canonical_identity_claimed": False,
        "commercial_microvariant_claimed": False,
        "exact_identity_eligible": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run(
    *,
    state_path: Path,
    commit: bool,
    database_url: str,
    front_pages: int,
    rotation_pages: int,
    page_size: int,
    wait_ms: int,
    fetch_page: Optional[Callable[[str], Mapping[str, Any]]] = None,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    state = load_state(state_path)
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    records, collection, next_state = collect_cycle(
        state,
        front_pages=front_pages,
        rotation_pages=rotation_pages,
        page_size=page_size,
        wait_ms=wait_ms,
        fetch_page=fetch_page,
    )
    prepared, prepare_blocked = _prepare_records(records, observed_at=observed)
    if prepare_blocked:
        raise RuntimeError(f"P3 preflight blocked collected paid rows: {prepare_blocked}")
    if len(prepared) != len(records):
        raise RuntimeError("P3 prepared count differs from collected paid-SOLD count")

    result: dict[str, Any] = {
        **collection,
        "prepared_sale_transactions": len(prepared),
        "state_advanced": False,
        "committed": False,
    }

    if not commit:
        memory = dry_run.run_memory_dry_run(
            records,
            max_records=max(1, len(records)) if records else 1,
            observed_at=observed,
            replay=True,
        ) if records else {
            "sale_transactions_stored_in_memory": 0,
            "unresolved_identity_sales": 0,
            "canonical_card_links": 0,
            "hammer_price_jpy_rows": 0,
            "sale_transactions_after_replay": 0,
            "duplicate_sale_replays": 0,
        }
        result.update(
            {
                "dry_run": True,
                "sale_transactions_stored_in_memory": int(memory.get("sale_transactions_stored_in_memory", 0)),
                "unresolved_identity_sales": int(memory.get("unresolved_identity_sales", 0)),
                "canonical_card_links": int(memory.get("canonical_card_links", 0)),
                "hammer_price_jpy_rows": int(memory.get("hammer_price_jpy_rows", 0)),
                "sale_transactions_after_replay": int(memory.get("sale_transactions_after_replay", 0)),
                "duplicate_sale_replays": int(memory.get("duplicate_sale_replays", 0)),
            }
        )
        return result

    target = durable_ingest.validate_local_database_url(database_url)
    result.update(target)
    if prepared:
        with KnowledgeBase.open(database_url) as kb:
            if kb.backend_name != "postgresql":
                raise RuntimeError("recurring Cardova SOLD collector requires PostgreSQL")
            durable = durable_ingest.ingest_prepared_batch(kb, prepared)
        result.update(durable)
    else:
        result.update(
            {
                "selected_before": {
                    "sale_transactions": 0,
                    "canonical_card_links": 0,
                    "hammer_price_jpy_rows": 0,
                },
                "selected_after": {
                    "sale_transactions": 0,
                    "canonical_card_links": 0,
                    "hammer_price_jpy_rows": 0,
                },
                "sale_transactions_stored": 0,
                "duplicate_sale_replays": 0,
                "unresolved_identities_retained": 0,
                "exact_identities_linked": 0,
                "observations_accepted": 0,
                "observations_replayed": 0,
            }
        )

    next_state["successful_cycles"] = int(state.get("successful_cycles", 0) or 0) + 1
    next_state["last_success_at"] = observed
    save_state(state_path, next_state)
    result.update(
        {
            "dry_run": False,
            "committed": True,
            "state_advanced": True,
            "successful_cycles": next_state["successful_cycles"],
        }
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Recurring local Cardova paid-SOLD collector")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--front-pages", type=int, default=DEFAULT_FRONT_PAGES)
    parser.add_argument("--rotation-pages", type=int, default=DEFAULT_ROTATION_PAGES)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="persist proven paid/completed sales to the guarded local PostgreSQL KB and advance rotation state",
    )
    args = parser.parse_args(argv)

    summary = safe_summary(commit=args.commit)
    code = 1
    try:
        if args.front_pages < 1 or args.rotation_pages < 1:
            raise ValueError("front/rotation pages must be >= 1")
        if args.front_pages + args.rotation_pages > HARD_MAX_PAGES_PER_RUN:
            raise ValueError(f"front+rotation page slots must be <= {HARD_MAX_PAGES_PER_RUN}")
        if not 1 <= args.page_size <= HARD_MAX_PAGE_SIZE:
            raise ValueError(f"page size must be 1..{HARD_MAX_PAGE_SIZE}")
        if not 500 <= args.wait_ms <= 8000:
            raise ValueError("wait-ms must be 500..8000")
        database_url = os.getenv("ROBOT_KB_DATABASE_URL", "").strip() if args.commit else ""
        summary.update(
            run(
                state_path=args.state,
                commit=args.commit,
                database_url=database_url,
                front_pages=args.front_pages,
                rotation_pages=args.rotation_pages,
                page_size=args.page_size,
                wait_ms=args.wait_ms,
            )
        )
        summary["error"] = None
        code = 0
    except Exception as error:
        summary["committed"] = False
        summary["state_advanced"] = False
        summary["error"] = f"{type(error).__name__}: {error}"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
