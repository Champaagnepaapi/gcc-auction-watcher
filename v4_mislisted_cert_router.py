from __future__ import annotations

import re
from typing import Optional

import v4_mislisted_slab_hunter as hunter


CCC_VERIFY_URL = "https://cccgrading.com/fr/verification-carte-ccc"
PCA_VERIFY_URL = "https://pcagrade.com/fr/"
CGC_VERIFY_URL = "https://www.cgccards.com/certlookup/"
SGC_VERIFY_URL = "https://www.gosgc.com/cert-code-lookup"
COLLECTAURA_VERIFY_URL = "https://www.collectaura.com/pages/check-the-authenticity-of-a-card"
AP_VERIFY_URL = "https://check.apgrading.de/"
GEM_VERIFY_URL = "https://www.gem-cards.com/verify/"
BECKETT_VERIFY_URL = "https://www.beckett.com/grading/card-lookup?item_id={cert_number}&item_type={item_type}"
SGS_VERIFY_URL = "https://sgscards.com/cardpage/{cert_number}"
ACE_VERIFY_URL = "https://acegrading.com/cert/{cert_number}"
GRAAD_VERIFY_URL = "https://www.graad.eu/en/verify-cert/{cert_number}"

_GRADER_ALIASES = {
    "BECKETT": "BGS",
    "BECKETT BGS": "BGS",
    "COLLECTAURA": "CA",
    "COLLECT AURA": "CA",
    "ACE GRADING": "ACE",
    "AP GRADING": "AP",
    "GRAAD GRADING": "GRAAD",
}

_NOT_FOUND_MARKERS = (
    "this item cannot be found",
    "cannot be found",
    "certification number was entered correctly",
    "numéro d'authenticité non trouvé",
    "numero d'authenticite non trouve",
    "certificat introuvable",
    "certification introuvable",
    "no certificate found",
    "no cert found",
    "invalid certificate",
    "invalid cert",
)


def _normalize_grader(grader: str) -> str:
    normalized = re.sub(r"\s+", " ", (grader or "").strip().upper())
    return _GRADER_ALIASES.get(normalized, normalized)


def _cert_digits(cert_number: str) -> str:
    return re.sub(r"\D", "", cert_number or "")


def _provider_cert(grader: str, cert_number: str) -> str:
    digits = _cert_digits(cert_number)
    if grader == "SGC" and len(digits) == 10:
        return f"{digits[:7]}-{digits[7:]}"
    return digits


def _cache_or_budget(grader: str, cert_number: str) -> tuple[Optional[hunter.GraderCertificate], bool]:
    cache_key = (grader, cert_number)
    cached = hunter._CERT_CACHE.get(cache_key)
    if cached is not None:
        return cached, False
    if hunter._CERT_LOOKUPS >= hunter.MAX_CERT_LOOKUPS_PER_RUN:
        return hunter.GraderCertificate(
            cert_number,
            None,
            status=hunter.CERT_UNAVAILABLE,
            grader=grader,
        ), False
    hunter._CERT_LOOKUPS += 1
    return None, True


def _cache_certificate(certificate: hunter.GraderCertificate) -> hunter.GraderCertificate:
    hunter._CERT_CACHE[(certificate.grader, certificate.cert_number)] = certificate
    return certificate


def _grade_token(text: str) -> Optional[float]:
    match = re.search(
        r"(?<!\d)(10|9[.,]5|9|8[.,]5|8|7[.,]5|7|6[.,]5|6|5[.,]5|5|4[.,]5|4|3[.,]5|3|2[.,]5|2|1[.,]5|1)(?!\d)",
        text,
    )
    return hunter._numeric_grade(match.group(1)) if match else None


