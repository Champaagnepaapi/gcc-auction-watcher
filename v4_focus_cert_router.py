from __future__ import annotations

import re
from typing import Callable

import v4_mislisted_cert_router as router
import v4_mislisted_slab_hunter as hunter


PSA_DIRECT_URL = "https://www.psacard.com/cert/{cert_number}"
PCA_DIRECT_URL = "https://pcagrade.com/fr/check-certification/{cert_number}"
CCC_VERIFY_URL = "https://cccgrading.com/fr/verification-carte-ccc"
FOCUS_GRADERS = frozenset({"PSA", "PCA", "CCC"})
_INSTALLED = False


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _unavailable(grader: str, cert_number: str) -> hunter.GraderCertificate:
    return hunter.GraderCertificate(
        _digits(cert_number),
        None,
        status=hunter.CERT_UNAVAILABLE,
        grader=grader,
    )


def _new_verification_page(page, url: str):
    verification_page = page.context.new_page()
    verification_page.goto(url, wait_until="domcontentloaded", timeout=9000)
    try:
        verification_page.wait_for_load_state("networkidle", timeout=4500)
    except Exception:
        verification_page.wait_for_timeout(900)
    return verification_page


def resolve_psa_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    """Use a real browser page; GitHub Actions HTTP requests are WAF-blocked by PSA."""
    cert_number = _digits(cert_number)
    if not cert_number or page is None:
        return _unavailable("PSA", cert_number)

    cached, allowed = router._cache_or_budget("PSA", cert_number)
    if not allowed:
        return cached

    verification_page = None
    try:
        verification_page = _new_verification_page(
            page,
            PSA_DIRECT_URL.format(cert_number=cert_number),
        )
        certificate = hunter.parse_psa_certificate_html(
            verification_page.content(),
            cert_number,
        )
    except Exception as error:
        hunter.watcher.log(
            f"Mislisted slab: PSA browser cert indisponible ({type(error).__name__})"
        )
        certificate = _unavailable("PSA", cert_number)
    finally:
        if verification_page is not None:
            try:
                verification_page.close()
            except Exception:
                pass
    return router._cache_certificate(certificate)


def resolve_pca_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    """PCA exposes a stable public direct certification URL."""
    cert_number = _digits(cert_number)
    if not cert_number or page is None:
        return _unavailable("PCA", cert_number)

    cached, allowed = router._cache_or_budget("PCA", cert_number)
    if not allowed:
        return cached

    verification_page = None
    try:
        verification_page = _new_verification_page(
            page,
            PCA_DIRECT_URL.format(cert_number=cert_number),
        )
        text = verification_page.locator("body").inner_text(timeout=3000)
        certificate = router.parse_official_grade_text(text, cert_number, "PCA")
    except Exception as error:
        hunter.watcher.log(
            f"Mislisted slab: PCA direct cert indisponible ({type(error).__name__})"
        )
        certificate = _unavailable("PCA", cert_number)
    finally:
        if verification_page is not None:
            try:
                verification_page.close()
            except Exception:
                pass
    return router._cache_certificate(certificate)


def _first_visible_cert_input(verification_page):
    inputs = verification_page.locator("input")
    best = None
    best_score = -1
    for index in range(inputs.count()):
        candidate = inputs.nth(index)
        try:
            input_type = (candidate.get_attribute("type") or "text").lower()
            if not candidate.is_visible() or input_type in {
                "hidden",
                "submit",
                "button",
                "checkbox",
                "radio",
                "email",
                "password",
            }:
                continue
            descriptor = " ".join(
                candidate.get_attribute(attr) or ""
                for attr in ("placeholder", "name", "id", "aria-label")
            ).casefold()
            score = 1
            if any(
                token in descriptor
                for token in ("cert", "authentic", "numéro", "numero", "number")
            ):
                score += 10
            if input_type in {"text", "number", "search"}:
                score += 2
            if score > best_score:
                best = candidate
                best_score = score
        except Exception:
            continue
    return best


def _submit_ccc_form(verification_page, input_locator) -> None:
    # Enter is more robust than relying on a specific translated button tag.
    try:
        input_locator.press("Enter", timeout=2500)
        return
    except Exception:
        pass

    submitters = verification_page.locator(
        'button, input[type="submit"], [role="button"]'
    )
    for index in range(submitters.count()):
        candidate = submitters.nth(index)
        try:
            text = " ".join(
                filter(
                    None,
                    (
                        candidate.inner_text(timeout=500),
                        candidate.get_attribute("value"),
                        candidate.get_attribute("aria-label"),
                    ),
                )
            )
            if re.search(r"V[ée]rifier|authenticit[ée]|Check|Verify", text, re.I):
                candidate.click(timeout=2500)
                return
        except Exception:
            continue
    raise RuntimeError("CCC verification submitter unavailable")


def resolve_ccc_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    cert_number = _digits(cert_number)
    if not cert_number or page is None:
        return _unavailable("CCC", cert_number)

    cached, allowed = router._cache_or_budget("CCC", cert_number)
    if not allowed:
        return cached

    verification_page = None
    try:
        verification_page = _new_verification_page(page, CCC_VERIFY_URL)
        cert_input = _first_visible_cert_input(verification_page)
        if cert_input is None:
            raise RuntimeError("CCC cert input unavailable")
        cert_input.fill(cert_number)
        _submit_ccc_form(verification_page, cert_input)
        try:
            verification_page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            verification_page.wait_for_timeout(1400)
        text = verification_page.locator("body").inner_text(timeout=3000)
        certificate = hunter.parse_ccc_verification_text(text, cert_number)
    except Exception as error:
        hunter.watcher.log(
            f"Mislisted slab: CCC browser cert indisponible ({type(error).__name__})"
        )
        certificate = _unavailable("CCC", cert_number)
    finally:
        if verification_page is not None:
            try:
                verification_page.close()
            except Exception:
                pass
    return router._cache_certificate(certificate)


def resolve_focus_grader_certificate(
    page,
    grader: str,
    cert_number: str,
) -> hunter.GraderCertificate:
    grader = router._normalize_grader(grader)
    if grader == "PSA":
        return resolve_psa_certificate(page, cert_number)
    if grader == "PCA":
        return resolve_pca_certificate(page, cert_number)
    if grader == "CCC":
        return resolve_ccc_certificate(page, cert_number)
    return router.resolve_grader_certificate(page, grader, cert_number)


def install_v4_focus_cert_router() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    hunter.resolve_grader_certificate = resolve_focus_grader_certificate
    _INSTALLED = True
