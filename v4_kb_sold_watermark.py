"""Lossless-ish GCC SOLD catch-up collector for the Robot KB cloud shadow.

The collector keeps a durable high-watermark plus the IDs already ingested while a
backlog is being drained. Every run restarts from the newest SOLD page, skips IDs
already processed in the pending window, and keeps walking backward until it
reaches the previously committed soldAt watermark.

State is only committed by the separate ``commit`` command after the downstream
Neon sidecar ingest succeeds.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import requests


GCC_API_URL = "https://api.gradedcardcenter.com/on-sale-items"
STATE_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_RECORDS = 400
DEFAULT_MAX_SCAN_PAGES = 200
MAX_PENDING_IDS = 50_000
DEFERRED_NONFINAL_STATUSES = frozenset({"WAITING_FOR_PAYMENT"})


class SoldWatermarkError(RuntimeError):
    """Raised when SOLD collection or state validation fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _parse_aware_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SoldWatermarkError(f"{field} must be a non-empty timezone-aware timestamp")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise SoldWatermarkError(f"{field} is not a valid ISO timestamp: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SoldWatermarkError(f"{field} must be timezone-aware: {text}")
    return parsed.astimezone(timezone.utc)


def _canonical_timestamp(value: Any, *, field: str) -> str:
    return _parse_aware_timestamp(value, field=field).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _row_id(row: Mapping[str, Any]) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not value.strip():
        raise SoldWatermarkError("GCC SOLD row is missing a stable id")
    return value.strip()


def _row_sold_at(row: Mapping[str, Any]) -> tuple[str, datetime]:
    canonical = _canonical_timestamp(row.get("soldAt"), field="soldAt")
    return canonical, _parse_aware_timestamp(canonical, field="soldAt")


def _row_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "").strip().upper()


def _has_final_price(row: Mapping[str, Any]) -> bool:
    cents = row.get("priceInCents")
    if isinstance(cents, bool):
        cents = None
    if isinstance(cents, int) and cents >= 0:
        return True
    price = row.get("price")
    if isinstance(price, bool):
        return False
    return isinstance(price, (int, float)) and price >= 0


def _validate_sold_row(row: Mapping[str, Any]) -> tuple[str, str, datetime]:
    status = _row_status(row)
    if status != "SOLD":
        raise SoldWatermarkError(f"GCC SOLD scope returned non-SOLD row: {status or 'EMPTY'}")
    native_id = _row_id(row)
    sold_at_text, sold_at = _row_sold_at(row)
    if not _has_final_price(row):
        raise SoldWatermarkError(f"GCC SOLD row {native_id} lacks final price")
    return native_id, sold_at_text, sold_at


def _new_state_from_bootstrap(bootstrap_since: str) -> dict[str, Any]:
    canonical = _canonical_timestamp(bootstrap_since, field="bootstrap_since")
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "committed_watermark_sold_at": canonical,
        "committed_watermark_ids": [],
        "pending_seen_ids": [],
        "pending_target_watermark_sold_at": None,
        "pending_target_watermark_ids": [],
        "updated_at": None,
    }


def _validated_state(raw: Any, *, bootstrap_since: str) -> dict[str, Any]:
    if raw is None:
        return _new_state_from_bootstrap(bootstrap_since)
    if not isinstance(raw, Mapping):
        raise SoldWatermarkError("SOLD state must be a JSON object")
    if raw.get("schema_version") != STATE_SCHEMA_VERSION:
        raise SoldWatermarkError(
            f"Unsupported SOLD state schema: {raw.get('schema_version')}"
        )

    committed = _canonical_timestamp(
        raw.get("committed_watermark_sold_at"), field="committed_watermark_sold_at"
    )

    def _ids(name: str) -> list[str]:
        value = raw.get(name)
        if not isinstance(value, list):
            raise SoldWatermarkError(f"{name} must be a list")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise SoldWatermarkError(f"{name} contains an invalid id")
            item = item.strip()
            if item not in seen:
                seen.add(item)
                cleaned.append(item)
        return cleaned

    pending_target = raw.get("pending_target_watermark_sold_at")
    if pending_target is not None:
        pending_target = _canonical_timestamp(
            pending_target, field="pending_target_watermark_sold_at"
        )

    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "committed_watermark_sold_at": committed,
        "committed_watermark_ids": _ids("committed_watermark_ids"),
        "pending_seen_ids": _ids("pending_seen_ids"),
        "pending_target_watermark_sold_at": pending_target,
        "pending_target_watermark_ids": _ids("pending_target_watermark_ids"),
        "updated_at": raw.get("updated_at"),
    }
    if len(state["pending_seen_ids"]) > MAX_PENDING_IDS:
        raise SoldWatermarkError(
            f"pending_seen_ids exceeds safety ceiling ({MAX_PENDING_IDS})"
        )
    return state


