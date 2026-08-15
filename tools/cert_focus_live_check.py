from __future__ import annotations

import os
import re
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


KNOWN = (
    ("PSA", "131216316", 10.0),
    ("PCA", "76676760", 9.5),
    ("CCC", "544340143", 9.0),
)


def _interesting(text: str, cert_number: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    hits = []
    for index, line in enumerate(lines):
        folded = line.casefold()
        if cert_number in re.sub(r"\D", "", line) or any(
            token in folded for token in ("grade", "note", "mint", "gem", "neuf", "cert")
        ):
            hits.extend(lines[max(0, index - 1): min(len(lines), index + 3)])
    deduped = []
    for line in hits:
        if line not in deduped:
            deduped.append(line)
    return " | ".join(deduped)[:2400]


def _diagnose_text(page, grader: str, cert_number: str) -> None:
    context = None
    try:
        if grader == "PSA":
            context, verify = focus_router._new_verification_page(
                page, focus_router.PSA_DIRECT_URL.format(cert_number=cert_number)
            )
        elif grader == "PCA":
            context, verify = focus_router._new_verification_page(
                page, focus_router.PCA_DIRECT_URL.format(cert_number=cert_number)
            )
        else:
            context, verify = focus_router._new_verification_page(page, focus_router.CCC_VERIFY_URL)
            field = focus_router._first_visible_cert_input(verify)
            if field is not None:
                field.fill(cert_number)
                focus_router._submit_ccc_form(verify, field)
                verify.wait_for_timeout(1600)
        text = verify.locator("body").inner_text(timeout=3000)
        print(f"CERT_TEXT grader={grader} :: {_interesting(text, cert_number)}", flush=True)
    except Exception as exc:
        print(f"CERT_TEXT grader={grader} diagnostic_error={type(exc).__name__}", flush=True)
    finally:
        if context is not None:
            context.close()


def main():
    hunter._CERT_LOOKUPS = 0
    hunter._CERT_CACHE.clear()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})

        for grader, cert_number, expected in KNOWN:
            cert = focus_router.resolve_focus_grader_certificate(page, grader, cert_number)
            match = cert.status == "OK" and cert.grade == expected
            print(
                f"CERT_CHECK grader={grader} expected={expected:g} "
                f"status={cert.status} grade={cert.grade} match={match}",
                flush=True,
            )
            if cert.status != "OK":
                _diagnose_text(page, grader, cert_number)
        browser.close()


if __name__ == "__main__":
    main()
