from __future__ import annotations

from collections import Counter

import requests
from playwright.sync_api import sync_playwright

import watcher
import v4_cert_problem_notifications as cert_alerts
import v4_mislisted_slab_hunter as hunter

API = "https://api.gradedcardcenter.com/on-sale-items"
FOCUS = {"PSA", "PCA", "CCC"}
LIMIT = 100


def nested_item(row: dict) -> dict:
    return row.get("item") if isinstance(row.get("item"), dict) else {}


def api_serial(row: dict) -> str:
    item = nested_item(row)
    for key in ("serialNumber", "certificationNumber", "certificateNumber", "certNumber"):
        for source in (item, row):
            value = cert_alerts._digits(source.get(key))
            if value:
                return value
    return ""


def api_grader(row: dict) -> str:
    item = nested_item(row)
    for key in ("gradingCompany", "grader", "gradingCompanyName"):
        for source in (item, row):
            value = str(source.get(key) or "").strip().upper()
            if value.startswith("PSA"):
                return "PSA"
            if value.startswith("PCA"):
                return "PCA"
            if value.startswith("CCC"):
                return "CCC"
            if value:
                return value
    return ""


def api_grade(row: dict) -> str:
    item = nested_item(row)
    for key in ("grade", "gradingGrade", "score"):
        for source in (item, row):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def collect_rows() -> list[dict]:
    selected: list[dict] = []
    page_number = 1
    while len(selected) < LIMIT and page_number <= 12:
        response = requests.get(
            API,
            params={
                "sellingTypes": "FIXED_PRICE",
                "categories": "Pokemon",
                "itemTypes": "CARDS",
                "page": page_number,
                "limit": 100,
                "includeCounts": "true" if page_number == 1 else "false",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if isinstance(row, dict) and api_grader(row) in FOCUS:
                selected.append(row)
                if len(selected) == LIMIT:
                    break
        page_number += 1
    return selected


def main() -> int:
    rows = collect_rows()
    counts = Counter()
    examples: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        for index, row in enumerate(rows, start=1):
            native_id = str(row.get("id") or "").strip()
            if not native_id:
                continue
            url = f"https://gradedcardcenter.com/item/{native_id}"
            grader = api_grader(row)
            grade = api_grade(row)
            api_cert = api_serial(row)
            counts["sampled"] += 1
            counts[f"grader_{grader}"] += 1
            counts["api_cert_present" if api_cert else "api_cert_missing"] += 1

            lot = watcher.Lot(
                url=url,
                title=f"{grader} {grade}".strip(),
                current_price=None,
                source_type="fixed",
                grader=grader,
                grade=grade or None,
                commercial_dimensions=({"cert_number": api_cert} if api_cert else {}),
            )
            inspected = watcher.inspect_item(page, lot, log_listing_errors=False)
            raw_post = hunter._serial_from_lot(inspected)
            preserved = cert_alerts._preserve_serial_after_inspection(lot, inspected)
            preserved_cert = hunter._serial_from_lot(preserved)
            panel_cert = cert_alerts._serial_from_gradation_panel(page, url)

            if raw_post:
                counts["raw_post_inspect_cert_present"] += 1
            if preserved_cert:
                counts["post_preserve_cert_present"] += 1
            if api_cert and preserved_cert == api_cert:
                counts["post_preserve_matches_api"] += 1
            if panel_cert:
                counts["gradation_fallback_present"] += 1
            if api_cert and panel_cert == api_cert:
                counts["gradation_matches_api"] += 1
            elif api_cert and panel_cert and panel_cert != api_cert:
                counts["gradation_conflicts_api"] += 1
            elif api_cert and not panel_cert:
                counts["gradation_missing_despite_api"] += 1

            if len(examples) < 12 and (
                api_cert != preserved_cert or api_cert != panel_cert
            ):
                examples.append(
                    f"{index:03d} {grader} id={native_id} api={api_cert or '-'} "
                    f"raw_post={raw_post or '-'} preserved={preserved_cert or '-'} "
                    f"gradation={panel_cert or '-'}"
                )
        browser.close()

    print("=== GCC CERT FIX REGRESSION 100 ===")
    for key in (
        "sampled", "grader_PSA", "grader_PCA", "grader_CCC",
        "api_cert_present", "api_cert_missing",
        "raw_post_inspect_cert_present",
        "post_preserve_cert_present", "post_preserve_matches_api",
        "gradation_fallback_present", "gradation_matches_api",
        "gradation_conflicts_api", "gradation_missing_despite_api",
    ):
        print(f"{key}={counts[key]}")
    print("--- discrepancies ---")
    for line in examples:
        print(line)
    print("READ_ONLY=true NO_NTFY=true NO_BID=true NO_PURCHASE=true NO_CHECKOUT=true")

    if counts["sampled"] != LIMIT:
        raise SystemExit(f"Expected {LIMIT} cards, got {counts['sampled']}")
    if counts["api_cert_present"] != LIMIT:
        raise SystemExit("API cert coverage unexpectedly below 100/100")
    if counts["post_preserve_matches_api"] != LIMIT:
        raise SystemExit("Structured cert preservation regression")
    if counts["gradation_matches_api"] != LIMIT:
        raise SystemExit("Description -> Gradation fallback regression")
    if counts["gradation_conflicts_api"] or counts["gradation_missing_despite_api"]:
        raise SystemExit("Gradation panel disagrees with API cert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
