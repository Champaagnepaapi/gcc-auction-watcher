from __future__ import annotations

import re
from collections import Counter

import requests
from playwright.sync_api import sync_playwright

import watcher
import v4_mislisted_slab_hunter as hunter

API = "https://api.gradedcardcenter.com/on-sale-items"
FOCUS = {"PSA", "PCA", "CCC"}
LIMIT = 100


def digits(value: object) -> str:
    raw = re.sub(r"\D", "", str(value or ""))
    return raw if 5 <= len(raw) <= 12 else ""


def nested_item(row: dict) -> dict:
    return row.get("item") if isinstance(row.get("item"), dict) else {}


def api_serial(row: dict) -> str:
    item = nested_item(row)
    for key in ("serialNumber", "certificationNumber", "certificateNumber", "certNumber"):
        for source in (item, row):
            value = digits(source.get(key))
            if value:
                return value
    return ""


def api_grader(row: dict) -> str:
    item = nested_item(row)
    for key in ("gradingCompany", "grader", "gradingCompanyName"):
        for source in (item, row):
            value = str(source.get(key) or "").strip().upper()
            if value:
                if value.startswith("PSA"):
                    return "PSA"
                if value.startswith("PCA"):
                    return "PCA"
                if value.startswith("CCC"):
                    return "CCC"
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


def find_serial_in_text(text: str) -> str:
    patterns = (
        r"(?:Num[ée]ro de s[ée]rie|Serial Number|Certification Number|Num[ée]ro de certification|Cert(?:ification)?(?: Number)?)\s*:?\s*\n?\s*([0-9][0-9 ]{4,14})",
        r"(?:Certification|Certificat)\s*\n\s*([0-9][0-9 ]{4,14})",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", re.I)
        if match:
            value = digits(match.group(1))
            if value:
                return value
    return ""


def click_visible_text(page, pattern: str) -> bool:
    rx = re.compile(pattern, re.I)
    candidates = [
        page.get_by_role("button", name=rx),
        page.get_by_text(rx, exact=True),
    ]
    for locator in candidates:
        try:
            count = min(locator.count(), 8)
        except Exception:
            continue
        for index in range(count):
            node = locator.nth(index)
            try:
                if node.is_visible():
                    node.click(timeout=1200)
                    page.wait_for_timeout(150)
                    return True
            except Exception:
                continue
    return False


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
            if not isinstance(row, dict):
                continue
            if api_grader(row) in FOCUS:
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
            if api_cert:
                counts["api_cert_present"] += 1
            else:
                counts["api_cert_missing"] += 1

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
            post_cert = hunter._serial_from_lot(inspected)
            collapsed_text = inspected.body or ""
            collapsed_cert = find_serial_in_text(collapsed_text)

            if post_cert:
                counts["post_inspect_cert_present"] += 1
            if api_cert and not post_cert:
                counts["api_cert_lost_after_inspect"] += 1
            if collapsed_cert:
                counts["collapsed_text_cert_present"] += 1

            description_clicked = click_visible_text(page, r"^(Description|Détails?|Details?)$")
            gradation_clicked = click_visible_text(page, r"^(Gradation|Grading)$")
            if description_clicked:
                counts["description_clicked"] += 1
            if gradation_clicked:
                counts["gradation_clicked"] += 1

            try:
                expanded_text = page.locator("body").inner_text(timeout=2500)
            except Exception:
                expanded_text = ""
            expanded_cert = find_serial_in_text(expanded_text)
            if expanded_cert:
                counts["expanded_text_cert_present"] += 1
            if api_cert and expanded_cert == api_cert:
                counts["expanded_matches_api"] += 1
            elif api_cert and expanded_cert and expanded_cert != api_cert:
                counts["expanded_conflicts_api"] += 1
            elif api_cert and not expanded_cert:
                counts["expanded_missing_despite_api"] += 1

            if len(examples) < 20 and (api_cert and not post_cert or expanded_cert != api_cert):
                examples.append(
                    f"{index:03d} {grader} id={native_id} api={api_cert or '-'} "
                    f"post_inspect={post_cert or '-'} collapsed={collapsed_cert or '-'} "
                    f"expanded={expanded_cert or '-'} desc_click={description_clicked} grad_click={gradation_clicked}"
                )

        browser.close()

    print("=== GCC CERT PANEL DIAGNOSTIC 100 ===")
    for key in (
        "sampled", "grader_PSA", "grader_PCA", "grader_CCC",
        "api_cert_present", "api_cert_missing",
        "post_inspect_cert_present", "api_cert_lost_after_inspect",
        "collapsed_text_cert_present", "description_clicked", "gradation_clicked",
        "expanded_text_cert_present", "expanded_matches_api",
        "expanded_conflicts_api", "expanded_missing_despite_api",
    ):
        print(f"{key}={counts[key]}")
    print("--- discrepant examples ---")
    for line in examples:
        print(line)
    print("READ_ONLY=true NO_NTFY=true NO_BID=true NO_PURCHASE=true NO_CHECKOUT=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
