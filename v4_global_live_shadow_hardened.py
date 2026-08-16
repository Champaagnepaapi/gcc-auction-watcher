from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import v4_global_live_shadow as base
from v4_global_retrieval_hardening_v2 import (
    collect_comc_v2,
    collect_fanatics_v2,
    collect_magi_v2,
    traces_to_json,
)


def run(args: argparse.Namespace) -> dict:
    observed_at = base.now_utc()
    diagnostics = base.japan.Diagnostics()
    sales = base.japan.fetch_gcc(max_pages=max(1, args.gcc_sold_pages), diag=diagnostics)
    seeds = base.build_seed_panel(sales, observed_at=observed_at, max_identities=max(1, args.max_identities))
    fx_converter = base.ECBCurrencyConverter()
    fx = base._fx_map(fx_converter)
    rows = {}
    statuses = []
    traces = []

    gcc_rows, gcc_status = base.fetch_gcc_live(
        seeds,
        observed_at=observed_at,
        max_pages_each=max(1, args.gcc_live_pages),
    )
    rows["gcc"] = gcc_rows
    statuses.append(gcc_status)

    cardova_rows, cardova_status = base.load_cardova(
        seeds,
        observed_at=observed_at,
        fixed_path=Path(args.cardova_fixed_json) if args.cardova_fixed_json else None,
        auction_path=Path(args.cardova_auction_json) if args.cardova_auction_json else None,
    )
    rows["cardova"] = cardova_rows
    statuses.append(cardova_status)

    if not args.no_browser_sources and seeds:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()

            magi_rows, magi_status, magi_trace = collect_magi_v2(
                page,
                seeds,
                observed_at=observed_at,
                max_candidates=args.market_candidates,
            )
            rows["magi"] = magi_rows
            statuses.append(magi_status)
            traces.append(magi_trace)

            fanatics_rows, fanatics_status, fanatics_trace = collect_fanatics_v2(
                page,
                seeds,
                observed_at=observed_at,
                max_candidates=args.market_candidates,
            )
            rows["fanatics"] = fanatics_rows
            statuses.append(fanatics_status)
            traces.append(fanatics_trace)

            comc_rows, comc_status, comc_trace = collect_comc_v2(
                page,
                seeds,
                observed_at=observed_at,
                max_candidates=args.market_candidates,
            )
            rows["comc"] = comc_rows
            statuses.append(comc_status)
            traces.append(comc_trace)

            context.close()
            browser.close()
    else:
        for market in ("magi", "fanatics", "comc"):
            rows[market] = {seed.identity.strict_key: [] for seed in seeds}
            statuses.append(base.SourceStatus(market, "SKIPPED", "browser sources disabled"))

    report = base.build_report(seeds, rows, fx=fx, statuses=statuses, observed_at=observed_at)
    report["retrieval_hardening"] = {
        "version": 2,
        "magi": "Pokemon/PSA10 priority before cap + detail rejection reasons",
        "fanatics": "anchor + embedded buy-now/fixed route recovery + era-normalized exact set/localId proof",
        "comc": "direct player fallback + exact metadata/localId + PSA10 row-bound price",
        "identity_gate_relaxed": False,
    }
    report["retrieval_diagnostics"] = traces_to_json(*traces)
    report["gcc_sold_diagnostics"] = asdict(diagnostics)
    report["fx"] = {
        "provider": "ECB",
        "currency_per_eur": fx,
        "available": bool(fx),
    }
    base.write_report(report, Path(args.output_dir))
    return report


def parser() -> argparse.ArgumentParser:
    return base.parser()


def main() -> int:
    args = parser().parse_args()
    report = run(args)
    print(
        json.dumps(
            {
                "mode": report.get("mode"),
                "cards": len(report.get("cards", [])),
                "source_status": report.get("source_status", []),
                "retrieval_hardening": report.get("retrieval_hardening"),
                "retrieval_diagnostics": [
                    {
                        "market": row.get("market"),
                        "reject_reasons": row.get("reject_reasons"),
                    }
                    for row in report.get("retrieval_diagnostics", [])
                ],
                "output": str(Path(args.output_dir).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
