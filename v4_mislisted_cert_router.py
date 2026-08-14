from __future__ import annotations

import re
from typing import Optional

import v4_mislisted_slab_hunter as hunter


CCC_VERIFY_URL = "https://cccgrading.com/fr/verification-carte-ccc"


def parse_grade_from_ocr_text(raw_text: str, grader: str) -> tuple[Optional[float], str]:
    """Strict OCR parser: one unique plausible grade or no grade at all."""
    grader = (grader or "").strip().upper()
    lines = [re.sub(r"\s+", " ", line).strip() for line in (raw_text or "").splitlines() if line.strip()]
    candidates: list[float] = []
    strong_tokens = (
        grader,
        "GRADE",
        "NOTE",
        "MINT",
        "GEM",
        "NEUF",
        "PRISTINE",
        "EXCELLENT",
        "SURFACE",
        "CORNERS",
        "COINS",
        "EDGES",
        "COTES",
        "CÔTÉS",
        "CENTERING",
        "CENTRAGE",
    )
    for line in lines[:12]:
        upper = line.upper().replace(",", ".")
        if not any(token and token in upper for token in strong_tokens):
            continue
        for match in re.finditer(r"(?<!\d)(10|9\.5|9|8\.5|8|7|6|5|4|3|2|1)(?!\d)", upper):
            grade = hunter._numeric_grade(match.group(1))
            if grade is not None:
                candidates.append(grade)
    if not candidates:
        for line in lines[:8]:
            compact = line.strip().replace(",", ".")
            if len(compact) <= 18:
                match = re.fullmatch(r".*?\b(10|9\.5|9|8\.5|8|7|6|5|4|3|2|1)\b.*", compact)
                if match:
                    grade = hunter._numeric_grade(match.group(1))
                    if grade is not None:
                        candidates.append(grade)
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0], "OK"
    if len(unique) > 1:
        return None, hunter.IMAGE_GRADE_AMBIGUOUS
    return None, hunter.IMAGE_GRADE_UNAVAILABLE


def resolve_ccc_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number or page is None:
        return hunter.GraderCertificate(cert_number, None, status=hunter.CERT_UNAVAILABLE, grader="CCC")

    cache_key = ("CCC", cert_number)
    cached = hunter._CERT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if hunter._CERT_LOOKUPS >= hunter.MAX_CERT_LOOKUPS_PER_RUN:
        return hunter.GraderCertificate(cert_number, None, status=hunter.CERT_UNAVAILABLE, grader="CCC")

    hunter._CERT_LOOKUPS += 1
    verification_page = None
    try:
        verification_page = page.context.new_page()
        verification_page.goto(CCC_VERIFY_URL, wait_until="domcontentloaded", timeout=8000)

        filled = False
        inputs = verification_page.locator("input")
        for index in range(inputs.count()):
            candidate = inputs.nth(index)
            try:
                if candidate.is_visible():
                    candidate.fill(cert_number)
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            raise RuntimeError("CCC cert input unavailable")

        button = verification_page.get_by_role("button", name=re.compile(r"V[ée]rifier|Check", re.I))
        if button.count() == 0:
            button = verification_page.locator("button").filter(has_text=re.compile(r"V[ée]rifier|Check", re.I))
        button.first.click(timeout=3000)
        try:
            verification_page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            verification_page.wait_for_timeout(1200)

        text = verification_page.locator("body").inner_text(timeout=3000)
        certificate = hunter.parse_ccc_verification_text(text, cert_number)
    except Exception as error:
        hunter.watcher.log(f"Mislisted slab: CCC cert indisponible ({type(error).__name__})")
        certificate = hunter.GraderCertificate(cert_number, None, status=hunter.CERT_UNAVAILABLE, grader="CCC")
    finally:
        if verification_page is not None:
            try:
                verification_page.close()
            except Exception:
                pass

    hunter._CERT_CACHE[cache_key] = certificate
    return certificate


def resolve_grader_certificate(page, grader: str, cert_number: str) -> hunter.GraderCertificate:
    grader = (grader or "").strip().upper()
    if grader == "PSA":
        return hunter.resolve_psa_certificate(cert_number)
    if grader == "CCC":
        return resolve_ccc_certificate(page, cert_number)
    # Unsupported official verifier: OCR fallback remains available downstream.
    return hunter.GraderCertificate(cert_number, None, status=hunter.CERT_UNAVAILABLE, grader=grader)


def install_v4_mislisted_cert_router() -> None:
    hunter.resolve_grader_certificate = resolve_grader_certificate
    hunter.parse_grade_from_ocr_text = parse_grade_from_ocr_text
