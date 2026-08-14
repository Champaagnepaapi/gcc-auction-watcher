from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import watcher


SPOOL_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
DEFAULT_NEAR_FINAL_MINUTES = 12
GCC_API_URL = watcher.GCC_ON_SALE_ITEMS_API_URL


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

    def __init__(self, delegate, *, clock=_utc_now) -> None:
        self.delegate = delegate
        self.clock = clock

    def __call__(self, url, *args, **kwargs):
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

    def collect_with_capture(page, url, source_type, run_diagnostics=None, **kwargs):
        if source_type == "fixed" and kwargs.get("fixed_http_get") is None:
            kwargs["fixed_http_get"] = capture_get
        return original_collect(page, url, source_type, run_diagnostics, **kwargs)

    def auction_discover_with_capture(*args, **kwargs):
        if kwargs.get("http_get") is None:
            kwargs["http_get"] = capture_get
        return original_auction_discover(*args, **kwargs)

    watcher.collect_lots_from_listing = collect_with_capture
    auction_discovery.discover_auction_api_lots = auction_discover_with_capture
    _INSTALLED = True


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
    }
    path = Path(raw_path)
    _atomic_json(path, spool)
    return path


def _money_value(row: Mapping[str, Any]) -> Any:
    for key in ("priceInCents", "currentPriceInCents", "price", "currentPrice"):
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
    return {"schema_version": STATE_SCHEMA_VERSION, "fixed": {}, "auction": {}}


def _bucket_rank(bucket: str) -> int:
    if bucket == "LE5":
        return 2
    if isinstance(bucket, str) and bucket.startswith("LE"):
        return 1
    return 0


def filter_spool(
    spool_path: Path,
    state_path: Path,
    output_path: Path,
    manifest_path: Path,
) -> int:
    spool = _load_json(spool_path, {})
    if spool.get("schema_version") != SPOOL_SCHEMA_VERSION:
        raise ValueError("unsupported V4 KB spool schema")
    state = _load_json(state_path, _empty_state())
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        state = _empty_state()
    fixed_state = state.get("fixed") if isinstance(state.get("fixed"), dict) else {}
    auction_state = (
        state.get("auction") if isinstance(state.get("auction"), dict) else {}
    )

    pending: list[dict[str, Any]] = []
    updates = {"fixed": {}, "auction": {}}

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
        if not changed and not closer:
            continue
        pending.append(dict(row))
        updates["auction"][native_id] = {
            "fingerprint": fingerprint,
            "bucket": bucket,
            "seen_at": entry.get("retrieved_at") or spool.get("captured_at"),
        }

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
    state = _load_json(state_path, _empty_state())
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        state = _empty_state()
    manifest = _load_json(manifest_path, {})
    if manifest.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported V4 KB manifest schema")
    for section in ("fixed", "auction"):
        target = state.setdefault(section, {})
        updates = manifest.get("updates", {}).get(section, {})
        if isinstance(target, dict) and isinstance(updates, dict):
            target.update(updates)
    state["updated_at"] = manifest.get("observed_at") or _utc_now()
    _atomic_json(state_path, state)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Passive V4 -> Robot KB shadow bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    filt = sub.add_parser("filter")
    filt.add_argument("--spool", required=True)
    filt.add_argument("--state", required=True)
    filt.add_argument("--output", required=True)
    filt.add_argument("--manifest", required=True)
    commit = sub.add_parser("commit")
    commit.add_argument("--state", required=True)
    commit.add_argument("--manifest", required=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "filter":
        count = filter_spool(
            Path(args.spool), Path(args.state), Path(args.output), Path(args.manifest)
        )
        print(count)
        return 0
    commit_manifest(Path(args.state), Path(args.manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
