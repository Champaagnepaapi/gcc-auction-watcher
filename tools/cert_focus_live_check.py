from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HEADLESS", "true")
os.environ.setdefault("V4_MISLISTED_CERT_MAX_PER_RUN", "10")

from playwright.sync_api import sync_playwright

import watcher
import v4_mislisted_cert_router as router
import v4_mislisted_slab_hunter as hunter


# Read-only smoke checks: no bid/buy/checkout and no notification.
KNOWN = (
    ("PSA", "131216316", 10.0),
    ("CCC", "544340143", 9.0),
)


def _find_pca_listing(page):
    diagnostics = watcher.RunDiagnostics()
    lots = watcher.collect_fixed_lots_from_api(diagnostics, page_size=100, max_pages=8)
    for lot in lots:
        if (lot.grader or "").strip().upper() != "PCA":
            continue
        inspected = lot if lot.body else watcher.inspect_item(page, lot)
        serial = hunter._serial_from_lot(inspected)
        grade = hunter._numeric_grade(inspected.grade)
        if serial and grade is not None:
            return inspected, serial, grade
    return None, "", None


def main():
    hunter._CERT_LOOKUPS = 0
    hunter._CERT_CACHE.clear()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})

        for grader, cert_number, expected in KNOWN:
            cert = router.resolve_grader_certificate(page, grader, cert_number)
            print(
                f"CERT_CHECK grader={grader} expected={expected:g} "
                f"status={cert.status} grade={cert.grade}",
                flush=True,
            )

        lot, serial, expected = _find_pca_listing(page)
        if lot is None:
            print("CERT_CHECK grader=PCA status=NO_SAMPLE grade=None", flush=True)
        else:
            cert = router.resolve_grader_certificate(page, "PCA", serial)
            print(
                f"CERT_CHECK grader=PCA metadata={expected:g} status={cert.status} "
                f"grade={cert.grade} listing={lot.url}",
                flush=True,
            )
        browser.close()


if __name__ == "__main__":
    main()
