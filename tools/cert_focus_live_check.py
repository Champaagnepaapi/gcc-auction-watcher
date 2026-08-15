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
PCA_SAMPLE_URL = "https://gradedcardcenter.com/item/388a81b3-5993-4269-bda2-e5d5ac175689"


def _inspect_pca_sample(page):
    lot = watcher.Lot(
        url=PCA_SAMPLE_URL,
        title="PCA live cert smoke sample",
        current_price=None,
        source_type="fixed",
        grader="PCA",
        grade="9.5",
    )
    inspected = watcher.inspect_item(page, lot)
    return inspected, hunter._serial_from_lot(inspected), hunter._numeric_grade(inspected.grade)


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

        inspected, serial, metadata_grade = _inspect_pca_sample(page)
        if inspected.inspection_error or not serial:
            print(
                f"CERT_CHECK grader=PCA status=NO_SERIAL grade=None "
                f"inspection_error={inspected.inspection_error or 'none'}",
                flush=True,
            )
        else:
            cert = router.resolve_grader_certificate(page, "PCA", serial)
            print(
                f"CERT_CHECK grader=PCA metadata={metadata_grade} status={cert.status} "
                f"grade={cert.grade} listing={inspected.url}",
                flush=True,
            )
        browser.close()


if __name__ == "__main__":
    main()