def parse_official_grade_text(
    raw_text: str,
    expected_cert: str = "",
    grader: str = "",
) -> hunter.GraderCertificate:
    """Parse only an explicit overall grade, never a random subgrade/population number."""
    grader = _normalize_grader(grader)
    expected = _cert_digits(expected_cert)
    lines = [re.sub(r"\s+", " ", line).strip() for line in (raw_text or "").splitlines() if line.strip()]
    folded = "\n".join(lines).casefold()

    if any(marker in folded for marker in _NOT_FOUND_MARKERS):
        return hunter.GraderCertificate(expected, None, status=hunter.CERT_UNAVAILABLE, grader=grader)

    label_pattern = re.compile(
        r"^(?:overall\s+grade|final\s+grade|grade|note|notation|rating|note\s+finale)\s*[:\-]?\s*(.*)$",
        re.I,
    )
    for index, line in enumerate(lines):
        match = label_pattern.match(line)
        if not match:
            continue
        tail = match.group(1).strip()
        grade = _grade_token(tail) if tail else None
        if grade is None:
            for next_line in lines[index + 1 : index + 4]:
                grade = _grade_token(next_line)
                if grade is not None:
                    break
        if grade is not None:
            return hunter.GraderCertificate(expected, grade, status="OK", grader=grader)

    if grader:
        prefix = re.compile(
            rf"^{re.escape(grader)}(?:\s+(?:GRADING|GRADE))?\s+"
            r"(10|9[.,]5|9|8[.,]5|8|7[.,]5|7|6[.,]5|6|5[.,]5|5|4[.,]5|4|3[.,]5|3|2[.,]5|2|1[.,]5|1)\b",
            re.I,
        )
        for line in lines:
            match = prefix.search(line)
            if match:
                grade = hunter._numeric_grade(match.group(1))
                if grade is not None:
                    return hunter.GraderCertificate(expected, grade, status="OK", grader=grader)

    if expected:
        for index, line in enumerate(lines[:40]):
            if expected not in _cert_digits(line):
                continue
            for next_line in lines[index + 1 : index + 5]:
                if re.fullmatch(
                    r"(?:10|9[.,]5|9|8[.,]5|8|7[.,]5|7|6[.,]5|6|5[.,]5|5|4[.,]5|4|3[.,]5|3|2[.,]5|2|1[.,]5|1)",
                    next_line,
                    re.I,
                ):
                    grade = hunter._numeric_grade(next_line)
                    if grade is not None:
                        return hunter.GraderCertificate(expected, grade, status="OK", grader=grader)

    return hunter.GraderCertificate(expected, None, status=hunter.CERT_GRADE_UNREADABLE, grader=grader)


def parse_grade_from_ocr_text(raw_text: str, grader: str) -> tuple[Optional[float], str]:
    """Strict OCR parser: one unique plausible grade or no grade at all."""
    grader = _normalize_grader(grader)
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
        for match in re.finditer(
            r"(?<!\d)(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5|4\.5|4|3\.5|3|2\.5|2|1\.5|1)(?!\d)",
            upper,
        ):
            grade = hunter._numeric_grade(match.group(1))
            if grade is not None:
                candidates.append(grade)
    if not candidates:
        for line in lines[:8]:
            compact = line.strip().replace(",", ".")
            if len(compact) <= 18:
                match = re.fullmatch(
                    r".*?\b(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5|4\.5|4|3\.5|3|2\.5|2|1\.5|1)\b.*",
                    compact,
                )
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


