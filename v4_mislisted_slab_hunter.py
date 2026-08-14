from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from email.header import Header
from typing import Optional

import watcher
import v4_auction_item_discovery as auction_discovery


POSITIVE_GRADE_MISMATCH = "POSITIVE_GRADE_MISMATCH"
NEGATIVE_GRADE_MISMATCH = "NEGATIVE_GRADE_MISMATCH"
GRADE_MATCH = "GRADE_MATCH"
CERT_UNAVAILABLE = "CERT_UNAVAILABLE"
CERT_GRADE_UNREADABLE = "CERT_GRADE_UNREADABLE"
IMAGE_GRADE_UNAVAILABLE = "IMAGE_GRADE_UNAVAILABLE"
IMAGE_GRADE_AMBIGUOUS = "IMAGE_GRADE_AMBIGUOUS"

PSA_CERT_URL = "https://www.psacard.com/cert/{cert_number}"
CCC_VERIFY_URL = "https://cccgrading.com/fr/verification-carte-ccc"
MAX_CERT_LOOKUPS_PER_RUN = max(0, int(os.getenv("V4_MISLISTED_CERT_MAX_PER_RUN", "5")))
PSA_CERT_TIMEOUT_SECONDS = max(2.0, float(os.getenv("V4_MISLISTED_CERT_TIMEOUT_SECONDS", "6")))
OCR_TIMEOUT_SECONDS = max(2.0, float(os.getenv("V4_MISLISTED_OCR_TIMEOUT_SECONDS", "8")))

_ORIGINAL_AUCTION_API_LOT = auction_discovery._auction_api_lot
_ORIGINAL_EVALUATE = watcher.evaluate_gcc_candidate_for_arbitration
_CERT_LOOKUPS = 0
_CERT_CACHE: dict[tuple[str, str], "GraderCertificate"] = {}
_INSTALLED = False


@dataclass(frozen=True)
class GraderCertificate:
    cert_number: str
    grade: Optional[float]
    card_number: str = ""
    subject: str = ""
    year: str = ""
    status: str = "OK"
    grader: str = ""
    source: str = "OFFICIAL_CERT"


# Backwards-compatible alias retained for existing tests/imports.
PsaCertificate = GraderCertificate


@dataclass(frozen=True)
class GradeMismatch:
    status: str
    metadata_grade: float
    resolved_grade: Optional[float]
    image_grade: Optional[float] = None
    certificate_grade: Optional[float] = None
    manual_verification_required: bool = True
    evidence_source: str = ""


def _numeric_grade(value: object) -> Optional[float]:
    try:
        grade = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return grade if 0 < grade <= 10 else None


def classify_grade_mismatch(
    metadata_grade: object,
    *,
    certificate_grade: object = None,
    image_grade: object = None,
) -> Optional[GradeMismatch]:
    """Resolve mismatch direction without authorising a transaction.

    Official certificate data outranks image OCR. Image-only conflicts remain
    explicitly unverified and always require manual review.
    """
    metadata = _numeric_grade(metadata_grade)
    cert = _numeric_grade(certificate_grade)
    image = _numeric_grade(image_grade)
    if metadata is None:
        return None
    resolved = cert if cert is not None else image
    evidence_source = "OFFICIAL_CERT" if cert is not None else ("IMAGE_OCR" if image is not None else "")
    if resolved is None:
        return GradeMismatch(CERT_UNAVAILABLE, metadata, None, image, cert, True, evidence_source)
    if resolved > metadata:
        status = POSITIVE_GRADE_MISMATCH
    elif resolved < metadata:
        status = NEGATIVE_GRADE_MISMATCH
    else:
        status = GRADE_MATCH
    return GradeMismatch(status, metadata, resolved, image, cert, True, evidence_source)


