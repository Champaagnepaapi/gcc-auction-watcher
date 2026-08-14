"""Manual-only command line entrypoint for shadow observation collection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable, List, Optional

from robot_kb.repository import KnowledgeBase

from .collectors import (
    GCC_MAX_PAGES,
    GCC_MAX_PAGE_SIZE,
    GCC_MAX_RECORDS,
    GCCMarketplaceCollector,
    TCGdexCollector,
    load_gcc_fixture,
    load_tcgdex_fixture,
    utc_now,
)
from .models import CollectionResult
from .persistence import ShadowKnowledgePersistence
from .runner import ShadowSidecar


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m robot_kb.sidecar",
        description=(
            "Manual read-only collector for the isolated Robot KB shadow ledger. "
            "It never scores, alerts, buys, bids, checks out, or mutates V4 state."
        ),
    )
    parser.add_argument(
        "--database",
        default=os.getenv("ROBOT_KB_DATABASE", ":memory:"),
        help="local/replay SQLite path (default: ROBOT_KB_DATABASE or :memory:)",
    )
    parser.add_argument(
        "--gcc-fixture",
        action="append",
        default=[],
        metavar="JSON",
        help="replay a GCC row/page fixture",
    )
    parser.add_argument(
        "--tcgdex-fixture",
        action="append",
        default=[],
        metavar="JSON",
        help="replay a TCGdex card fixture",
    )
    parser.add_argument(
        "--observed-at",
        help="timezone-aware retrieval timestamp for fixtures (default: now UTC)",
    )
    parser.add_argument(
        "--live-gcc",
        action="append",
        choices=("fixed", "auction"),
        default=[],
        help="manually fetch one GCC inventory mode",
    )
    parser.add_argument(
        "--live-tcgdex-card",
        action="append",
        default=[],
        metavar="LANG:CARD_ID",
        help="manually fetch one TCGdex card response",
    )
    parser.add_argument(
        "--allow-live-read-only",
        action="store_true",
        help="required guard for explicit live GET requests; never enables scheduling",
    )
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-records", type=int, default=500)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    for name, value, ceiling in (
        ("--page-size", args.page_size, GCC_MAX_PAGE_SIZE),
        ("--max-pages", args.max_pages, GCC_MAX_PAGES),
        ("--max-records", args.max_records, GCC_MAX_RECORDS),
    ):
        if not 1 <= value <= ceiling:
            parser.error(f"{name} must be between 1 and {ceiling}")
    live_requested = bool(args.live_gcc or args.live_tcgdex_card)
    if live_requested and not args.allow_live_read_only:
        parser.error("live GET requests require --allow-live-read-only")
    if not (
        args.gcc_fixture
        or args.tcgdex_fixture
        or args.live_gcc
        or args.live_tcgdex_card
    ):
        parser.error("select at least one fixture or explicit live read-only source")

    observed_at = args.observed_at or utc_now()
    jobs: list[tuple[str, Callable[[], CollectionResult]]] = []
    for raw_path in args.gcc_fixture:
        path = Path(raw_path)
        jobs.append(
            (
                f"gcc-fixture:{path.name}",
                lambda path=path: load_gcc_fixture(path, retrieved_at=observed_at),
            )
        )
    for raw_path in args.tcgdex_fixture:
        path = Path(raw_path)
        jobs.append(
            (
                f"tcgdex-fixture:{path.name}",
                lambda path=path: load_tcgdex_fixture(
                    path, retrieved_at=observed_at
                ),
            )
        )

    gcc_collector = GCCMarketplaceCollector()
    for mode in args.live_gcc:
        jobs.append(
            (
                f"gcc-live:{mode}",
                lambda mode=mode: gcc_collector.collect(
                    mode,
                    page_size=args.page_size,
                    max_pages=args.max_pages,
                    max_records=args.max_records,
                ),
            )
        )
    tcgdex_collector = TCGdexCollector()
    for specification in args.live_tcgdex_card:
        language, separator, card_id = specification.partition(":")
        if not separator or not language.strip() or not card_id.strip():
            parser.error("--live-tcgdex-card must use LANG:CARD_ID")
        jobs.append(
            (
                f"tcgdex-live:{language}:{card_id}",
                lambda language=language, card_id=card_id: (
                    tcgdex_collector.collect_card(language, card_id)
                ),
            )
        )

    with KnowledgeBase.open(args.database) as knowledge_base:
        sidecar = ShadowSidecar(ShadowKnowledgePersistence(knowledge_base))
        diagnostics = sidecar.run_sources(jobs)
    print(json.dumps(diagnostics.as_dict(), indent=2, sort_keys=True))
    return 1 if diagnostics.source_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