def _visible_input_near_button(verification_page, button):
    try:
        form = button.locator("xpath=ancestor::form[1]")
        if form.count():
            inputs = form.locator("input")
            for index in range(inputs.count()):
                candidate = inputs.nth(index)
                try:
                    input_type = (candidate.get_attribute("type") or "text").lower()
                    if candidate.is_visible() and input_type not in {"hidden", "submit", "button", "checkbox", "radio"}:
                        return candidate
                except Exception:
                    continue
    except Exception:
        pass

    best = None
    best_score = -1
    inputs = verification_page.locator("input")
    for index in range(inputs.count()):
        candidate = inputs.nth(index)
        try:
            input_type = (candidate.get_attribute("type") or "text").lower()
            if not candidate.is_visible() or input_type in {"hidden", "submit", "button", "checkbox", "radio", "email", "password"}:
                continue
            descriptor = " ".join(
                candidate.get_attribute(attr) or ""
                for attr in ("placeholder", "name", "id", "aria-label")
            ).casefold()
            score = 0
            if any(token in descriptor for token in ("cert", "serial", "authentic", "numéro", "numero", "code")):
                score += 10
            if re.search(r"\d{5,}", descriptor):
                score += 4
            if input_type in {"text", "number", "search"}:
                score += 1
            if score > best_score:
                best = candidate
                best_score = score
        except Exception:
            continue
    return best


def _resolve_browser_form(
    page,
    grader: str,
    cert_number: str,
    *,
    url: str,
    button_pattern: str,
) -> hunter.GraderCertificate:
    grader = _normalize_grader(grader)
    cert_digits = _cert_digits(cert_number)
    provider_cert = _provider_cert(grader, cert_digits)
    if not cert_digits or page is None:
        return hunter.GraderCertificate(cert_digits, None, status=hunter.CERT_UNAVAILABLE, grader=grader)

    cached, allowed = _cache_or_budget(grader, cert_digits)
    if not allowed:
        return cached

    verification_page = None
    try:
        verification_page = page.context.new_page()
        verification_page.goto(url, wait_until="domcontentloaded", timeout=8000)
        button = verification_page.get_by_role("button", name=re.compile(button_pattern, re.I))
        if button.count() == 0:
            button = verification_page.locator("button").filter(has_text=re.compile(button_pattern, re.I))
        if button.count() == 0:
            raise RuntimeError(f"{grader} verify button unavailable")

        input_locator = _visible_input_near_button(verification_page, button.first)
        if input_locator is None:
            raise RuntimeError(f"{grader} cert input unavailable")
        input_locator.fill(provider_cert)
        button.first.click(timeout=3000)
        try:
            verification_page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            verification_page.wait_for_timeout(1200)

        text = verification_page.locator("body").inner_text(timeout=3000)
        certificate = parse_official_grade_text(text, cert_digits, grader)
    except Exception as error:
        hunter.watcher.log(f"Mislisted slab: {grader} cert indisponible ({type(error).__name__})")
        certificate = hunter.GraderCertificate(cert_digits, None, status=hunter.CERT_UNAVAILABLE, grader=grader)
    finally:
        if verification_page is not None:
            try:
                verification_page.close()
            except Exception:
                pass

    return _cache_certificate(certificate)


