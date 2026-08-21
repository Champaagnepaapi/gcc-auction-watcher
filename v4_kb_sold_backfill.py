"""Historical GCC SOLD backfill for Robot KB.

This lane is deliberately separate from the fresh high-watermark collector.  It walks
backward from a fixed bootstrap timestamp and only emits rows that satisfy the same
strict final-sale contract used by the fresh collector: ``status=SOLD`` + a
timezone-aware ``soldAt`` + a final price.

Durable state is advanced only by the separate ``commit`` command after the Neon
sidecar ingest succeeds.  The collector is GET-only and never bids, buys, checks out,
or changes a GCC listing.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import requests


GCC_API_URL = "https://api.gradedcardcenter.com/on-sale-items"
STATE_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_RECORDS = 400
DEFAULT_MAX_PAGE_PROBES = 40
DEFAULT_MAX_SCAN_PAGES = 20
MAX_CURSOR_IDS = 10_000
DEFERRED_NONFINAL_STATUSES = frozenset({"WAITING_FOR_PAYMENT"})


class SoldBackfillError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def _aware(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SoldBackfillError(f"{field} must be a timezone-aware timestamp")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise SoldBackfillError(f"invalid {field}: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SoldBackfillError(f"{field} must be timezone-aware: {text}")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any, *, field: str) -> str:
    return _aware(value, field=field).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _row_id(row: Mapping[str, Any]) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not value.strip():
        raise SoldBackfillError("SOLD row missing stable id")
    return value.strip()


def _row_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "").strip().upper()


def _is_deferred_nonfinal(row: Mapping[str, Any]) -> bool:
    status = _row_status(row)
    if status in DEFERRED_NONFINAL_STATUSES:
        # GCC can leak WAITING_FOR_PAYMENT rows into status=SOLD.  The fresh
        # watermark lane owns their eventual finalization and keeps its cursor
        # blocked; historical backfill must neither ingest them nor let them
        # break page-boundary discovery.
        _row_id(row)
        return True
    if status != "SOLD":
        raise SoldBackfillError(f"historical SOLD scope returned {status or 'EMPTY'}")
    return False


def _validate_row(row: Mapping[str, Any]) -> tuple[str, str, datetime]:
    if _is_deferred_nonfinal(row):
        raise SoldBackfillError("deferred non-final row cannot be validated as SOLD")
    native_id = _row_id(row)
    sold_at_text = _canonical(row.get("soldAt"), field="soldAt")
    sold_at = _aware(sold_at_text, field="soldAt")
    cents = row.get("priceInCents")
    price = row.get("price")
    cents_ok = isinstance(cents, int) and not isinstance(cents, bool) and cents >= 0
    price_ok = isinstance(price, (int, float)) and not isinstance(price, bool) and price >= 0
    if not (cents_ok or price_ok):
        raise SoldBackfillError(f"SOLD row {native_id} has no final price")
    return native_id, sold_at_text, sold_at


def _new_state(bootstrap_before: str) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "cursor_sold_at": _canonical(bootstrap_before, field="bootstrap_before"),
        "cursor_seen_ids": [],
        "cursor_is_exclusive": True,
        "complete": False,
        "updated_at": None,
    }


def _validated_state(raw: Any, *, bootstrap_before: str) -> dict[str, Any]:
    if raw is None:
        return _new_state(bootstrap_before)
    if not isinstance(raw, Mapping) or raw.get("schema_version") != STATE_SCHEMA_VERSION:
        raise SoldBackfillError("invalid SOLD backfill state schema")
    cursor = _canonical(raw.get("cursor_sold_at"), field="cursor_sold_at")
    ids = raw.get("cursor_seen_ids")
    if not isinstance(ids, list):
        raise SoldBackfillError("cursor_seen_ids must be a list")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in ids:
        if not isinstance(item, str) or not item.strip():
            raise SoldBackfillError("cursor_seen_ids contains an invalid id")
        value = item.strip()
        if value not in seen:
            seen.add(value)
            cleaned.append(value)
    if len(cleaned) > MAX_CURSOR_IDS:
        raise SoldBackfillError("cursor_seen_ids safety ceiling exceeded")
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "cursor_sold_at": cursor,
        "cursor_seen_ids": cleaned,
        "cursor_is_exclusive": bool(raw.get("cursor_is_exclusive", False)),
        "complete": bool(raw.get("complete", False)),
        "updated_at": raw.get("updated_at"),
    }


def _fetch_page(
    page: int,
    page_size: int,
    *,
    get_fn: Callable[..., Any],
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], Optional[int]]:
    params = {
        "sellingTypeGroup": "AUCTION",
        "status": "SOLD",
        "sortType": "MOST_RECENT",
        "page": page,
        "limit": page_size,
        "includeCounts": "false",
    }
    try:
        response = get_fn(
            GCC_API_URL,
            params=params,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise SoldBackfillError(f"HTTP request failed for SOLD page {page}: {exc}") from exc
    if getattr(response, "status_code", None) != 200:
        raise SoldBackfillError(f"HTTP {getattr(response, 'status_code', 'unknown')} fetching SOLD page {page}")
    try:
        payload = response.json()
    except Exception as exc:
        raise SoldBackfillError(f"malformed SOLD JSON page {page}") from exc
    if not isinstance(payload, Mapping):
        raise SoldBackfillError(f"SOLD page {page} is not an object")
    info, results = payload.get("info"), payload.get("results")
    if not isinstance(info, Mapping) or not isinstance(results, list):
        raise SoldBackfillError(f"SOLD page {page} lacks info/results")
    if info.get("currentPage") != page:
        raise SoldBackfillError(f"SOLD page mismatch: requested {page}, received {info.get('currentPage')}")
    rows: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, Mapping):
            raise SoldBackfillError(f"SOLD page {page} contains a non-object row")
        row = dict(raw)
        if not _is_deferred_nonfinal(row):
            _validate_row(row)
        rows.append(row)
    next_page = info.get("nextPage")
    if next_page is not None and (
        isinstance(next_page, bool) or not isinstance(next_page, int) or next_page <= page
    ):
        raise SoldBackfillError(f"invalid nextPage on SOLD page {page}")
    return rows, next_page


def _page_bounds(rows: list[dict[str, Any]]) -> tuple[Optional[datetime], Optional[datetime]]:
    if not rows:
        return None, None
    dates: list[datetime] = []
    for row in rows:
        if _is_deferred_nonfinal(row):
            continue
        dates.append(_validate_row(row)[2])
    if not dates:
        return None, None
    return max(dates), min(dates)


def _find_boundary_page(
    cursor: datetime,
    page_size: int,
    *,
    get_fn: Callable[..., Any],
    timeout_seconds: float,
    max_page_probes: int,
) -> tuple[int, dict[int, tuple[list[dict[str, Any]], Optional[int]]], bool]:
    """Find a page at/just before the cursor with logarithmic probing."""
    cache: dict[int, tuple[list[dict[str, Any]], Optional[int]]] = {}
    probes = 0

    def load(page: int):
        nonlocal probes
        if page not in cache:
            if probes >= max_page_probes:
                raise SoldBackfillError("historical SOLD page-probe safety ceiling reached")
            cache[page] = _fetch_page(
                page, page_size, get_fn=get_fn, timeout_seconds=timeout_seconds
            )
            probes += 1
        return cache[page]

    rows1, next1 = load(1)
    if not rows1:
        return 1, cache, True
    _, oldest1 = _page_bounds(rows1)
    if oldest1 is not None and oldest1 <= cursor:
        return 1, cache, next1 is None

    low = 1
    high = 2
    exhausted = False
    while True:
        rows, next_page = load(high)
        if not rows:
            exhausted = True
            break
        _, oldest = _page_bounds(rows)
        if oldest is not None and oldest <= cursor:
            break
        if next_page is None:
            exhausted = True
            break
        low = high
        high *= 2

    # If exponential probing stepped beyond the API, narrow to the last existing page.
    if not cache.get(high, ([], None))[0]:
        while high - low > 1:
            mid = (low + high) // 2
            rows, _ = load(mid)
            if rows:
                low = mid
            else:
                high = mid
        return max(1, low - 1), cache, True

    # Find the first page whose oldest timestamp reaches/passes the cursor.
    while high - low > 1:
        mid = (low + high) // 2
        rows, _ = load(mid)
        if not rows:
            high = mid
            continue
        _, oldest = _page_bounds(rows)
        if oldest is not None and oldest <= cursor:
            high = mid
        else:
            low = mid
    return max(1, high - 1), cache, exhausted


def fetch_sold_backfill_batch(
    state_path: Path,
    output_fixture_path: Path,
    manifest_path: Path,
    *,
    bootstrap_before: str,
    max_records: int = DEFAULT_MAX_RECORDS,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_page_probes: int = DEFAULT_MAX_PAGE_PROBES,
    max_scan_pages: int = DEFAULT_MAX_SCAN_PAGES,
    http_get: Optional[Callable[..., Any]] = None,
    clock: Callable[[], str] = utc_now,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    if max_records <= 0:
        raise SoldBackfillError("max_records must be positive")
    if page_size <= 0 or page_size > 100:
        raise SoldBackfillError("page_size must be 1..100")
    if max_page_probes <= 0 or max_scan_pages <= 0:
        raise SoldBackfillError("page safety limits must be positive")

    if state_path.exists():
        try:
            raw_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SoldBackfillError("existing SOLD backfill state is corrupt") from exc
    else:
        raw_state = None
    state = _validated_state(raw_state, bootstrap_before=bootstrap_before)
    retrieved_at = clock()
    if state["complete"]:
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "retrieved_at": retrieved_at,
            "records_count": 0,
            "pages_scanned": 0,
            "complete": True,
            "next_state": state,
        }
        _atomic_json(output_fixture_path, [])
        _atomic_json(manifest_path, manifest)
        return manifest

    cursor_text = state["cursor_sold_at"]
    cursor = _aware(cursor_text, field="cursor_sold_at")
    cursor_ids = set(state["cursor_seen_ids"])
    exclusive = bool(state["cursor_is_exclusive"])
    get_fn = http_get or requests.get

    start_page, page_cache, exhausted_hint = _find_boundary_page(
        cursor,
        page_size,
        get_fn=get_fn,
        timeout_seconds=timeout_seconds,
        max_page_probes=max_page_probes,
    )

    rows_out: list[dict[str, Any]] = []
    emitted: set[str] = set()
    deferred_nonfinal_ids: set[str] = set()
    deferred_nonfinal_status_counts: dict[str, int] = {}
    pages_scanned = 0
    api_exhausted = False
    page = start_page
    while pages_scanned < max_scan_pages and len(rows_out) < max_records:
        if page in page_cache:
            rows, next_page = page_cache[page]
        else:
            rows, next_page = _fetch_page(
                page, page_size, get_fn=get_fn, timeout_seconds=timeout_seconds
            )
        pages_scanned += 1
        if not rows:
            api_exhausted = True
            break
        for row in rows:
            if _is_deferred_nonfinal(row):
                native_id = _row_id(row)
                deferred_nonfinal_ids.add(native_id)
                status = _row_status(row)
                deferred_nonfinal_status_counts[status] = (
                    deferred_nonfinal_status_counts.get(status, 0) + 1
                )
                continue
            native_id, _, sold_at = _validate_row(row)
            eligible = sold_at < cursor or (
                sold_at == cursor and not exclusive and native_id not in cursor_ids
            )
            if not eligible or native_id in emitted:
                continue
            rows_out.append(row)
            emitted.add(native_id)
            if len(rows_out) >= max_records:
                break
        if len(rows_out) >= max_records:
            break
        if next_page is None:
            api_exhausted = True
            break
        page = next_page

    if not rows_out and not api_exhausted and pages_scanned >= max_scan_pages:
        raise SoldBackfillError("historical SOLD scan ceiling reached without progress")

    if rows_out:
        dated = [(_validate_row(row)[2], _validate_row(row)[0]) for row in rows_out]
        oldest = min(dt for dt, _ in dated)
        oldest_text = oldest.isoformat(timespec="microseconds").replace("+00:00", "Z")
        oldest_ids = sorted(native_id for dt, native_id in dated if dt == oldest)
        if oldest == cursor and not exclusive:
            oldest_ids = sorted(cursor_ids | set(oldest_ids))
        next_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "cursor_sold_at": oldest_text,
            "cursor_seen_ids": oldest_ids,
            "cursor_is_exclusive": False,
            "complete": False,
            "updated_at": retrieved_at,
        }
    else:
        next_state = dict(state)
        next_state["updated_at"] = retrieved_at

    # We can declare completion only after reaching the actual API tail.
    if api_exhausted and len(rows_out) < max_records:
        next_state["complete"] = True

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "retrieved_at": retrieved_at,
        "records_count": len(rows_out),
        "pages_scanned": pages_scanned,
        "start_page": start_page,
        "api_exhausted": api_exhausted or exhausted_hint and not rows_out,
        "complete": bool(next_state["complete"]),
        "cursor_before": cursor_text,
        "cursor_after": next_state["cursor_sold_at"],
        "deferred_nonfinal_rows": len(deferred_nonfinal_ids),
        "deferred_nonfinal_status_counts": dict(sorted(deferred_nonfinal_status_counts.items())),
        "next_state": next_state,
    }
    _atomic_json(output_fixture_path, rows_out)
    _atomic_json(manifest_path, manifest)
    return manifest


def commit_sold_backfill(state_path: Path, manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise SoldBackfillError("missing SOLD backfill manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SoldBackfillError("SOLD backfill manifest is corrupt") from exc
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise SoldBackfillError("invalid SOLD backfill manifest")
    next_state = manifest.get("next_state")
    if not isinstance(next_state, Mapping):
        raise SoldBackfillError("SOLD backfill manifest lacks next_state")
    state = _validated_state(dict(next_state), bootstrap_before=str(next_state.get("cursor_sold_at") or ""))
    _atomic_json(state_path, state)
    return state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--state", type=Path, required=True)
    fetch.add_argument("--output-fixture", type=Path, required=True)
    fetch.add_argument("--manifest", type=Path, required=True)
    fetch.add_argument("--bootstrap-before", required=True)
    fetch.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    fetch.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    fetch.add_argument("--max-page-probes", type=int, default=DEFAULT_MAX_PAGE_PROBES)
    fetch.add_argument("--max-scan-pages", type=int, default=DEFAULT_MAX_SCAN_PAGES)
    commit = sub.add_parser("commit")
    commit.add_argument("--state", type=Path, required=True)
    commit.add_argument("--manifest", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "fetch":
        result = fetch_sold_backfill_batch(
            args.state,
            args.output_fixture,
            args.manifest,
            bootstrap_before=args.bootstrap_before,
            max_records=args.max_records,
            page_size=args.page_size,
            max_page_probes=args.max_page_probes,
            max_scan_pages=args.max_scan_pages,
        )
    else:
        result = commit_sold_backfill(args.state, args.manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
