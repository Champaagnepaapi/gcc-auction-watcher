#!/usr/bin/env python3
"""Capture Fanatics PAID sale evidence without depending on TCGdex availability.

This is a local/manual read-only evidence lane. It reuses the proven Fanatics
provider semantics from ``robot_kb_fanatics_paid_sold_harvest`` but deliberately
performs zero TCGdex requests. Exact identity and microvariant resolution remain
mandatory later before any sale can become a Robot KB ``SALE_TRANSACTION``.

The purpose is resilience: a transient catalog outage must not make genuine
provider-level PAID sale evidence disappear from the current harvest.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


LOCAL_DIR = Path(__file__).resolve().parent
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

import robot_kb_fanatics_paid_sold_harvest as base  # noqa: E402


MAX_PENDING_RECORDS = 200


def pending_record(row: base.PaidSaleRow) -> Mapping[str, Any]:
    payload = asdict(row)
    payload.update(
        {
            "source_url": (
                "https://sales-history-api.services.fanaticscollect.com/"
                f"api/v1/pub/sales/item/{row.source_native_record_id}"
            ),
            "paid_sale_status_proven": True,
            "provider_purchase_price_proven": True,
            "identity_status": "PENDING_TCGDEX",
            "microvariant_status": "PENDING_TCGDEX",
            "currency": "",
            "currency_proven": False,
            "robot_kb_sale_ready": False,
        }
    )
    return payload


def safe_summary() -> dict[str, Any]:
    summary = base.safe_summary()
    summary.update(
        {
            "mode": "READ_ONLY_FANATICS_PAID_PENDING_CAPTURE",
            "tcgdex_requests": 0,
            "identity_resolution_attempted": False,
            "pending_identity_only": True,
        }
    )
    return summary


def run_capture(
    *,
    queries: Sequence[str],
    pages_per_query: int,
    page_size: int,
    timeout_seconds: float,
    fetcher: Callable[..., Mapping[str, Any]] = base.fetch_page,
) -> Mapping[str, Any]:
    summary = safe_summary()
    rejects: Counter[str] = Counter()
    records: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    pages_fetched = 0
    rows_seen = 0

    for raw_query in queries:
        query = base._norm_text(raw_query)
        if len(query) < 2:
            continue
        for page_number in range(pages_per_query):
            payload = fetcher(
                query=query,
                page=page_number,
                size=page_size,
                timeout_seconds=timeout_seconds,
            )
            pages_fetched += 1
            rows = base._embedded_rows(payload)
            rows_seen += len(rows)
            for raw in rows:
                source_id = base._norm_text(raw.get("id"))
                if source_id and source_id in seen_ids:
                    rejects["DUPLICATE_SOURCE_ID"] += 1
                    continue
                if source_id:
                    seen_ids.add(source_id)
                row, reason = base.precheck_row(raw)
                if row is None:
                    rejects[reason] += 1
                    continue
                records.append(pending_record(row))
                if len(records) >= MAX_PENDING_RECORDS:
                    break
            if len(records) >= MAX_PENDING_RECORDS:
                break
            meta = base._page_meta(payload)
            try:
                total_pages = int(meta.get("totalPages"))
            except (TypeError, ValueError):
                total_pages = page_number + 1
            if not rows or page_number + 1 >= total_pages:
                break
        if len(records) >= MAX_PENDING_RECORDS:
            break

    summary.update(
        {
            "queries": list(queries),
            "pages_fetched": pages_fetched,
            "rows_seen": rows_seen,
            "pending_identity_count": len(records),
            "blocked": dict(sorted(rejects.items())),
            "records": records,
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture Fanatics PAID evidence without TCGdex network dependency"
    )
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--pages-per-query", type=int, default=base.DEFAULT_PAGES_PER_QUERY)
    parser.add_argument("--page-size", type=int, default=base.DEFAULT_PAGE_SIZE)
    parser.add_argument("--timeout-seconds", type=float, default=base.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if not 1 <= args.pages_per_query <= base.MAX_PAGES_PER_QUERY:
        parser.error(
            f"--pages-per-query must be between 1 and {base.MAX_PAGES_PER_QUERY}"
        )
    if not 1 <= args.page_size <= base.MAX_PAGE_SIZE:
        parser.error(f"--page-size must be between 1 and {base.MAX_PAGE_SIZE}")
    if not 1.0 <= args.timeout_seconds <= base.MAX_TIMEOUT_SECONDS:
        parser.error(
            f"--timeout-seconds must be between 1 and {base.MAX_TIMEOUT_SECONDS}"
        )

    queries = tuple(args.queries or base.DEFAULT_QUERIES)
    try:
        payload = run_capture(
            queries=queries,
            pages_per_query=args.pages_per_query,
            page_size=args.page_size,
            timeout_seconds=args.timeout_seconds,
        )
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        try:
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
