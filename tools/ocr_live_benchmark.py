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
import v4_mislisted_slab_hunter as hunter


SAMPLE_SIZE = 24
SEED = 20260814
OUT = Path("ocr_benchmark_results.json")


def _grade(value):
    return hunter._numeric_grade(value)


def _sample_diverse(lots, size):
    rng = random.Random(SEED)
    groups = defaultdict(list)
    for lot in lots:
        if _grade(lot.grade) is None or not (lot.grader or "").strip():
            continue
        groups[(lot.grader or "").strip().upper()].append(lot)
    for group in groups.values():
        rng.shuffle(group)

    selected = []
    graders = sorted(groups)
    rng.shuffle(graders)
    while len(selected) < size and graders:
        next_round = []
        for grader in graders:
            if groups[grader] and len(selected) < size:
                selected.append(groups[grader].pop())
            if groups[grader]:
                next_round.append(grader)
        graders = next_round
    return selected


def main():
    diagnostics = watcher.RunDiagnostics()
    lots = watcher.collect_fixed_lots_from_api(
        diagnostics,
        page_size=100,
        max_pages=4,
    )
    sample = _sample_diverse(lots, SAMPLE_SIZE)
    print(f"OCR_BENCHMARK candidates={len(lots)} sample={len(sample)} seed={SEED}", flush=True)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1600})
        for index, lot in enumerate(sample, 1):
            expected = _grade(lot.grade)
            record = {
                "index": index,
                "url": lot.url,
                "title": lot.title,
                "grader": (lot.grader or "").strip().upper(),
                "metadata_grade": expected,
                "ocr_grade": None,
                "ocr_status": hunter.IMAGE_GRADE_UNAVAILABLE,
                "outcome": "UNAVAILABLE",
            }
            try:
                page.goto(lot.url, wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(900)
                ocr_grade, status = hunter.resolve_image_grade_from_page(page, lot.grader)
                record["ocr_grade"] = ocr_grade
                record["ocr_status"] = status
                if status == "OK" and ocr_grade is not None:
                    record["outcome"] = "EXACT" if abs(ocr_grade - expected) < 1e-9 else "WRONG"
                elif status == hunter.IMAGE_GRADE_AMBIGUOUS:
                    record["outcome"] = "AMBIGUOUS"
            except Exception as exc:
                record["error"] = type(exc).__name__
            results.append(record)
            print(
                f"OCR_CASE {index:02d}/{len(sample)} {record['grader']} metadata={expected:g} "
                f"ocr={record['ocr_grade']} status={record['ocr_status']} outcome={record['outcome']} "
                f"{lot.url}",
                flush=True,
            )
        browser.close()

    counts = Counter(r["outcome"] for r in results)
    readable = counts["EXACT"] + counts["WRONG"]
    exact_rate_readable = (counts["EXACT"] / readable * 100.0) if readable else 0.0
    exact_rate_all = (counts["EXACT"] / len(results) * 100.0) if results else 0.0
    summary = {
        "sample_size": len(results),
        "exact": counts["EXACT"],
        "wrong": counts["WRONG"],
        "ambiguous": counts["AMBIGUOUS"],
        "unavailable": counts["UNAVAILABLE"],
        "exact_rate_when_readable_pct": round(exact_rate_readable, 1),
        "exact_rate_all_pct": round(exact_rate_all, 1),
        "grader_counts": dict(Counter(r["grader"] for r in results)),
    }
    OUT.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OCR_BENCHMARK_SUMMARY " + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
