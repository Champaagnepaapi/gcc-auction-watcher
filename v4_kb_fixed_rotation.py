"""Durable fixed-price inventory backup rotation for Robot KB shadow collection."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import requests


GCC_API_URL = "https://api.gradedcardcenter.com/on-sale-items"
DEFAULT_PAGE_SIZE = 100
DEFAULT_PAGES_PER_RUN = 4
ROTATION_STATE_SCHEMA_VERSION = 1
ROTATION_MANIFEST_SCHEMA_VERSION = 1


class RotationError(RuntimeError):
    """Raised when fixed rotation collection or validation fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


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


def _empty_rotation_state() -> dict[str, Any]:
    return {
        "schema_version": ROTATION_STATE_SCHEMA_VERSION,
        "last_page": 0,
        "total_pages_seen": 68,
        "updated_at": None,
    }


def fetch_fixed_rotation_batch(
    rotation_state_path: Path,
    output_fixture_path: Path,
    manifest_path: Path,
    *,
    pages_per_run: int = DEFAULT_PAGES_PER_RUN,
    page_size: int = DEFAULT_PAGE_SIZE,
    http_get: Optional[Callable[..., Any]] = None,
    clock: Callable[[], str] = utc_now,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Fetch consecutive fixed-price pages with Pokemon and CARDS filtering.

    Fails non-zero (raises RotationError) on:
    - HTTP failure (non-200, timeout, connection error)
    - Malformed payload (not a JSON object, missing info or results, results not list)
    - Pagination mismatch (info.currentPage != expected page)
    - No progress (results returned but 0 valid records)
    - Partial collection (fewer than pages_per_run pages fetched before completion)
    """
    if pages_per_run <= 0:
        raise RotationError("pages_per_run must be strictly positive")
    if page_size <= 0:
        raise RotationError("page_size must be strictly positive")

    get_fn = http_get or requests.get
    state = _load_json(rotation_state_path, _empty_rotation_state())
    if state.get("schema_version") != ROTATION_STATE_SCHEMA_VERSION:
        state = _empty_rotation_state()

    last_page = int(state.get("last_page") or 0)
    total_pages_seen = int(state.get("total_pages_seen") or 68)

    # 1-indexed start page
    if total_pages_seen > 0:
        start_page = (last_page % total_pages_seen) + 1
    else:
        start_page = 1

    retrieved_at = clock()
    collected_rows: list[dict[str, Any]] = []
    current_page = start_page
    pages_fetched = 0
    last_fetched_page = start_page

    while pages_fetched < pages_per_run:
        page_to_fetch = current_page
        last_fetched_page = page_to_fetch

        params: dict[str, Any] = {
            "sellingTypes": "FIXED_PRICE",
            "categories": "Pokemon",
            "itemTypes": "CARDS",
            "page": page_to_fetch,
            "limit": page_size,
            "includeCounts": "true" if page_to_fetch == 1 or pages_fetched == 0 else "false",
        }

        try:
            resp = get_fn(
                GCC_API_URL,
                params=params,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout_seconds,
            )
        except Exception as exc:
            raise RotationError(f"HTTP request failed for page {page_to_fetch}: {exc}") from exc

        if getattr(resp, "status_code", None) != 200:
            status = getattr(resp, "status_code", "unknown")
            raise RotationError(f"HTTP {status} fetching page {page_to_fetch}")

        try:
            payload = resp.json()
        except Exception as exc:
            raise RotationError(f"Malformed JSON on page {page_to_fetch}: {exc}") from exc

        if not isinstance(payload, Mapping):
            raise RotationError(f"Page {page_to_fetch} payload is not a JSON object")

        info = payload.get("info")
        results = payload.get("results")

        if not isinstance(info, Mapping) or not isinstance(results, list):
            raise RotationError(f"Page {page_to_fetch} lacks info or results list")

        current_page_reported = info.get("currentPage")
        if current_page_reported != page_to_fetch:
            raise RotationError(
                f"Page mismatch: requested {page_to_fetch}, received {current_page_reported}"
            )

        counts = info.get("counts") if isinstance(info.get("counts"), Mapping) else {}
        fixed_count = counts.get("fixedPriceCount") or counts.get("total") or info.get("totalItems")
        if isinstance(fixed_count, int) and fixed_count > 0:
            total_pages_seen = max(1, math.ceil(fixed_count / page_size))

        valid_page_records = 0
        for r in results:
            if isinstance(r, Mapping) and r.get("id"):
                collected_rows.append(dict(r))
                valid_page_records += 1

        if results and valid_page_records == 0:
            raise RotationError(f"Page {page_to_fetch} contained results but 0 valid records")

        # Determine next page in sequence
        next_page = info.get("nextPage")
        if next_page is not None and isinstance(next_page, int) and next_page > page_to_fetch:
            if total_pages_seen > 0 and next_page > total_pages_seen:
                current_page = 1
            else:
                current_page = next_page
        elif next_page is None or (total_pages_seen > 0 and page_to_fetch >= total_pages_seen):
            current_page = 1
        else:
            current_page = page_to_fetch + 1
            if total_pages_seen > 0 and current_page > total_pages_seen:
                current_page = 1

        pages_fetched += 1

    if pages_fetched != pages_per_run:
        raise RotationError(
            f"Partial collection: expected {pages_per_run} pages, fetched {pages_fetched}"
        )

    manifest = {
        "schema_version": ROTATION_MANIFEST_SCHEMA_VERSION,
        "retrieved_at": retrieved_at,
        "start_page": start_page,
        "last_page": last_fetched_page,
        "total_pages_seen": total_pages_seen,
        "pages_fetched": pages_fetched,
        "records_count": len(collected_rows),
    }

    _atomic_json(output_fixture_path, collected_rows)
    _atomic_json(manifest_path, manifest)
    return manifest


def commit_rotation_cursor(
    rotation_state_path: Path,
    manifest_path: Path,
    *,
    clock: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    """Advance the durable rotation cursor after verified successful Neon ingest."""
    manifest = _load_json(manifest_path, {})
    if manifest.get("schema_version") != ROTATION_MANIFEST_SCHEMA_VERSION:
        raise RotationError("Invalid or missing rotation manifest for cursor commit")

    last_page = manifest.get("last_page")
    total_pages_seen = manifest.get("total_pages_seen")

    if not isinstance(last_page, int) or last_page <= 0:
        raise RotationError(f"Invalid last_page in manifest: {last_page}")
    if not isinstance(total_pages_seen, int) or total_pages_seen <= 0:
        raise RotationError(f"Invalid total_pages_seen in manifest: {total_pages_seen}")

    state = {
        "schema_version": ROTATION_STATE_SCHEMA_VERSION,
        "last_page": last_page,
        "total_pages_seen": total_pages_seen,
        "updated_at": manifest.get("retrieved_at") or clock(),
    }
    _atomic_json(rotation_state_path, state)
    return state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Durable fixed-price inventory backup rotation for Robot KB"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rot = sub.add_parser("rotate", help="Fetch next consecutive fixed pages batch")
    rot.add_argument("--rotation-state", required=True, help="Path to rotation state JSON")
    rot.add_argument("--output-fixture", required=True, help="Path to output fixture JSON")
    rot.add_argument("--manifest", required=True, help="Path to output manifest JSON")
    rot.add_argument("--pages", type=int, default=DEFAULT_PAGES_PER_RUN, help="Pages to fetch (default: 4)")
    rot.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="Page size (default: 100)")

    com = sub.add_parser("commit", help="Commit rotation cursor after successful ingest")
    com.add_argument("--rotation-state", required=True, help="Path to rotation state JSON")
    com.add_argument("--manifest", required=True, help="Path to manifest JSON")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "rotate":
        manifest = fetch_fixed_rotation_batch(
            Path(args.rotation_state),
            Path(args.output_fixture),
            Path(args.manifest),
            pages_per_run=args.pages,
            page_size=args.page_size,
        )
        print(
            f"FIXED ROTATION: pages {manifest['start_page']}..{manifest['last_page']} "
            f"({manifest['records_count']} cards, total pages {manifest['total_pages_seen']})"
        )
        return 0
    elif args.command == "commit":
        state = commit_rotation_cursor(
            Path(args.rotation_state),
            Path(args.manifest),
        )
        print(
            f"CURSOR COMMITTED: last_page={state['last_page']} total_pages={state['total_pages_seen']}"
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