def _html_to_lines(raw_html: str) -> list[str]:
    text = re.sub(r"(?is)<(?:script|style)[^>]*>.*?</(?:script|style)>", " ", raw_html or "")
    text = re.sub(r"(?i)<(?:br|/p|/div|/td|/th|/tr|/li|/h\d)>\s*", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _field_after(lines: list[str], label: str) -> str:
    target = label.casefold()
    for index, line in enumerate(lines):
        if line.casefold() == target and index + 1 < len(lines):
            return lines[index + 1]
        if line.casefold().startswith(target + " |"):
            return line.split("|", 1)[1].strip()
        if line.casefold().startswith(target + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def parse_psa_certificate_html(raw_html: str, expected_cert: str = "") -> GraderCertificate:
    lines = _html_to_lines(raw_html)
    cert = _field_after(lines, "Certification Number")
    if not cert:
        match = re.search(r"PSA Certification\s*#?\s*(\d{5,12})", "\n".join(lines), re.I)
        cert = match.group(1) if match else ""
    cert = re.sub(r"\D", "", cert)
    expected = re.sub(r"\D", "", expected_cert or "")
    if expected and cert and cert != expected:
        return GraderCertificate(expected, None, status=CERT_UNAVAILABLE, grader="PSA")
    if expected and not cert:
        cert = expected

    raw_grade = _field_after(lines, "Grade")
    grade_match = re.search(r"(10(?:\.0)?|[1-9](?:\.5|\.0)?)\s*$", raw_grade)
    grade = _numeric_grade(grade_match.group(1)) if grade_match else None
    status = "OK" if grade is not None else CERT_GRADE_UNREADABLE
    subject = _field_after(lines, "Player") or _field_after(lines, "Subject") or _field_after(lines, "Card Name")
    return GraderCertificate(
        cert_number=cert or expected,
        grade=grade,
        card_number=_field_after(lines, "Card Number"),
        subject=subject,
        year=_field_after(lines, "Year"),
        status=status,
        grader="PSA",
    )


def parse_ccc_verification_text(raw_text: str, expected_cert: str = "") -> GraderCertificate:
    text = re.sub(r"\s+", " ", raw_text or "").strip()
    expected = re.sub(r"\D", "", expected_cert or "")
    patterns = (
        r"(?:Note|Grade|Notation|Note finale)\s*[:\-]?\s*(10|9[\.,]5|9|8[\.,]5|8|7|6|5|4|3|2|1)\b",
        r"\b(10|9[\.,]5|9|8[\.,]5|8|7|6|5|4|3|2|1)\s*(?:/\s*10)?\s*(?:Neuf\+|Neuf|Mint|Gem Mint|Pristine|Excellent|Très Bon|Bon|Correct|Poor)\b",
    )
    grade = None
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            grade = _numeric_grade(match.group(1))
            break
    status = "OK" if grade is not None else CERT_GRADE_UNREADABLE
    return GraderCertificate(expected, grade, status=status, grader="CCC")


def _serial_from_result(result: dict) -> str:
    item = result.get("item") if isinstance(result.get("item"), dict) else {}
    for value in (
        item.get("serialNumber"),
        item.get("certificationNumber"),
        result.get("serialNumber"),
        result.get("certificationNumber"),
    ):
        if value is not None:
            serial = re.sub(r"\D", "", str(value))
            if 5 <= len(serial) <= 12:
                return serial
    return ""


def _auction_api_lot_with_serial(result, item_url, coverage, parsed_end):
    lot = _ORIGINAL_AUCTION_API_LOT(result, item_url, coverage, parsed_end)
    if lot is None:
        return None
    serial = _serial_from_result(result)
    if not serial:
        return lot
    dimensions = dict(lot.commercial_dimensions)
    dimensions["cert_number"] = serial
    return replace(lot, commercial_dimensions=dimensions)


def _serial_from_lot(lot: watcher.Lot) -> str:
    direct = lot.commercial_dimensions.get("cert_number", "")
    serial = re.sub(r"\D", "", str(direct))
    if 5 <= len(serial) <= 12:
        return serial
    body = lot.body or ""
    patterns = (
        r"(?:Num[ée]ro de s[ée]rie|Serial Number|Certification Number|Cert(?:ification)?(?: Number)?)\s*:?\s*\n?\s*([0-9][0-9 ]{4,14})",
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.I)
        if match:
            serial = re.sub(r"\D", "", match.group(1))
            if 5 <= len(serial) <= 12:
                return serial
    return ""


def resolve_psa_certificate(cert_number: str, *, http_get=None) -> GraderCertificate:
    global _CERT_LOOKUPS
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number:
        return GraderCertificate("", None, status=CERT_UNAVAILABLE, grader="PSA")
    cache_key = ("PSA", cert_number)
    cached = _CERT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if _CERT_LOOKUPS >= MAX_CERT_LOOKUPS_PER_RUN:
        return GraderCertificate(cert_number, None, status=CERT_UNAVAILABLE, grader="PSA")

    getter = http_get or watcher.requests.get
    _CERT_LOOKUPS += 1
    try:
        response = getter(
            PSA_CERT_URL.format(cert_number=cert_number),
            headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"},
            timeout=PSA_CERT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        certificate = parse_psa_certificate_html(response.text, cert_number)
    except Exception as error:
        watcher.log(f"Mislisted slab: PSA cert indisponible ({type(error).__name__})")
        certificate = GraderCertificate(cert_number, None, status=CERT_UNAVAILABLE, grader="PSA")
    _CERT_CACHE[cache_key] = certificate
    return certificate


def resolve_ccc_certificate(page, cert_number: str) -> GraderCertificate:
    global _CERT_LOOKUPS
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number:
        return GraderCertificate("", None, status=CERT_UNAVAILABLE, grader="CCC")
    cache_key = ("CCC", cert_number)
    cached = _CERT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if _CERT_LOOKUPS >= MAX_CERT_LOOKUPS_PER_RUN or page is None:
        return GraderCertificate(cert_number, None, status=CERT_UNAVAILABLE, grader="CCC")

    _CERT_LOOKUPS += 1
    verification_page = None
    try:
        verification_page = page.context.new_page()
        verification_page.goto(CCC_VERIFY_URL, wait_until="domcontentloaded", timeout=8000)
        input_locator = verification_page.locator("input").filter(visible=True) if hasattr(verification_page.locator("input"), "filter") else None
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
        certificate = parse_ccc_verification_text(text, cert_number)
    except Exception as error:
        watcher.log(f"Mislisted slab: CCC cert indisponible ({type(error).__name__})")
        certificate = GraderCertificate(cert_number, None, status=CERT_UNAVAILABLE, grader="CCC")
    finally:
        if verification_page is not None:
            try:
                verification_page.close()
            except Exception:
                pass
    _CERT_CACHE[cache_key] = certificate
    return certificate


def resolve_grader_certificate(page, grader: str, cert_number: str) -> GraderCertificate:
    grader = (grader or "").strip().upper()
    if grader == "PSA":
        return resolve_psa_certificate(cert_number)
    if grader == "CCC":
        return resolve_ccc_certificate(page, cert_number)
    return GraderCertificate(cert_number, None, status=CERT_UNAVAILABLE, grader=grader)


def _image_ocr_enabled() -> bool:
    return os.getenv("V4_MISLISTED_IMAGE_OCR_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def parse_grade_from_ocr_text(raw_text: str, grader: str) -> tuple[Optional[float], str]:
    grader = (grader or "").strip().upper()
    lines = [re.sub(r"\s+", " ", line).strip() for line in (raw_text or "").splitlines() if line.strip()]
    candidates: list[float] = []
    strong_tokens = (grader, "GRADE", "NOTE", "MINT", "GEM", "NEUF", "PRISTINE", "EXCELLENT")
    for line in lines[:12]:
        upper = line.upper().replace(",", ".")
        if not any(token and token in upper for token in strong_tokens):
            continue
        for match in re.finditer(r"(?<!\d)(10|9\.5|9|8\.5|8|7|6|5|4|3|2|1)(?!\d)", upper):
            grade = _numeric_grade(match.group(1))
            if grade is not None:
                candidates.append(grade)
    if not candidates:
        for line in lines[:8]:
            compact = line.strip().replace(",", ".")
            if len(compact) <= 18:
                match = re.fullmatch(r".*?\b(10|9\.5|9|8\.5|8|7|6|5|4|3|2|1)\b.*", compact)
                if match:
                    grade = _numeric_grade(match.group(1))
                    if grade is not None:
                        candidates.append(grade)
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0], "OK"
    if len(unique) > 1:
        return None, IMAGE_GRADE_AMBIGUOUS
    return None, IMAGE_GRADE_UNAVAILABLE


def resolve_image_grade_from_page(page, grader: str) -> tuple[Optional[float], str]:
    if not _image_ocr_enabled() or page is None or not shutil.which("tesseract"):
        return None, IMAGE_GRADE_UNAVAILABLE
    try:
        images = page.locator("img")
        best_box = None
        for index in range(images.count()):
            candidate = images.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                box = candidate.bounding_box()
            except Exception:
                continue
            if not box or box["width"] < 120 or box["height"] < 220:
                continue
            area = box["width"] * box["height"]
            if best_box is None or area > best_box[0]:
                best_box = (area, box)
        if best_box is None:
            return None, IMAGE_GRADE_UNAVAILABLE
        box = best_box[1]
        clip = {
            "x": max(0, box["x"]),
            "y": max(0, box["y"]),
            "width": box["width"],
            "height": max(80, box["height"] * 0.34),
        }
        png_bytes = page.screenshot(clip=clip)
        with tempfile.NamedTemporaryFile(suffix=".png") as handle:
            handle.write(png_bytes)
            handle.flush()
            completed = subprocess.run(
                ["tesseract", handle.name, "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=OCR_TIMEOUT_SECONDS,
                check=False,
            )
        if completed.returncode != 0:
            return None, IMAGE_GRADE_UNAVAILABLE
        return parse_grade_from_ocr_text(completed.stdout, grader)
    except Exception as error:
        watcher.log(f"Mislisted slab: image OCR indisponible ({type(error).__name__})")
        return None, IMAGE_GRADE_UNAVAILABLE


def _estimate_for_grade(lot: watcher.Lot, grade: float, now) -> Optional[watcher.MarketEstimate]:
    try:
        sales = watcher.extract_historical_sales(lot)
        scenario = replace(lot, grade=f"{grade:g}")
        return watcher.build_market_estimate(scenario, sales, now)
    except Exception:
        return None


def _money(value: Optional[float]) -> str:
    return "indisponible" if value is None else f"{value:.2f} €"


def _send_mismatch_review(
    lot: watcher.Lot,
    mismatch: GradeMismatch,
    certificate: GraderCertificate,
    metadata_fv: Optional[float],
    resolved_fv: Optional[float],
) -> bool:
    direction = "POSITIVE" if mismatch.status == POSITIVE_GRADE_MISMATCH else "NEGATIVE"
    title = f"POTENTIAL MISLISTED SLAB — {direction}"
    identity = watcher.extract_card_identity(lot)
    name = identity.get("core") or lot.title or "Carte GCC"
    ref = identity.get("ref") or lot.card_number
    if ref:
        name = f"{name} #{str(ref).lstrip('#')}"
    current = lot.current_price
    hidden_discount = None
    if resolved_fv and resolved_fv > 0 and current is not None:
        hidden_discount = max(0.0, (resolved_fv - current) / resolved_fv * 100.0)

    grader = (lot.grader or certificate.grader or "grader").upper()
    if mismatch.evidence_source == "OFFICIAL_CERT":
        evidence_line = f"Cert officiel {grader} #{certificate.cert_number} : {grader} {mismatch.resolved_grade:g}"
        confidence_line = "Preuve : OFFICIAL_CERT"
    else:
        evidence_line = f"Image slab OCR : {grader} {mismatch.resolved_grade:g} (NON CONFIRMÉ)"
        confidence_line = f"Certificat : {certificate.status} | Preuve : IMAGE_ONLY"

    warning = (
        "Potential hidden upgrade; vérifier manuellement avant enchère."
        if mismatch.status == POSITIVE_GRADE_MISMATCH
        else "NE PAS valoriser automatiquement au grade supérieur de l'annonce. Revue manuelle requise."
    )
    message = (
        f"🚨 {title}\n\n"
        f"{name}\n"
        f"GCC metadata : {grader} {mismatch.metadata_grade:g}\n"
        f"{evidence_line}\n"
        f"{confidence_line}\n"
        f"Prix actuel : {_money(current)}\n"
        f"FV metadata : {_money(metadata_fv)}\n"
        f"FV scénario grade résolu : {_money(resolved_fv)}\n"
        + (f"Potential hidden discount : {hidden_discount:.1f}%\n" if hidden_discount is not None else "")
        + f"{warning}\n"
        "MANUAL REVIEW ONLY — aucun achat/enchère automatique.\n"
        f"{lot.url}"
    )
    watcher.log(f"Mislisted slab détecté: {mismatch.status} / {mismatch.evidence_source} | {lot.url}")
    print(message, flush=True)
    if not watcher.NTFY_TOPIC:
        return False
    try:
        watcher.requests.post(
            f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": Header(title, "utf-8").encode(),
                "Priority": "5" if mismatch.status == NEGATIVE_GRADE_MISMATCH else "4",
                "Tags": "warning,mag,card_index",
            },
            timeout=10,
        ).raise_for_status()
        return True
    except Exception as error:
        watcher.log(f"Mislisted slab ntfy échoué ({type(error).__name__})")
        return False


def evaluate_with_mislisted_slab_guard(
    page,
    lot: watcher.Lot,
    position: int,
    state: dict,
    seen_at: str,
    run_now,
    run_diagnostics: watcher.RunDiagnostics,
):
    """Cert-first mismatch hunter, then image OCR only when cert lookup fails.

    Official grader verification is authoritative when available. If the grader
    lookup is unavailable, OCR may still surface an IMAGE_ONLY manual-review
    lead. Positive image-only mismatches never change the normal V4 valuation.
    Negative mismatches are blocked from normal economic notification because
    the listing may be overstating the slab grade.
    """
    grader = (lot.grader or "").strip().upper()
    if not grader:
        return _ORIGINAL_EVALUATE(page, lot, position, state, seen_at, run_now, run_diagnostics)

    inspected = lot if lot.body else watcher.inspect_item(page, lot)
    if inspected.inspection_error:
        return _ORIGINAL_EVALUATE(page, inspected, position, state, seen_at, run_now, run_diagnostics)

    serial = _serial_from_lot(inspected)
    metadata_grade = _numeric_grade(inspected.grade)
    if not serial or metadata_grade is None:
        return _ORIGINAL_EVALUATE(page, inspected, position, state, seen_at, run_now, run_diagnostics)

    certificate = resolve_grader_certificate(page, grader, serial)
    image_grade = None
    image_status = IMAGE_GRADE_UNAVAILABLE
    if certificate.status == "OK" and certificate.grade is not None:
        mismatch = classify_grade_mismatch(metadata_grade, certificate_grade=certificate.grade)
    else:
        image_grade, image_status = resolve_image_grade_from_page(page, grader)
        mismatch = classify_grade_mismatch(metadata_grade, image_grade=image_grade)

    if mismatch is None or mismatch.status in {GRADE_MATCH, CERT_UNAVAILABLE}:
        if certificate.status != "OK" and image_status == IMAGE_GRADE_AMBIGUOUS:
            watcher.log(f"Mislisted slab: OCR ambigu, aucune alerte | {inspected.url}")
        return _ORIGINAL_EVALUATE(page, inspected, position, state, seen_at, run_now, run_diagnostics)

    review_key = f"{grader}:{serial}:{metadata_grade:g}:{mismatch.resolved_grade:g}:{mismatch.evidence_source}"
    reviewed = state.setdefault("mislisted_slab_reviews", {})
    previous_key = reviewed.get(inspected.url)
    if previous_key != review_key:
        metadata_estimate = _estimate_for_grade(inspected, metadata_grade, run_now)
        resolved_estimate = _estimate_for_grade(inspected, mismatch.resolved_grade, run_now)
        sent = _send_mismatch_review(
            inspected,
            mismatch,
            certificate,
            metadata_estimate.central if metadata_estimate else None,
            resolved_estimate.central if resolved_estimate else None,
        )
        if sent or not watcher.NTFY_TOPIC:
            reviewed[inspected.url] = review_key

    if mismatch.status == NEGATIVE_GRADE_MISMATCH:
        watcher.log(
            "Mislisted slab safety gate: negative grade mismatch -> "
            "opportunité économique bloquée, revue manuelle requise"
        )
        run_diagnostics.record_valuation(inspected, watcher.REJECTION_OTHER)
        return None

    return _ORIGINAL_EVALUATE(page, inspected, position, state, seen_at, run_now, run_diagnostics)


def install_v4_mislisted_slab_hunter() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    auction_discovery._auction_api_lot = _auction_api_lot_with_serial
    watcher.evaluate_gcc_candidate_for_arbitration = evaluate_with_mislisted_slab_guard
    _INSTALLED = True
