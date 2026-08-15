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
import v4_mislisted_ocr_hardening as ocr_hardening
import v4_mislisted_slab_hunter as hunter

FOCUS = ("PSA", "PCA", "CCC")
TARGETS = {"PSA": 17, "PCA": 17, "CCC": 16}
SAMPLE_SIZE = 50
SEED = 20260815
OUT = Path("ocr_benchmark_50_results.json")


def _grade(value):
    return hunter._numeric_grade(value)


def _sample_focus(lots):
    rng = random.Random(SEED)
    groups = defaultdict(list)
    for lot in lots:
        grader = (lot.grader or "").strip().upper()
        if grader not in FOCUS or _grade(lot.grade) is None:
            continue
        groups[grader].append(lot)
    for grader in FOCUS:
        rng.shuffle(groups[grader])

    selected = []
    for grader in FOCUS:
        selected.extend(groups[grader][: TARGETS[grader]])
        groups[grader] = groups[grader][TARGETS[grader] :]

    while len(selected) < SAMPLE_SIZE:
        progressed = False
        for grader in FOCUS:
            if groups[grader] and len(selected) < SAMPLE_SIZE:
                selected.append(groups[grader].pop())
                progressed = True
        if not progressed:
            break
    rng.shuffle(selected)
    return selected[:SAMPLE_SIZE]


def main():
    diagnostics = watcher.RunDiagnostics()
    lots = watcher.collect_fixed_lots_from_api(diagnostics, page_size=100, max_pages=12)
    sample = _sample_focus(lots)
    inventory = Counter((lot.grader or "").strip().upper() for lot in lots)
    print(
        "OCR50_INPUT " + json.dumps({"candidates": len(lots), "sample": len(sample), "focus_inventory": {g: inventory[g] for g in FOCUS}}, sort_keys=True),
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
                ocr_grade, status = ocr_hardening.resolve_image_grade_from_page(page, grader)
                record["ocr_grade"] = ocr_grade
                record["ocr_status"] = status
                if status == "OK" and ocr_grade is not None:
                    record["outcome"] = "MATCH_METADATA" if abs(ocr_grade - expected) < 1e-9 else "DIFF_METADATA_REVIEW"
                elif status == hunter.IMAGE_GRADE_AMBIGUOUS:
                    record["outcome"] = "AMBIGUOUS"
            except Exception as exc:
                record["error"] = type(exc).__name__
            results.append(record)
            print(
                f"OCR50_CASE {index:02d}/{len(sample)} {grader} metadata={expected:g} "
                f"ocr={record['ocr_grade']} status={record['ocr_status']} outcome={record['outcome']}",
                flush=True,
            )
        browser.close()

    counts = Counter(r["outcome"] for r in results)
    readable = counts["MATCH_METADATA"] + counts["DIFF_METADATA_REVIEW"]
    per_grader = {}
    for grader in FOCUS:
        subset = [r for r in results if r["grader"] == grader]
        c = Counter(r["outcome"] for r in subset)
        rcount = c["MATCH_METADATA"] + c["DIFF_METADATA_REVIEW"]
        per_grader[grader] = {
            "sample": len(subset),
            "match_metadata": c["MATCH_METADATA"],
            "diff_metadata_review": c["DIFF_METADATA_REVIEW"],
            "ambiguous": c["AMBIGUOUS"],
            "unavailable": c["UNAVAILABLE"],
            "readable": rcount,
            "metadata_concordance_when_readable_pct": round(c["MATCH_METADATA"] / rcount * 100.0, 1) if rcount else 0.0,
        }

    summary = {
        "sample_size": len(results),
        "match_metadata": counts["MATCH_METADATA"],
        "diff_metadata_review": counts["DIFF_METADATA_REVIEW"],
        "ambiguous": counts["AMBIGUOUS"],
        "unavailable": counts["UNAVAILABLE"],
        "readable": readable,
        "metadata_concordance_when_readable_pct": round(counts["MATCH_METADATA"] / readable * 100.0, 1) if readable else 0.0,
        "coverage_readable_pct": round(readable / len(results) * 100.0, 1) if results else 0.0,
        "per_grader": per_grader,
        "roi": {
            "PSA": ocr_hardening.OCR_LABEL_ROIS["PSA"],
            "PCA": ocr_hardening.OCR_LABEL_ROIS["PCA"],
            "CCC": ocr_hardening.OCR_LABEL_ROIS["CCC"],
        },
        "note": "DIFF_METADATA_REVIEW is not labelled OCR wrong because metadata itself can be mislisted; manual/certificate confirmation is required.",
    }
    OUT.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OCR50_SUMMARY " + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