def _resolve_direct_http(
    grader: str,
    cert_number: str,
    *,
    url: str,
    http_get=None,
) -> hunter.GraderCertificate:
    grader = _normalize_grader(grader)
    cert_digits = _cert_digits(cert_number)
    if not cert_digits:
        return hunter.GraderCertificate("", None, status=hunter.CERT_UNAVAILABLE, grader=grader)

    cached, allowed = _cache_or_budget(grader, cert_digits)
    if not allowed:
        return cached

    getter = http_get or hunter.watcher.requests.get
    try:
        response = getter(
            url.format(cert_number=cert_digits),
            headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"},
            timeout=hunter.PSA_CERT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        text = "\n".join(hunter._html_to_lines(response.text))
        certificate = parse_official_grade_text(text, cert_digits, grader)
    except Exception as error:
        hunter.watcher.log(f"Mislisted slab: {grader} cert indisponible ({type(error).__name__})")
        certificate = hunter.GraderCertificate(cert_digits, None, status=hunter.CERT_UNAVAILABLE, grader=grader)
    return _cache_certificate(certificate)


def resolve_ccc_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    cert_number = _cert_digits(cert_number)
    if not cert_number or page is None:
        return hunter.GraderCertificate(cert_number, None, status=hunter.CERT_UNAVAILABLE, grader="CCC")

    cached, allowed = _cache_or_budget("CCC", cert_number)
    if not allowed:
        return cached

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

    return _cache_certificate(certificate)


def resolve_pca_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    return _resolve_browser_form(page, "PCA", cert_number, url=PCA_VERIFY_URL, button_pattern=r"Rechercher|Search")


def resolve_cgc_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    return _resolve_browser_form(page, "CGC", cert_number, url=CGC_VERIFY_URL, button_pattern=r"^Go$|Verify|Search")


def resolve_sgc_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    return _resolve_browser_form(page, "SGC", cert_number, url=SGC_VERIFY_URL, button_pattern=r"Check Cert Code|Check|Verify")


def resolve_collectaura_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    return _resolve_browser_form(page, "CA", cert_number, url=COLLECTAURA_VERIFY_URL, button_pattern=r"V[ée]rifier|Verify")


def resolve_ap_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    return _resolve_browser_form(page, "AP", cert_number, url=AP_VERIFY_URL, button_pattern=r"Check|Verify")


def resolve_gem_certificate(page, cert_number: str) -> hunter.GraderCertificate:
    return _resolve_browser_form(page, "GEM", cert_number, url=GEM_VERIFY_URL, button_pattern=r"Verify|Verification")


def resolve_beckett_certificate(grader: str, cert_number: str) -> hunter.GraderCertificate:
    grader = _normalize_grader(grader)
    cert_digits = _cert_digits(cert_number)
    item_type = grader if grader in {"BGS", "BVG", "BCCG"} else "BGS"
    url = BECKETT_VERIFY_URL.format(cert_number=cert_digits, item_type=item_type)
    return _resolve_direct_http(grader, cert_digits, url=url)


def resolve_sgs_certificate(cert_number: str) -> hunter.GraderCertificate:
    return _resolve_direct_http("SGS", cert_number, url=SGS_VERIFY_URL)


def resolve_ace_certificate(cert_number: str) -> hunter.GraderCertificate:
    return _resolve_direct_http("ACE", cert_number, url=ACE_VERIFY_URL)


def resolve_graad_certificate(cert_number: str) -> hunter.GraderCertificate:
    return _resolve_direct_http("GRAAD", cert_number, url=GRAAD_VERIFY_URL)


def resolve_grader_certificate(page, grader: str, cert_number: str) -> hunter.GraderCertificate:
    grader = _normalize_grader(grader)
    if grader == "PSA":
        return hunter.resolve_psa_certificate(cert_number)
    if grader == "CCC":
        return resolve_ccc_certificate(page, cert_number)
    if grader == "PCA":
        return resolve_pca_certificate(page, cert_number)
    if grader == "CGC":
        return resolve_cgc_certificate(page, cert_number)
    if grader in {"BGS", "BVG", "BCCG"}:
        return resolve_beckett_certificate(grader, cert_number)
    if grader == "SGC":
        return resolve_sgc_certificate(page, cert_number)
    if grader == "SGS":
        return resolve_sgs_certificate(cert_number)
    if grader == "CA":
        return resolve_collectaura_certificate(page, cert_number)
    if grader == "ACE":
        return resolve_ace_certificate(cert_number)
    if grader == "GRAAD":
        return resolve_graad_certificate(cert_number)
    if grader == "AP":
        return resolve_ap_certificate(page, cert_number)
    if grader == "GEM":
        return resolve_gem_certificate(page, cert_number)
    # Unsupported official verifier: OCR fallback remains available downstream.
    return hunter.GraderCertificate(_cert_digits(cert_number), None, status=hunter.CERT_UNAVAILABLE, grader=grader)


def install_v4_mislisted_cert_router() -> None:
    hunter.resolve_grader_certificate = resolve_grader_certificate
    hunter.parse_grade_from_ocr_text = parse_grade_from_ocr_text