def fetch_sold_catchup_batch(
    state_path: Path,
    output_fixture_path: Path,
    manifest_path: Path,
    *,
    bootstrap_since: str,
    max_records: int = DEFAULT_MAX_RECORDS,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_scan_pages: int = DEFAULT_MAX_SCAN_PAGES,
    http_get: Optional[Callable[..., Any]] = None,
    clock: Callable[[], str] = utc_now,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Fetch the next lossless SOLD catch-up slice without mutating durable state."""
    if max_records <= 0:
        raise SoldWatermarkError("max_records must be strictly positive")
    if page_size <= 0 or page_size > 100:
        raise SoldWatermarkError("page_size must be between 1 and 100")
    if max_scan_pages <= 0:
        raise SoldWatermarkError("max_scan_pages must be strictly positive")

    if state_path.exists():
        try:
            raw_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SoldWatermarkError("Existing SOLD state is unreadable/corrupt") from exc
    else:
        raw_state = None
    state = _validated_state(raw_state, bootstrap_since=bootstrap_since)

    base_text = state["committed_watermark_sold_at"]
    base_dt = _parse_aware_timestamp(base_text, field="committed_watermark_sold_at")
    base_ids = set(state["committed_watermark_ids"])
    pending_seen = set(state["pending_seen_ids"])
    pending_target_text = state["pending_target_watermark_sold_at"]
    pending_target_ids = set(state["pending_target_watermark_ids"])
    pending_target_dt = (
        _parse_aware_timestamp(
            pending_target_text, field="pending_target_watermark_sold_at"
        )
        if pending_target_text
        else base_dt
    )
    if pending_target_text is None:
        pending_target_text = base_text
        pending_target_ids = set(base_ids)

    # A pending backlog can require scanning through IDs already ingested on prior runs.
    # Grow the scan allowance with the pending prefix, while preserving a hard ceiling.
    minimum_needed = math.ceil((len(pending_seen) + max_records) / page_size) + 5
    effective_max_scan_pages = min(
        max_scan_pages, max(5, minimum_needed)
    )

    get_fn = http_get or requests.get
    retrieved_at = clock()
    rows_to_ingest: list[dict[str, Any]] = []
    collected_ids: set[str] = set()
    seen_this_scan: set[str] = set()
    deferred_nonfinal_ids: set[str] = set()
    deferred_nonfinal_unknown_time_ids: set[str] = set()
    deferred_nonfinal_status_counts: dict[str, int] = {}
    pages_scanned = 0
    caught_up = False
    cap_reached = False
    api_exhausted = False
    last_page = 0

    page = 1
    while pages_scanned < effective_max_scan_pages:
        params: dict[str, Any] = {
            "sellingTypeGroup": "AUCTION",
            "status": "SOLD",
            "sortType": "MOST_RECENT",
            "page": page,
            "limit": page_size,
            "includeCounts": "true" if page == 1 else "false",
        }
        try:
            response = get_fn(
                GCC_API_URL,
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=timeout_seconds,
            )
        except Exception as exc:
            raise SoldWatermarkError(f"HTTP request failed for SOLD page {page}: {exc}") from exc

        if getattr(response, "status_code", None) != 200:
            status = getattr(response, "status_code", "unknown")
            raise SoldWatermarkError(f"HTTP {status} fetching SOLD page {page}")

        try:
            payload = response.json()
        except Exception as exc:
            raise SoldWatermarkError(f"Malformed JSON on SOLD page {page}: {exc}") from exc

        if not isinstance(payload, Mapping):
            raise SoldWatermarkError(f"SOLD page {page} payload is not a JSON object")
        info = payload.get("info")
        results = payload.get("results")
        if not isinstance(info, Mapping) or not isinstance(results, list):
            raise SoldWatermarkError(f"SOLD page {page} lacks info or results list")
        if info.get("currentPage") != page:
            raise SoldWatermarkError(
                f"SOLD page mismatch: requested {page}, received {info.get('currentPage')}"
            )

        pages_scanned += 1
        last_page = page

        if not results:
            api_exhausted = True
            caught_up = True
            break

        stop_page = False
        for raw_row in results:
            if not isinstance(raw_row, Mapping):
                raise SoldWatermarkError(f"SOLD page {page} contains a non-object row")
            row = dict(raw_row)
            status = _row_status(row)

            if status in DEFERRED_NONFINAL_STATUSES:
                native_id = _row_id(row)
                if native_id in seen_this_scan:
                    continue
                seen_this_scan.add(native_id)

                sold_at_value = row.get("soldAt")
                if isinstance(sold_at_value, str) and sold_at_value.strip():
                    try:
                        _, sold_at_dt = _row_sold_at(row)
                    except SoldWatermarkError:
                        deferred_nonfinal_unknown_time_ids.add(native_id)
                    else:
                        if sold_at_dt < base_dt:
                            caught_up = True
                            stop_page = True
                            break
                else:
                    deferred_nonfinal_unknown_time_ids.add(native_id)

                deferred_nonfinal_ids.add(native_id)
                deferred_nonfinal_status_counts[status] = (
                    deferred_nonfinal_status_counts.get(status, 0) + 1
                )
                continue

            native_id, sold_at_text, sold_at_dt = _validate_sold_row(row)

            if native_id in seen_this_scan:
                continue
            seen_this_scan.add(native_id)

            # Track the newest final sale timestamp/IDs observed while this backlog is open.
            if sold_at_dt > pending_target_dt:
                pending_target_dt = sold_at_dt
                pending_target_text = sold_at_text
                pending_target_ids = {native_id}
            elif sold_at_dt == pending_target_dt:
                pending_target_ids.add(native_id)

            if sold_at_dt < base_dt:
                caught_up = True
                stop_page = True
                break

            if sold_at_dt == base_dt and native_id in base_ids:
                # Same-timestamp rows already part of the committed boundary are covered.
                continue

            if native_id in pending_seen or native_id in collected_ids:
                continue

            rows_to_ingest.append(row)
            collected_ids.add(native_id)
            if len(rows_to_ingest) >= max_records:
                cap_reached = True
                stop_page = True
                break

        if stop_page:
            break

        next_page = info.get("nextPage")
        if next_page is None:
            api_exhausted = True
            caught_up = True
            break
        if (
            isinstance(next_page, bool)
            or not isinstance(next_page, int)
            or next_page <= page
        ):
            raise SoldWatermarkError(f"GCC SOLD nextPage is invalid on page {page}")
        page = next_page

    scan_limit_reached = (
        not caught_up and not cap_reached and not api_exhausted and pages_scanned >= effective_max_scan_pages
    )
    if scan_limit_reached:
        raise SoldWatermarkError(
            "SOLD scan safety ceiling reached before cap or committed watermark; "
            "raise --max-scan-pages to preserve lossless catch-up"
        )

    watermark_blocked_by_nonfinal = bool(deferred_nonfinal_ids)
    caught_up = caught_up and not watermark_blocked_by_nonfinal

    next_pending_seen = pending_seen | collected_ids
    if len(next_pending_seen) > MAX_PENDING_IDS:
        raise SoldWatermarkError(
            f"pending SOLD backlog exceeds safety ceiling ({MAX_PENDING_IDS} IDs)"
        )

    if caught_up:
        next_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "committed_watermark_sold_at": pending_target_text,
            "committed_watermark_ids": sorted(pending_target_ids),
            "pending_seen_ids": [],
            "pending_target_watermark_sold_at": None,
            "pending_target_watermark_ids": [],
            "updated_at": retrieved_at,
        }
    else:
        next_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "committed_watermark_sold_at": base_text,
            "committed_watermark_ids": sorted(base_ids),
            "pending_seen_ids": sorted(next_pending_seen),
            "pending_target_watermark_sold_at": pending_target_text,
            "pending_target_watermark_ids": sorted(pending_target_ids),
            "updated_at": retrieved_at,
        }

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "retrieved_at": retrieved_at,
        "records_count": len(rows_to_ingest),
        "pages_scanned": pages_scanned,
        "last_page": last_page,
        "cap_reached": cap_reached,
        "caught_up": caught_up,
        "api_exhausted": api_exhausted,
        "deferred_nonfinal_rows": len(deferred_nonfinal_ids),
        "deferred_nonfinal_unknown_time_rows": len(deferred_nonfinal_unknown_time_ids),
        "deferred_nonfinal_status_counts": dict(sorted(deferred_nonfinal_status_counts.items())),
        "watermark_blocked_by_nonfinal": watermark_blocked_by_nonfinal,
        "base_watermark_sold_at": base_text,
        "next_committed_watermark_sold_at": next_state["committed_watermark_sold_at"],
        "pending_ids_after_commit": len(next_state["pending_seen_ids"]),
        "next_state": next_state,
    }
    _atomic_json(output_fixture_path, rows_to_ingest)
    _atomic_json(manifest_path, manifest)
    return manifest


def commit_sold_watermark(
    state_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Commit the manifest-produced SOLD state after successful Neon ingest."""
    if not manifest_path.exists():
        raise SoldWatermarkError("Missing SOLD manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SoldWatermarkError("SOLD manifest is unreadable/corrupt") from exc
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise SoldWatermarkError("Invalid SOLD manifest")
    next_state = manifest.get("next_state")
    if not isinstance(next_state, Mapping):
        raise SoldWatermarkError("SOLD manifest lacks next_state")
    state = _validated_state(
        dict(next_state),
        bootstrap_since=str(next_state.get("committed_watermark_sold_at") or ""),
    )
    _atomic_json(state_path, state)
    return state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Durable lossless GCC SOLD watermark/backlog collector for Robot KB"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rotate = sub.add_parser("rotate", help="Fetch next SOLD catch-up slice")
    rotate.add_argument("--state", required=True, help="Path to SOLD state JSON")
    rotate.add_argument("--output-fixture", required=True, help="Path to SOLD fixture JSON")
    rotate.add_argument("--manifest", required=True, help="Path to SOLD manifest JSON")
    rotate.add_argument(
        "--bootstrap-since",
        required=True,
        help="Initial committed soldAt watermark used only when state is absent",
    )
    rotate.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    rotate.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    rotate.add_argument("--max-scan-pages", type=int, default=DEFAULT_MAX_SCAN_PAGES)

    commit = sub.add_parser("commit", help="Commit SOLD state after successful Neon ingest")
    commit.add_argument("--state", required=True, help="Path to SOLD state JSON")
    commit.add_argument("--manifest", required=True, help="Path to SOLD manifest JSON")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "rotate":
        manifest = fetch_sold_catchup_batch(
            Path(args.state),
            Path(args.output_fixture),
            Path(args.manifest),
            bootstrap_since=args.bootstrap_since,
            max_records=args.max_records,
            page_size=args.page_size,
            max_scan_pages=args.max_scan_pages,
        )
        print(
            "SOLD CATCH-UP: "
            f"records={manifest['records_count']} pages={manifest['pages_scanned']} "
            f"caught_up={manifest['caught_up']} cap_reached={manifest['cap_reached']} "
            f"deferred_nonfinal={manifest['deferred_nonfinal_rows']} "
            f"pending_after_commit={manifest['pending_ids_after_commit']}"
        )
        return 0
    if args.command == "commit":
        state = commit_sold_watermark(Path(args.state), Path(args.manifest))
        print(
            "SOLD WATERMARK COMMITTED: "
            f"soldAt={state['committed_watermark_sold_at']} "
            f"pending={len(state['pending_seen_ids'])}"
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())