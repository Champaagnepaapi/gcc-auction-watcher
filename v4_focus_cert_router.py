from __future__ import annotations

import re

import v4_mislisted_cert_router as router
import v4_mislisted_slab_hunter as hunter


PSA_DIRECT_URL = "https://www.psacard.com/cert/{cert_number}/psa"
PCA_DIRECT_URL = "https://pcagrade.com/fr/check-certification/{cert_number}"
CCC_VERIFY_URL = "https://cccgrading.com/fr/verification-carte-ccc"
FOCUS_GRADERS = frozenset({"PSA", "PCA", "CCC"})
_INSTALLED = False
_GRADE_RE = re.compile(
    r"(?<!\d)(10(?:\.0)?|9(?:[.,]5|\.0)?|8(?:[.,]5|\.0)?|7(?:[.,]5|\.0)?|"
    r"6(?:[.,]5|\.0)?|5(?:[.,]5|\.0)?|4(?:[.,]5|\.0)?|3(?:[.,]5|\.0)?|"
    r"2(?:[.,]5|\.0)?|1(?:[.,]5|\.0)?)(?!\d)"
)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines() if line.strip()]


def _grade_from_text(value: str):
    match = _GRADE_RE.search((value or "").replace(",", "."))
    return hunter._numeric_grade(match.group(1)) if match else None


def _unavailable(grader: str, cert_number: str) -> hunter.GraderCertificate:
    return hunter.GraderCertificate(
        _digits(cert_number),
        None,
        status=hunter.CERT_UNAVAILABLE,
        grader=grader,
    )


def _safe_error(error: Exception) -> str:
    """Short transport diagnostic; redact URLs/query strings and line breaks."""
    message = re.sub(r"\s+", " ", str(error or "")).strip()
    message = re.sub(r"https?://([^/?\s]+)[^\s]*", r"https://\1/<redacted>", message)
    return message[:220] or type(error).__name__


def _new_verification_page(page, url: str):
    """Open verifier outside browser.new_page()'s single-page owned context."""
    browser = page.context.browser
    if browser is None:
        raise RuntimeError("browser unavailable from listing page")
    verification_context = browser.new_context(
        viewport={"width": 1280, "height": 1100},
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
    )
    verification_page = verification_context.new_page()
    try:
        verification_page.goto(url, wait_until="domcontentloaded", timeout=9000)
        try:
            verification_page.wait_for_load_state("networkidle", timeout=4500)
        except Exception:
            verification_page.wait_for_timeout(900)
        return verification_context, verification_page
    except Exception:
        verification_context.close()
        raise


def parse_psa_verified_text(raw_text: str, cert_number: str) -> hunter.GraderCertificate:
    cert_number = _digits(cert_number)
    lines = _lines(raw_text)
    folded = "\n".join(lines).casefold()
    if cert_number and cert_number not in _digits("\n".join(lines)):
        return _unavailable("PSA", cert_number)
    if "requested certification number" in folded and "not found" in folded:
        return _unavailable("PSA", cert_number)

    for index, line in enumerate(lines):
        if re.fullmatch(r"item\s+grade", line, re.I):
            for candidate in lines[index + 1 : index + 3]:
                grade = _grade_from_text(candidate)
                if grade is not None:
                    return hunter.GraderCertificate(cert_number, grade, status="OK", grader="PSA")
        match = re.match(r"item\s+grade\s*[:\-]?\s*(.+)$", line, re.I)
        if match:
            grade = _grade_from_text(match.group(1))
            if grade is not None:
                return hunter.GraderCertificate(cert_number, grade, status="OK", grader="PSA")

    # PSA result headers commonly render e.g. "GEM MT 10" close to the cert.
    for line in lines[:80]:
        if re.search(r"\b(?:GEM\s*MT|MINT|NM-MT|EX-MT)\b", line, re.I):
            grade = _grade_from_text(line)
            if grade is not None:
                return hunter.GraderCertificate(cert_number, grade, status="OK", grader="PSA")
    return hunter.GraderCertificate(cert_number, None, status=hunter.CERT_GRADE_UNREADABLE, grader="PSA")


