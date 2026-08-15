"""Hybrid fixed-price Robot KB collector: recent + sequential + targeted coverage."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import requests

import v4_kb_fixed_rotation as rotation


GCC_API_URL = rotation.GCC_API_URL
HYBRID_MANIFEST_SCHEMA_VERSION = 1
TARGET_STATE_SCHEMA_VERSION = 1
DEFAULT_RECENT_RECORDS = 100
DEFAULT_ROTATION_PAGES = 2
DEFAULT_TARGET_RECORDS = 100
DEFAULT_PAGE_SIZE = 100
MAX_TARGET_QUERIES = 8

TARGET_DIMENSIONS = (
    "languages",
    "gradingCompanies",
    "grades",
    "editions",
)


class HybridFixedError(RuntimeError):
    """Raised when a hybrid fixed collection batch cannot be proven safe."""


def _empty_target_state() -> dict[str, Any]:
    return {
        "schema_version": TARGET_STATE_SCHEMA_VERSION,
        "dimension_cursor": 0,
        "segments": {dimension: {} for dimension in TARGET_DIMENSIONS},
        "updated_at": None,
    }


def _load_target_state(path: Path) -> dict[str, Any]:
    state = rotation._load_json(path, _empty_target_state())
    if not isinstance(state, dict) or state.get("schema_version") != TARGET_STATE_SCHEMA_VERSION:
        return _empty_target_state()
    segments = state.get("segments")
    if not isinstance(segments, dict):
        return _empty_target_state()
    normalized = _empty_target_state()
    normalized["dimension_cursor"] = int(state.get("dimension_cursor") or 0) % len(TARGET_DIMENSIONS)
    normalized["updated_at"] = state.get("updated_at")
    for dimension in TARGET_DIMENSIONS:
        raw_bucket = segments.get(dimension)
        if not isinstance(raw_bucket, dict):
            continue
        bucket: dict[str, dict[str, int]] = {}
        for raw_value, raw_stats in raw_bucket.items():
            value = str(raw_value).strip()
            if not value or not isinstance(raw_stats, dict):
                continue
            bucket[value] = {
                "runs": max(0, int(raw_stats.get("runs") or 0)),
                "records": max(0, int(raw_stats.get("records") or 0)),
            }
        normalized["segments"][dimension] = bucket
    return normalized


def _stable_id(row: Mapping[str, Any]) -> str:
    raw = row.get("id")
    return str(raw).strip() if raw is not None else ""


def _scalar(value: Any) -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()
    return ""


def _target_values(row: Mapping[str, Any]) -> dict[str, str]:
    item = row.get("item") if isinstance(row.get("item"), Mapping) else {}
    collectible = (
        item.get("collectible")
        if isinstance(item, Mapping) and isinstance(item.get("collectible"), Mapping)
        else {}
    )
    return {
        "languages": _scalar(
            collectible.get("language")
            or item.get("language")
            or row.get("language")
        ),
        "gradingCompanies": _scalar(
            item.get("gradingCompany")
            or item.get("grader")
            or row.get("gradingCompany")
        ),
        "grades": _scalar(item.get("grade") or row.get("grade")),
        "editions": _scalar(
            collectible.get("edition")
            or item.get("edition")
            or row.get("edition")
        ),
    }


def _register_segments(state: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    segments = state["segments"]
    for row in rows:
        for dimension, value in _target_values(row).items():
            if not value:
                continue
            bucket = segments[dimension]
            bucket.setdefault(value, {"runs": 0, "records": 0})


def _next_target_segment(state: dict[str, Any]) -> tuple[str, str] | None:
    start = int(state.get("dimension_cursor") or 0) % len(TARGET_DIMENSIONS)
    segments = state["segments"]
    for offset in range(len(TARGET_DIMENSIONS)):
        index = (start + offset) % len(TARGET_DIMENSIONS)
        dimension = TARGET_DIMENSIONS[index]
        bucket = segments.get(dimension) or {}
        if not bucket:
            continue
        value = min(
            bucket,
            key=lambda candidate: (
                int(bucket[candidate].get("runs") or 0),
                int(bucket[candidate].get("records") or 0),
                candidate.casefold(),
            ),
        )
        state["dimension_cursor"] = (index + 1) % len(TARGET_DIMENSIONS)
        return dimension, value
    return None


def _base_params(*, page: int, limit: int) -> dict[str, Any]:
    return {
        "sellingTypes": "FIXED_PRICE",
        "categories": "Pokemon",
        "itemTypes": "CARDS",
        "status": "ON_SALE",
        "page": page,
        "limit": limit,
        "includeCounts": "true" if page == 1 else "false",
    }


def _fetch_page(
    *,
    extra_params: Mapping[str, Any],
    page: int,
    limit: int,
    http_get: Optional[Callable[..., Any]] = None,
    timeout_seconds: float = 15.0,
) -> list[dict[str, Any]]:
    get_fn = http_get or requests.get
    params = _base_params(page=page, limit=limit)
    params.update(dict(extra_params))
    try:
        response = get_fn(
            GCC_API_URL,
            params=params,
            headers={
                "Accept": "application/json",
                "x-device-platform": "web",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise HybridFixedError(f"HTTP request failed for hybrid fixed page: {exc}") from exc

    if getattr(response, "status_code", None) != 200:
        raise HybridFixedError(
            f"HTTP {getattr(response, 'status_code', 'unknown')} fetching hybrid fixed page"
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise HybridFixedError(f"Malformed JSON in hybrid fixed page: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HybridFixedError("Hybrid fixed payload is not a JSON object")
    info = payload.get("info")
    results = payload.get("results")
    if not isinstance(info, Mapping) or not isinstance(results, list):
        raise HybridFixedError("Hybrid fixed payload lacks info/results")
    if info.get("currentPage") != page:
        raise HybridFixedError(
            f"Hybrid fixed page mismatch: requested {page}, received {info.get('currentPage')}"
        )

    rows: list[dict[str, Any]] = []
    for raw in results:
        if isinstance(raw, Mapping) and _stable_id(raw):
            rows.append(dict(raw))
    if results and not rows:
        raise HybridFixedError("Hybrid fixed page contained results but no stable GCC ids")
    return rows


def _dedupe_append(
    destination: list[dict[str, Any]],
    seen: set[str],
    rows: list[dict[str, Any]],
    *,
    cap: Optional[int] = None,
) -> int:
    added = 0
    for row in rows:
        native_id = _stable_id(row)
        if not native_id or native_id in seen:
            continue
        destination.append(row)
        seen.add(native_id)
        added += 1
        if cap is not None and added >= cap:
            break
    return added


def fetch_fixed_hybrid_batch(
    rotation_state_path: Path,
    target_state_path: Path,
    output_fixture_path: Path,
    hybrid_manifest_path: Path,
    rotation_manifest_path: Path,
    *,
    recent_records: int = DEFAULT_RECENT_RECORDS,
    rotation_pages: int = DEFAULT_ROTATION_PAGES,
    target_records: int = DEFAULT_TARGET_RECORDS,
    page_size: int = DEFAULT_PAGE_SIZE,
    http_get: Optional[Callable[..., Any]] = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    if not 0 <= recent_records <= page_size:
        raise HybridFixedError("recent_records must be between 0 and page_size")
    if rotation_pages <= 0:
        raise HybridFixedError("rotation_pages must be strictly positive")
    if target_records < 0:
        raise HybridFixedError("target_records must be non-negative")
    if page_size <= 0:
        raise HybridFixedError("page_size must be strictly positive")

    rotation_fixture_path = output_fixture_path.with_name(
        f"{output_fixture_path.stem}.rotation.json"
    )
    rotation_manifest = rotation.fetch_fixed_rotation_batch(
        rotation_state_path,
        rotation_fixture_path,
        rotation_manifest_path,
        pages_per_run=rotation_pages,
        page_size=page_size,
        http_get=http_get,
        timeout_seconds=timeout_seconds,
    )
    raw_rotation_rows = rotation._load_json(rotation_fixture_path, [])
    if not isinstance(raw_rotation_rows, list):
        raise HybridFixedError("Rotation fixture is malformed")
    rotation_rows = [
        dict(row)
        for row in raw_rotation_rows
        if isinstance(row, Mapping) and _stable_id(row)
    ]

    recent_rows: list[dict[str, Any]] = []
    if recent_records:
        recent_rows = _fetch_page(
            extra_params={"sortType": "MOST_RECENT"},
            page=1,
            limit=recent_records,
            http_get=http_get,
            timeout_seconds=timeout_seconds,
        )

    proposed_target_state = copy.deepcopy(_load_target_state(target_state_path))
    _register_segments(proposed_target_state, recent_rows + rotation_rows)

    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    recent_unique = _dedupe_append(combined, seen, recent_rows)
    rotation_unique = _dedupe_append(combined, seen, rotation_rows)

    targeted_rows: list[dict[str, Any]] = []
    targeted_seen = set(seen)
    target_queries: list[dict[str, Any]] = []
    queries_used = 0

    while len(targeted_rows) < target_records and queries_used < MAX_TARGET_QUERIES:
        selected = _next_target_segment(proposed_target_state)
        if selected is None:
            break
        dimension, value = selected
        bucket = proposed_target_state["segments"][dimension][value]
        remaining = target_records - len(targeted_rows)
        rows = _fetch_page(
            extra_params={
                "sortType": "MOST_RECENT",
                dimension: json.dumps([value], ensure_ascii=False),
            },
            page=1,
            limit=min(page_size, max(1, remaining)),
            http_get=http_get,
            timeout_seconds=timeout_seconds,
        )
        _register_segments(proposed_target_state, rows)

        before = len(targeted_rows)
        _dedupe_append(targeted_rows, targeted_seen, rows, cap=remaining)
        added = len(targeted_rows) - before
        bucket["runs"] = int(bucket.get("runs") or 0) + 1
        bucket["records"] = int(bucket.get("records") or 0) + added
        queries_used += 1
        target_queries.append(
            {
                "dimension": dimension,
                "value": value,
                "rows_returned": len(rows),
                "unique_added": added,
            }
        )

    targeted_unique = _dedupe_append(combined, seen, targeted_rows, cap=target_records)
    proposed_target_state["updated_at"] = rotation_manifest["retrieved_at"]

    manifest = {
        "schema_version": HYBRID_MANIFEST_SCHEMA_VERSION,
        "retrieved_at": rotation_manifest["retrieved_at"],
        "recent_records_cap": recent_records,
        "recent_records_fetched": len(recent_rows),
        "recent_unique_added": recent_unique,
        "rotation_pages": rotation_pages,
        "rotation_records_fetched": len(rotation_rows),
        "rotation_unique_added": rotation_unique,
        "rotation_start_page": rotation_manifest["start_page"],
        "rotation_last_page": rotation_manifest["last_page"],
        "rotation_total_pages_seen": rotation_manifest["total_pages_seen"],
        "target_records_cap": target_records,
        "targeted_unique_added": targeted_unique,
        "target_queries_used": queries_used,
        "target_queries": target_queries,
        "total_unique_records": len(combined),
        "proposed_target_state": proposed_target_state,
    }
    rotation._atomic_json(output_fixture_path, combined)
    rotation._atomic_json(hybrid_manifest_path, manifest)
    return manifest


def commit_fixed_hybrid_state(
    rotation_state_path: Path,
    target_state_path: Path,
    hybrid_manifest_path: Path,
    rotation_manifest_path: Path,
) -> dict[str, Any]:
    manifest = rotation._load_json(hybrid_manifest_path, {})
    if not isinstance(manifest, dict) or manifest.get("schema_version") != HYBRID_MANIFEST_SCHEMA_VERSION:
        raise HybridFixedError("Invalid or missing hybrid manifest")
    proposed_target_state = manifest.get("proposed_target_state")
    if (
        not isinstance(proposed_target_state, dict)
        or proposed_target_state.get("schema_version") != TARGET_STATE_SCHEMA_VERSION
    ):
        raise HybridFixedError("Invalid proposed target state")

    rotation_state = rotation.commit_rotation_cursor(
        rotation_state_path,
        rotation_manifest_path,
    )
    rotation._atomic_json(target_state_path, proposed_target_state)
    return {
        "rotation": rotation_state,
        "target": proposed_target_state,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hybrid fixed Robot KB collector: recent + sequential + targeted"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--rotation-state", required=True)
    fetch.add_argument("--target-state", required=True)
    fetch.add_argument("--output-fixture", required=True)
    fetch.add_argument("--manifest", required=True)
    fetch.add_argument("--rotation-manifest", required=True)
    fetch.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    fetch.add_argument("--rotation-pages", type=int, default=DEFAULT_ROTATION_PAGES)
    fetch.add_argument("--recent-records", type=int, default=DEFAULT_RECENT_RECORDS)
    fetch.add_argument("--target-records", type=int, default=DEFAULT_TARGET_RECORDS)

    commit = sub.add_parser("commit")
    commit.add_argument("--rotation-state", required=True)
    commit.add_argument("--target-state", required=True)
    commit.add_argument("--manifest", required=True)
    commit.add_argument("--rotation-manifest", required=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "fetch":
        manifest = fetch_fixed_hybrid_batch(
            Path(args.rotation_state),
            Path(args.target_state),
            Path(args.output_fixture),
            Path(args.manifest),
            Path(args.rotation_manifest),
            recent_records=args.recent_records,
            rotation_pages=args.rotation_pages,
            target_records=args.target_records,
            page_size=args.page_size,
        )
        print(
            "FIXED HYBRID: "
            f"recent={manifest['recent_records_fetched']} "
            f"rotation={manifest['rotation_records_fetched']} "
            f"(pages {manifest['rotation_start_page']}..{manifest['rotation_last_page']}) "
            f"targeted={manifest['targeted_unique_added']} "
            f"unique_total={manifest['total_unique_records']} "
            f"target_queries={manifest['target_queries_used']}"
        )
        for target in manifest["target_queries"]:
            print(
                "TARGET: "
                f"{target['dimension']}={target['value']} "
                f"rows={target['rows_returned']} unique_added={target['unique_added']}"
            )
        return 0

    state = commit_fixed_hybrid_state(
        Path(args.rotation_state),
        Path(args.target_state),
        Path(args.manifest),
        Path(args.rotation_manifest),
    )
    print(
        "FIXED HYBRID STATE COMMITTED: "
        f"last_page={state['rotation']['last_page']} "
        f"target_cursor={state['target']['dimension_cursor']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
