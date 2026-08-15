from __future__ import annotations

import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("V4_MISLISTED_IMAGE_OCR_ENABLED", "true")
os.environ.setdefault("HEADLESS", "true")

from playwright.sync_api import sync_playwright

import watcher
import v4_mislisted_ocr_hardening as ocr
import v4_mislisted_slab_hunter as hunter


SAMPLE_PER_GRADER = 8
SEED = 20260815
OUT = Path("ocr_focus_benchmark_results.json")
FOCUS = ("PSA", "PCA", "CCC")


def _grade(value):
    return hunter._numeric_grade(value)


def _sample(lots):
    rng = random.Random(SEED)
    groups = defaultdict(list)
    for lot in lots:
        grader = (lot.grader or "").strip().upper()
        if grader in FOCUS and _grade(lot.grade) is not None:
            groups[grader].append(lot)
    selected = []
    for grader in FOCUS:
        rng.shuffle(groups[grader])
        selected.extend(groups[grader][:SAMPLE_PER_GRADER])
    rng.shuffle(selected)
    return selected


def main():
    diagnostics = watcher.RunDiagnostics()
    lots = watcher.collect_fixed_lots_from_api(
        diagnostics,
        page_size=100,
        max_pages=8,
    )
    sample = _sample(lots)
    print(
        f"OCR_FOCUS_BENCHMARK candidates={len(lots)} sample={len(sample)} seed={SEED}",
        flush=True,
    )

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1600})
        for index, lot in enumerate(sample, 1):
            expected = _grade(lot.grade)
            grader = (lot.grader or "").strip().upper()
            record = {
                "index": index,
                "url": lot.url,
                "grader": grader,
                "metadata_grade": expected,
                "ocr_grade": None,
                "ocr_status": hunter.IMAGE_GRADE_UNAVAILABLE,
                "outcome": "UNAVAILABLE",
            }
            try:
                page.goto(lot.url, wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(700)
                grade, status = ocr.resolve_image_grade_from_page(page, grader)
                record["ocr_grade"] = grade
                record["ocr_status"] = status
                if status == "OK" and grade is not None:
                    record["outcome"] = "EXACT" if abs(grade - expected) < 1e-9 else "WRONG"
                elif status == hunter.IMAGE_GRADE_AMBIGUOUS:
                    record["outcome"] = "AMBIGUOUS"
            except Exception as exc:
                record["error"] = type(exc).__name__
            results.append(record)
            print(
                f"OCR_CASE {index:02d}/{len(sample)} {grader} metadata={expected:g} "
                f"ocr={record['ocr_grade']} status={record['ocr_status']} "
                f"outcome={record['outcome']} {lot.url}",
                flush=True,
            )
        browser.close()

    counts = Counter(r["outcome"] for r in results)
    readable = counts["EXACT"] + counts["WRONG"]
    summary = {
        "sample_size": len(results),
        "exact": counts["EXACT"],
        "wrong": counts["WRONG"],
        "ambiguous": counts["AMBIGUOUS"],
        "unavailable": counts["UNAVAILABLE"],
        "exact_rate_when_readable_pct": round((counts["EXACT"] / readable * 100.0) if readable else 0.0, 1),
        "exact_rate_all_pct": round((counts["EXACT"] / len(results) * 100.0) if results else 0.0, 1),
        "grader_counts": dict(Counter(r["grader"] for r in results)),
    }
    OUT.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("OCR_FOCUS_BENCHMARK_SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