def parse_ccc_verified_text(raw_text: str, cert_number: str) -> hunter.GraderCertificate:
    """Parse CCC overall grade without ever promoting a subgrade."""
    cert_number = _digits(cert_number)
    lines = _lines(raw_text)
    if cert_number and cert_number not in _digits("\n".join(lines)):
        return _unavailable("CCC", cert_number)

    parsed = hunter.parse_ccc_verification_text(raw_text, cert_number)
    if parsed.status == "OK" and parsed.grade is not None:
        return parsed

    # Current CCC verifier renders the overall score as a standalone number
    # immediately before the first subgrade label ("Note Centrage"). We only
    # accept a standalone grade in that narrow structural position.
    subgrade_label = re.compile(
        r"^(?:Note\s+)?(?:Centrage|Centering|Coins?|Corners?|C[oô]t[ée]s?|Edges?|Surface)\b",
        re.I,
    )
    for index, line in enumerate(lines):
        if not subgrade_label.search(line):
            continue
        for previous in reversed(lines[max(0, index - 3) : index]):
            normalized = previous.replace(",", ".")
            if re.fullmatch(
                r"10(?:\.0)?|9(?:\.5|\.0)?|8(?:\.5|\.0)?|7(?:\.5|\.0)?|"
                r"6(?:\.5|\.0)?|5(?:\.5|\.0)?|4(?:\.5|\.0)?|3(?:\.5|\.0)?|"
                r"2(?:\.5|\.0)?|1(?:\.5|\.0)?",
                normalized,
            ):
                grade = hunter._numeric_grade(normalized)
                if grade is not None:
                    return hunter.GraderCertificate(cert_number, grade, status="OK", grader="CCC")
            # Stop once we hit a non-value field label; do not search broadly.
            if re.search(r"[A-Za-zÀ-ÿ]", previous):
                break
        break

    return hunter.GraderCertificate(cert_number, None, status=hunter.CERT_GRADE_UNREADABLE, grader="CCC")


def resolve_psa_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    cert_number = _digits(cert_number)
    if not cert_number or page is None:
        return _unavailable("PSA", cert_number)

    cached, allowed = router._cache_or_budget("PSA", cert_number)
    if not allowed:
        return cached

    verification_context = None
    try:
        verification_context, verification_page = _new_verification_page(
            page,
            PSA_DIRECT_URL.format(cert_number=cert_number),
        )
        text = verification_page.locator("body").inner_text(timeout=3000)
        certificate = parse_psa_verified_text(text, cert_number)
    except Exception as error:
        hunter.watcher.log(
            f"Mislisted slab: PSA browser cert indisponible ({type(error).__name__}: {_safe_error(error)})"
        )
        certificate = _unavailable("PSA", cert_number)
    finally:
        if verification_context is not None:
            try:
                verification_context.close()
            except Exception:
                pass
    return router._cache_certificate(certificate)


def resolve_pca_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    """PCA direct cert page; bot challenges fail cleanly to OCR/manual review."""
    cert_number = _digits(cert_number)
    if not cert_number or page is None:
        return _unavailable("PCA", cert_number)

    cached, allowed = router._cache_or_budget("PCA", cert_number)
    if not allowed:
        return cached

    verification_context = None
    try:
        verification_context, verification_page = _new_verification_page(
            page,
            PCA_DIRECT_URL.format(cert_number=cert_number),
        )
        text = verification_page.locator("body").inner_text(timeout=3000)
        folded = text.casefold()
        if "security verification" in folded or "verify you are not a bot" in folded:
            certificate = _unavailable("PCA", cert_number)
        else:
            certificate = router.parse_official_grade_text(text, cert_number, "PCA")
    except Exception as error:
        hunter.watcher.log(
            f"Mislisted slab: PCA direct cert indisponible ({type(error).__name__}: {_safe_error(error)})"
        )
        certificate = _unavailable("PCA", cert_number)
    finally:
        if verification_context is not None:
            try:
                verification_context.close()
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

    verification_context = None
    try:
        verification_context, verification_page = _new_verification_page(
            page,
            CCC_VERIFY_URL,
        )
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
        certificate = parse_ccc_verified_text(text, cert_number)
    except Exception as error:
        hunter.watcher.log(
            f"Mislisted slab: CCC browser cert indisponible ({type(error).__name__}: {_safe_error(error)})"
        )
        certificate = _unavailable("CCC", cert_number)
    finally:
        if verification_context is not None:
            try:
                verification_context.close()
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
