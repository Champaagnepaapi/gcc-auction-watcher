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

import v4_focus_cert_router as focus_router
import v4_mislisted_slab_hunter as hunter


# Read-only smoke checks: no bid/buy/checkout and no notification.
# PCA example is a public certification URL from a live marketplace listing.
KNOWN = (
    ("PSA", "131216316", 10.0),
    ("PCA", "76676760", 9.5),
    ("CCC", "544340143", 9.0),
)


def main():
    hunter._CERT_LOOKUPS = 0
    hunter._CERT_CACHE.clear()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})

        for grader, cert_number, expected in KNOWN:
            cert = focus_router.resolve_focus_grader_certificate(
                page,
                grader,
                cert_number,
            )
            match = cert.status == "OK" and cert.grade == expected
            print(
                f"CERT_CHECK grader={grader} expected={expected:g} "
                f"status={cert.status} grade={cert.grade} match={match}",
                flush=True,
            )
        browser.close()


if __name__ == "__main__":
    main()
