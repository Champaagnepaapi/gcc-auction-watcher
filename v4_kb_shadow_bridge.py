from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import requests

import watcher


SPOOL_SCHEMA_VERSION = 2
STATE_SCHEMA_VERSION = 2
ROTATION_SCHEMA_VERSION = 1
DEFAULT_NEAR_FINAL_MINUTES = 12
GCC_API_URL = watcher.GCC_ON_SALE_ITEMS_API_URL
GCC_MAX_TIMEOUT_SECONDS = 30.0
GCC_MIN_REQUEST_INTERVAL_SECONDS = 0.25
GCC_MAX_RETRIES = 2


@dataclass(frozen=True)
class CapturedRow:
    payload: dict[str, Any]
    retrieved_at: str


_FIXED_ROWS: dict[str, CapturedRow] = {}
_AUCTION_ROWS: dict[str, CapturedRow] = {}
_INSTALLED = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _aware_datetime(value: str) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _stable_id(row: Mapping[str, Any]) -> Optional[str]:
    value = row.get("id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


class CapturingGccHttpGet:
    """Transparent GET wrapper; capture failures never alter V4 network behavior."""

    def __init__(self, delegate: Callable[..., Any], *, clock: Callable[[], str] = _utc_now) -> None:
        self.delegate = delegate
        self.clock = clock

    def __call__(self, url: Any, *args: Any, **kwargs: Any) -> Any:
        response = self.delegate(url, *args, **kwargs)
        try:
            if str(url).rstrip("/") != GCC_API_URL.rstrip("/"):
                return response
            params = kwargs.get("params") or {}
            if not isinstance(params, Mapping):
                return response
            payload = response.json()
            results = payload.get("results") if isinstance(payload, Mapping) else None
            if not isinstance(results, list):
                return response
            if str(params.get("sellingTypes") or "").upper() == "FIXED_PRICE":
                target = _FIXED_ROWS
            elif str(params.get("sellingTypeGroup") or "").upper() == "AUCTION":
                target = _AUCTION_ROWS
            else:
                return response
            retrieved_at = self.clock()
            for row in results:
                if not isinstance(row, Mapping):
                    continue
                native_id = _stable_id(row)
                if native_id is None:
                    continue
                target[native_id] = CapturedRow(_json_copy(row), retrieved_at)
        except Exception:
            # Shadow capture is deliberately fail-open relative to production V4.
            pass
        return response


def install_v4_kb_shadow_capture() -> None:
    """Observe existing V4 GCC API calls without adding provider/network calls."""

    global _INSTALLED
    if _INSTALLED:
        return

    import v4_auction_item_discovery as auction_discovery

    capture_get = CapturingGccHttpGet(watcher.requests.get)
    original_collect = watcher.collect_lots_from_listing
    original_auction_discover = auction_discovery.discover_auction_api_lots

    def collect_with_capture(page: Any, url: Any, source_type: Any, run_diagnostics: Any = None, **kwargs: Any) -> Any:
        if source_type == "fixed" and kwargs.get("fixed_http_get") is None:
            kwargs["fixed_http_get"] = capture_get
        return original_collect(page, url, source_type, run_diagnostics, **kwargs)

    def auction_discover_with_capture(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("http_get") is None:
            kwargs["http_get"] = capture_get
        return original_auction_discover(*args, **kwargs)

    watcher.collect_lots_from_listing = collect_with_capture
    auction_discovery.discover_auction_api_lots = auction_discover_with_capture
    _INSTALLED = True


def is_proven_gcc_sold(row: Mapping[str, Any]) -> bool:
    """Determine whether a GCC payload represents an unambiguous completed sale.

    Preserves the P1/P3 contract:
    - Status must be explicitly SOLD (never COMPLETED, WAITING_FOR_PAYMENT, etc.).
    - soldAt (or saleOccurredAt) must be present and parse to a valid timezone-aware timestamp.
    - price (or priceInCents/soldPrice/soldPriceInCents) must be strictly positive.
    - If category is given, must be Pokemon.
    """
    if not isinstance(row, Mapping):
        return False
    status = str(row.get("status") or "").strip().upper()
    if status != "SOLD":
        return False
    sold_at = row.get("soldAt") or row.get("saleOccurredAt")
    if not isinstance(sold_at, str) or not sold_at.strip():
        return False
    if _aware_datetime(sold_at) is None:
        return False
    price_cents = row.get("priceInCents") or row.get("soldPriceInCents")
    price_major = row.get("price") or row.get("soldPrice")
    has_valid_price = False
    if isinstance(price_cents, (int, float)) and price_cents > 0:
        has_valid_price = True
    elif isinstance(price_major, (int, float)) and price_major > 0:
        has_valid_price = True
    elif isinstance(price_cents, str) and price_cents.strip().isdigit() and int(price_cents.strip()) > 0:
        has_valid_price = True
    elif isinstance(price_major, str) and price_major.strip():
        try:
            if float(price_major.strip()) > 0:
                has_valid_price = True
        except ValueError:
            pass
    if not has_valid_price:
        return False
    item = row.get("item") if isinstance(row.get("item"), Mapping) else {}
    collectible = item.get("collectible") if isinstance(item.get("collectible"), Mapping) else {}
    cat = str(collectible.get("category") or "").strip().lower()
    if cat and cat != "pokemon":
        return False
    return True


def _minutes_to_end(row: Mapping[str, Any], observed_at: str) -> Optional[int]:
    end_value = row.get("endTime") or row.get("auctionEndTime")
    end_at = _aware_datetime(str(end_value or ""))
    observed = _aware_datetime(observed_at)
    if end_at is None or observed is None:
        return None
    seconds = (end_at - observed).total_seconds()
    if seconds < 0:
        return None
    return int(math.ceil(seconds / 60.0))


def _auction_row_is_v4_eligible(row: Mapping[str, Any]) -> bool:
    native_id = _stable_id(row)
    if native_id is None:
        return False
    coverage = watcher.CoverageAudit("KB AUCTION", ())
    lot = watcher._gcc_fixed_result_to_lot(
        dict(row),
        f"{watcher.BASE}/item/{native_id}",
        coverage,
        min_price=watcher.MIN_PRICE,
        max_price=watcher.MAX_PRICE,
    )
    return lot is not None


def _near_final_limit() -> int:
    raw = os.getenv("V4_KB_AUCTION_NEAR_FINAL_MINUTES", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_NEAR_FINAL_MINUTES
    except ValueError:
        value = DEFAULT_NEAR_FINAL_MINUTES
    return max(5, min(value, 60))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def flush_capture_if_configured() -> Optional[Path]:
    """Write a passive spool only when the production workflow explicitly enables it."""

    raw_path = os.getenv("V4_KB_SHADOW_SPOOL_PATH", "").strip()
    if not raw_path:
        return None
    limit = _near_final_limit()
    fixed_rows = [
        {"payload": captured.payload, "retrieved_at": captured.retrieved_at}
        for _, captured in sorted(_FIXED_ROWS.items())
    ]
    auction_rows = []
    for _, captured in sorted(_AUCTION_ROWS.items()):
        minutes = _minutes_to_end(captured.payload, captured.retrieved_at)
        if minutes is None or minutes > limit:
            continue
        if not _auction_row_is_v4_eligible(captured.payload):
            continue
        bucket = "LE5" if minutes <= 5 else f"LE{limit}"
        auction_rows.append(
            {
                "payload": captured.payload,
                "retrieved_at": captured.retrieved_at,
                "minutes_to_end": minutes,
                "bucket": bucket,
            }
        )
    spool = {
        "schema_version": SPOOL_SCHEMA_VERSION,
        "captured_at": _utc_now(),
        "auction_near_final_max_minutes": limit,
        "fixed_rows": fixed_rows,
        "auction_near_final_rows": auction_rows,
        "sold_rows": [],
    }
    path = Path(raw_path)
    _atomic_json(path, spool)
    return path


def _money_value(row: Mapping[str, Any]) -> Any:
    for key in ("priceInCents", "currentPriceInCents", "price", "currentPrice", "soldPriceInCents", "soldPrice"):
        if key in row:
            return row.get(key)
    return None


def _history_fingerprint(row: Mapping[str, Any]) -> str:
    item = row.get("item") if isinstance(row.get("item"), Mapping) else {}
    collectible = (
        item.get("collectible")
        if isinstance(item, Mapping) and isinstance(item.get("collectible"), Mapping)
        else {}
    )
    identity = {
        "status": row.get("status"),
        "sellingType": row.get("sellingType"),
        "price": _money_value(row),
        "shipping": row.get("shippingInCents", row.get("shipping")),
        "soldAt": row.get("soldAt") or row.get("saleOccurredAt"),
        "item": {
            key: item.get(key)
            for key in (
                "title",
                "gradingCompany",
                "grade",
                "serialNumber",
                "edition",
                "finish",
                "variant",
                "stamp",
                "shadowTreatment",
            )
        },
        "collectible": {
            key: collectible.get(key)
            for key in (
                "category",
                "type",
                "language",
                "yearOfDistribution",
                "extension",
                "set",
                "reference",
                "edition",
                "finish",
                "printVariant",
                "variant",
                "stamp",
                "shadowTreatment",
            )
        },
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "fixed": {},
        "auction": {},
        "sold": {},
        "ended_revisited": {},
    }


def _empty_rotation_state() -> dict[str, Any]:
    return {
        "schema_version": ROTATION_SCHEMA_VERSION,
        "last_page": 0,
        "total_pages_seen": 68,
        "updated_at": None,
    }


def _bucket_rank(bucket: str) -> int:
    if bucket == "LE5":
        return 2
    if isinstance(bucket, str) and bucket.startswith("LE"):
        return 1
    return 0


def fetch_gcc_single_item(
    native_id: str,
    *,
    http_get: Optional[Callable[..., Any]] = None,
    timeout_seconds: float = 15.0,
) -> Optional[dict[str, Any]]:
    """Fetch single item directly from GCC public API."""
    get_fn = http_get or requests.get
    url = f"{GCC_API_URL}/{native_id}"
    try:
        resp = get_fn(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout_seconds)
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, Mapping):
                return dict(payload)
    except Exception:
        pass
    return None


def fetch_gcc_sold_page(
    page: int = 1,
    *,
    page_size: int = 50,
    sort_type: str = "MOST_RECENT",
    selling_type_group: Optional[str] = None,
    http_get: Optional[Callable[..., Any]] = None,
    timeout_seconds: float = 15.0,
) -> tuple[list[dict[str, Any]], Optional[int]]:
    """Fetch a page of explicit GCC SOLD items."""
    get_fn = http_get or requests.get
    params: dict[str, Any] = {
        "status": "SOLD",
        "sortType": sort_type,
        "page": page,
        "limit": page_size,
        "includeCounts": "true" if page == 1 else "false",
    }
    if selling_type_group:
        params["sellingTypeGroup"] = selling_type_group
    try:
        resp = get_fn(GCC_API_URL, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout_seconds)
        if resp.status_code != 200:
            return [], None
        payload = resp.json()
        if not isinstance(payload, Mapping):
            return [], None
        results = payload.get("results")
        info = payload.get("info")
        next_page = info.get("nextPage") if isinstance(info, Mapping) else None
        if isinstance(results, list):
            valid_rows = [dict(r) for r in results if isinstance(r, Mapping)]
            return valid_rows, next_page
    except Exception:
        pass
    return [], None


def revisit_ended_auctions_in_state(
    state: dict[str, Any],
    *,
    http_get: Optional[Callable[..., Any]] = None,
    max_revisits: int = 50,
    now_dt: Optional[datetime] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Revisit previously spooled near-final auctions after their endTime has passed."""
    current_time = now_dt or datetime.now(timezone.utc)
    auction_state = state.get("auction") if isinstance(state.get("auction"), dict) else {}
    revisited_state = state.get("ended_revisited") if isinstance(state.get("ended_revisited"), dict) else {}
    sold_state = state.get("sold") if isinstance(state.get("sold"), dict) else {}

    proven_sales: list[dict[str, Any]] = []
    updates: dict[str, Any] = {"ended_revisited": {}, "sold": {}}
    revisited_count = 0

    for native_id, info in list(auction_state.items()):
        if revisited_count >= max_revisits:
            break
        if not isinstance(info, Mapping):
            continue
        if native_id in revisited_state or native_id in sold_state:
            continue
        end_time_str = str(info.get("end_time") or "")
        end_dt = _aware_datetime(end_time_str)
        # Only revisit if the auction endTime has definitively elapsed
        if end_dt is None or end_dt > current_time:
            continue

        revisited_count += 1
        item_payload = fetch_gcc_single_item(native_id, http_get=http_get)
        if item_payload is None:
            continue

        if is_proven_gcc_sold(item_payload):
            fingerprint = _history_fingerprint(item_payload)
            proven_sales.append(item_payload)
            updates["sold"][native_id] = {
                "fingerprint": fingerprint,
                "sold_at": item_payload.get("soldAt"),
                "price": _money_value(item_payload),
                "revisited_at": _utc_now(),
            }
            updates["ended_revisited"][native_id] = {
                "status": "SOLD",
                "revisited_at": _utc_now(),
            }
        else:
            status = str(item_payload.get("status") or "UNKNOWN").upper()
            updates["ended_revisited"][native_id] = {
                "status": status,
                "revisited_at": _utc_now(),
            }

    return proven_sales, updates


def filter_spool(
    spool_path: Path,
    state_path: Path,
    output_path: Path,
    manifest_path: Path,
    *,
    http_get: Optional[Callable[..., Any]] = None,
    revisit_ended: bool = True,
    harvest_recent_sold: bool = True,
) -> int:
    """Filter discovery spools, harvest proven sold items, and output deterministic pending batch."""
    spool = _load_json(spool_path, {})
    if spool.get("schema_version") not in (1, SPOOL_SCHEMA_VERSION):
        raise ValueError("unsupported V4 KB spool schema")
    state = _load_json(state_path, _empty_state())
    if state.get("schema_version") not in (1, STATE_SCHEMA_VERSION):
        state = _empty_state()

    fixed_state = state.get("fixed") if isinstance(state.get("fixed"), dict) else {}
    auction_state = state.get("auction") if isinstance(state.get("auction"), dict) else {}
    sold_state = state.get("sold") if isinstance(state.get("sold"), dict) else {}

    pending: list[dict[str, Any]] = []
    updates: dict[str, Any] = {
        "fixed": {},
        "auction": {},
        "sold": {},
        "ended_revisited": {},
    }

    # 1. Process Fixed rows from spool (deduplicated by fingerprint)
    for entry in spool.get("fixed_rows", []):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("payload"), Mapping):
            continue
        row = entry["payload"]
        native_id = _stable_id(row)
        if native_id is None:
            continue
        fingerprint = _history_fingerprint(row)
        if fixed_state.get(native_id, {}).get("fingerprint") == fingerprint:
            continue
        pending.append(dict(row))
        updates["fixed"][native_id] = {
            "fingerprint": fingerprint,
            "seen_at": entry.get("retrieved_at") or spool.get("captured_at"),
        }

    # 2. Process Near-Final Auction rows from spool
    for entry in spool.get("auction_near_final_rows", []):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("payload"), Mapping):
            continue
        row = entry["payload"]
        native_id = _stable_id(row)
        if native_id is None:
            continue
        fingerprint = _history_fingerprint(row)
        bucket = str(entry.get("bucket") or "")
        previous = auction_state.get(native_id, {})
        changed = previous.get("fingerprint") != fingerprint
        closer = _bucket_rank(bucket) > _bucket_rank(str(previous.get("bucket") or ""))
        end_time_str = str(row.get("endTime") or row.get("auctionEndTime") or "")
        if not changed and not closer:
            continue
        pending.append(dict(row))
        updates["auction"][native_id] = {
            "fingerprint": fingerprint,
            "bucket": bucket,
            "end_time": end_time_str,
            "seen_at": entry.get("retrieved_at") or spool.get("captured_at"),
        }

    # 3. Process explicit SOLD rows passed in spool
    for entry in spool.get("sold_rows", []):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("payload"), Mapping):
            continue
        row = entry["payload"]
        native_id = _stable_id(row)
        if native_id is None or not is_proven_gcc_sold(row):
            continue
        fingerprint = _history_fingerprint(row)
        if sold_state.get(native_id, {}).get("fingerprint") == fingerprint:
            continue
        pending.append(dict(row))
        updates["sold"][native_id] = {
            "fingerprint": fingerprint,
            "sold_at": row.get("soldAt"),
            "price": _money_value(row),
            "seen_at": entry.get("retrieved_at") or spool.get("captured_at"),
        }

    # 4. Optional: Harvest recent live SOLD feed if enabled
    if harvest_recent_sold:
        sold_rows, _ = fetch_gcc_sold_page(page=1, page_size=50, sort_type="MOST_RECENT", http_get=http_get)
        retrieved_at = _utc_now()
        for row in sold_rows:
            native_id = _stable_id(row)
            if native_id is None or not is_proven_gcc_sold(row):
                continue
            fingerprint = _history_fingerprint(row)
            if sold_state.get(native_id, {}).get("fingerprint") == fingerprint:
                continue
            if updates["sold"].get(native_id, {}).get("fingerprint") == fingerprint:
                continue
            pending.append(dict(row))
            updates["sold"][native_id] = {
                "fingerprint": fingerprint,
                "sold_at": row.get("soldAt"),
                "price": _money_value(row),
                "seen_at": retrieved_at,
            }

    # 5. Optional: Revisit ended auctions from state
    if revisit_ended:
        revisited_sales, rev_updates = revisit_ended_auctions_in_state(state, http_get=http_get)
        for row in revisited_sales:
            native_id = _stable_id(row)
            if native_id is None:
                continue
            fingerprint = _history_fingerprint(row)
            if sold_state.get(native_id, {}).get("fingerprint") == fingerprint:
                continue
            if updates["sold"].get(native_id, {}).get("fingerprint") == fingerprint:
                continue
            pending.append(dict(row))
        updates["sold"].update(rev_updates.get("sold", {}))
        updates["ended_revisited"].update(rev_updates.get("ended_revisited", {}))

    observed_at = spool.get("captured_at") or _utc_now()
    manifest = {
        "schema_version": STATE_SCHEMA_VERSION,
        "observed_at": observed_at,
        "updates": updates,
    }
    _atomic_json(output_path, pending)
    _atomic_json(manifest_path, manifest)
    return len(pending)


def commit_manifest(state_path: Path, manifest_path: Path) -> None:
    """Commit manifest updates to persistent shadow state."""
    state = _load_json(state_path, _empty_state())
    if state.get("schema_version") not in (1, STATE_SCHEMA_VERSION):
        state = _empty_state()
    manifest = _load_json(manifest_path, {})
    if manifest.get("schema_version") not in (1, STATE_SCHEMA_VERSION):
        raise ValueError("unsupported V4 KB manifest schema")
    for section in ("fixed", "auction", "sold", "ended_revisited"):
        target = state.setdefault(section, {})
        updates = manifest.get("updates", {}).get(section, {})
        if isinstance(target, dict) and isinstance(updates, dict):
            target.update(updates)
    state["updated_at"] = manifest.get("observed_at") or _utc_now()
    state["schema_version"] = STATE_SCHEMA_VERSION
    _atomic_json(state_path, state)


def collect_fixed_rotation_batch(
    rotation_state_path: Path,
    *,
    page_size: int = 100,
    pages_per_run: int = 4,
    http_get: Optional[Callable[..., Any]] = None,
    clock: Callable[[], str] = _utc_now,
    timeout_seconds: float = 15.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Durable 4-page fixed backup rotation + auction backup + recent SOLD harvest.

    - Fixed rotation advances 4 pages per run (page size 100).
    - Wraps safely to page 1 when total pages is exhausted.
    - Auction backup always begins from ENDING_SOON page 1.
    - Collects explicit recent SOLD items.
    """
    get_fn = http_get or requests.get
    current_rot_state = _load_json(rotation_state_path, _empty_rotation_state())
    if current_rot_state.get("schema_version") != ROTATION_SCHEMA_VERSION:
        current_rot_state = _empty_rotation_state()

    last_page = int(current_rot_state.get("last_page") or 0)
    total_pages_seen = int(current_rot_state.get("total_pages_seen") or 68)

    # Determine start page (1-indexed)
    if total_pages_seen > 0:
        start_page = (last_page % total_pages_seen) + 1
    else:
        start_page = 1

    fixed_rows: list[dict[str, Any]] = []
    current_page = start_page
    pages_collected = 0
    retrieved_at = clock()
    last_fetched_page = start_page

    while pages_collected < pages_per_run:
        page_to_fetch = current_page
        last_fetched_page = page_to_fetch
        params: dict[str, Any] = {
            "sellingTypes": "FIXED_PRICE",
            "page": page_to_fetch,
            "limit": page_size,
            "includeCounts": "true" if page_to_fetch == 1 or pages_collected == 0 else "false",
        }
        next_page = None
        try:
            resp = get_fn(GCC_API_URL, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout_seconds)
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, Mapping):
                    info = payload.get("info") if isinstance(payload.get("info"), Mapping) else {}
                    counts = info.get("counts") if isinstance(info.get("counts"), Mapping) else {}
                    fixed_count = counts.get("fixedPriceCount") or counts.get("total") or info.get("totalItems")
                    if isinstance(fixed_count, int) and fixed_count > 0:
                        total_pages_seen = max(1, math.ceil(fixed_count / page_size))

                    results = payload.get("results")
                    if isinstance(results, list):
                        for r in results:
                            if isinstance(r, Mapping):
                                fixed_rows.append({"payload": dict(r), "retrieved_at": retrieved_at})

                    next_page = info.get("nextPage")
        except Exception:
            pass

        if next_page is not None and isinstance(next_page, int) and next_page > page_to_fetch:
            if total_pages_seen > 0 and next_page > total_pages_seen:
                current_page = 1
            else:
                current_page = next_page
        elif next_page is None:
            current_page = 1
        else:
            current_page = page_to_fetch + 1
            if total_pages_seen > 0 and current_page > total_pages_seen:
                current_page = 1

        pages_collected += 1

    end_cursor_page = last_fetched_page

    # Auction Backup: Always from ENDING_SOON page 1
    auction_rows: list[dict[str, Any]] = []
    try:
        auction_params = {
            "sellingTypeGroup": "AUCTION",
            "sortType": "ENDING_SOON",
            "page": 1,
            "limit": page_size,
            "includeCounts": "true",
        }
        resp = get_fn(GCC_API_URL, params=auction_params, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout_seconds)
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, Mapping):
                results = payload.get("results")
                if isinstance(results, list):
                    limit = _near_final_limit()
                    for r in results:
                        if not isinstance(r, Mapping):
                            continue
                        minutes = _minutes_to_end(r, retrieved_at)
                        if minutes is None or minutes > limit:
                            continue
                        if not _auction_row_is_v4_eligible(r):
                            continue
                        bucket = "LE5" if minutes <= 5 else f"LE{limit}"
                        auction_rows.append(
                            {
                                "payload": dict(r),
                                "retrieved_at": retrieved_at,
                                "minutes_to_end": minutes,
                                "bucket": bucket,
                            }
                        )
    except Exception:
        pass

    # Harvest explicit recent SOLD rows
    sold_rows: list[dict[str, Any]] = []
    try:
        raw_sold, _ = fetch_gcc_sold_page(page=1, page_size=page_size, sort_type="MOST_RECENT", http_get=get_fn, timeout_seconds=timeout_seconds)
        for r in raw_sold:
            if is_proven_gcc_sold(r):
                sold_rows.append({"payload": r, "retrieved_at": retrieved_at})
    except Exception:
        pass

    spool = {
        "schema_version": SPOOL_SCHEMA_VERSION,
        "captured_at": retrieved_at,
        "auction_near_final_max_minutes": _near_final_limit(),
        "fixed_rows": fixed_rows,
        "auction_near_final_rows": auction_rows,
        "sold_rows": sold_rows,
    }

    rotation_manifest = {
        "schema_version": ROTATION_SCHEMA_VERSION,
        "retrieved_at": retrieved_at,
        "start_page": start_page,
        "last_page": end_cursor_page,
        "total_pages_seen": total_pages_seen,
        "fixed_rows_count": len(fixed_rows),
        "auction_rows_count": len(auction_rows),
        "sold_rows_count": len(sold_rows),
    }

    return spool, rotation_manifest


def commit_rotation_state(rotation_state_path: Path, rotation_manifest_path: Path) -> None:
    """Commit the rotation cursor only after successful ingestion."""
    manifest = _load_json(rotation_manifest_path, {})
    if manifest.get("schema_version") != ROTATION_SCHEMA_VERSION:
        raise ValueError("unsupported rotation manifest schema")
    state = {
        "schema_version": ROTATION_SCHEMA_VERSION,
        "last_page": manifest.get("last_page", 1),
        "total_pages_seen": manifest.get("total_pages_seen", 68),
        "updated_at": manifest.get("retrieved_at") or _utc_now(),
    }
    _atomic_json(rotation_state_path, state)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V4 KB shadow bridge, SOLD harvester & fixed rotation")
    sub = parser.add_subparsers(dest="command", required=True)

    filt = sub.add_parser("filter")
    filt.add_argument("--spool", required=True)
    filt.add_argument("--state", required=True)
    filt.add_argument("--output", required=True)
    filt.add_argument("--manifest", required=True)
    filt.add_argument("--no-revisit", action="store_true", default=False)
    filt.add_argument("--no-sold-harvest", action="store_true", default=False)

    commit = sub.add_parser("commit")
    commit.add_argument("--state", required=True)
    commit.add_argument("--manifest", required=True)

    rot = sub.add_parser("rotate")
    rot.add_argument("--rotation-state", required=True)
    rot.add_argument("--output-spool", required=True)
    rot.add_argument("--manifest", required=True)
    rot.add_argument("--page-size", type=int, default=100)
    rot.add_argument("--pages", type=int, default=4)

    rot_commit = sub.add_parser("commit-rotate")
    rot_commit.add_argument("--rotation-state", required=True)
    rot_commit.add_argument("--manifest", required=True)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "filter":
        count = filter_spool(
            Path(args.spool),
            Path(args.state),
            Path(args.output),
            Path(args.manifest),
            revisit_ended=not args.no_revisit,
            harvest_recent_sold=not args.no_sold_harvest,
        )
        print(count)
        return 0
    elif args.command == "commit":
        commit_manifest(Path(args.state), Path(args.manifest))
        return 0
    elif args.command == "rotate":
        spool, manifest = collect_fixed_rotation_batch(
            Path(args.rotation_state),
            page_size=args.page_size,
            pages_per_run=args.pages,
        )
        _atomic_json(Path(args.output_spool), spool)
        _atomic_json(Path(args.manifest), manifest)
        print(f"ROTATED: pages {manifest['start_page']}..{manifest['last_page']} (fixed: {manifest['fixed_rows_count']}, auction: {manifest['auction_rows_count']}, sold: {manifest['sold_rows_count']})")
        return 0
    elif args.command == "commit-rotate":
        commit_rotation_state(Path(args.rotation_state), Path(args.manifest))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
