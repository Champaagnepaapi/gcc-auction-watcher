from __future__ import annotations

import html
import os
import re
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

PSA_CERT_URL = "https://www.psacard.com/cert/{cert_number}"
MAX_CERT_LOOKUPS_PER_RUN = max(
    0, int(os.getenv("V4_MISLISTED_CERT_MAX_PER_RUN", "5"))
)
PSA_CERT_TIMEOUT_SECONDS = max(
    2.0, float(os.getenv("V4_MISLISTED_CERT_TIMEOUT_SECONDS", "6"))
)

_ORIGINAL_AUCTION_API_LOT = auction_discovery._auction_api_lot
_ORIGINAL_EVALUATE = watcher.evaluate_gcc_candidate_for_arbitration
_CERT_LOOKUPS = 0
_CERT_CACHE: dict[str, "PsaCertificate"] = {}
_INSTALLED = False


@dataclass(frozen=True)
class PsaCertificate:
    cert_number: str
    grade: Optional[float]
    card_number: str = ""
    subject: str = ""
    year: str = ""
    status: str = "OK"


@dataclass(frozen=True)
class GradeMismatch:
    status: str
    metadata_grade: float
    resolved_grade: Optional[float]
    image_grade: Optional[float] = None
    certificate_grade: Optional[float] = None
    manual_verification_required: bool = True



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
    """Resolve only the direction of a mismatch; never authorise a purchase.

    Official certificate grade is the strongest machine-readable signal. Image
    grade is retained as corroboration, but image-only conflicts remain manual.
    """
    metadata = _numeric_grade(metadata_grade)
    cert = _numeric_grade(certificate_grade)
    image = _numeric_grade(image_grade)
    if metadata is None:
        return None
    resolved = cert if cert is not None else image
    if resolved is None:
        return GradeMismatch(CERT_UNAVAILABLE, metadata, None, image, cert, True)
    if resolved > metadata:
        status = POSITIVE_GRADE_MISMATCH
    elif resolved < metadata:
        status = NEGATIVE_GRADE_MISMATCH
    else:
        status = GRADE_MATCH
    return GradeMismatch(status, metadata, resolved, image, cert, True)



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



def parse_psa_certificate_html(raw_html: str, expected_cert: str = "") -> PsaCertificate:
    lines = _html_to_lines(raw_html)
    cert = _field_after(lines, "Certification Number")
    if not cert:
        match = re.search(r"PSA Certification\s*#?\s*(\d{5,12})", "\n".join(lines), re.I)
        cert = match.group(1) if match else ""
    cert = re.sub(r"\D", "", cert)
    expected = re.sub(r"\D", "", expected_cert or "")
    if expected and cert and cert != expected:
        return PsaCertificate(expected, None, status=CERT_UNAVAILABLE)
    if expected and not cert:
        cert = expected

    raw_grade = _field_after(lines, "Grade")
    grade_match = re.search(r"(10(?:\.0)?|[1-9](?:\.5|\.0)?)\s*$", raw_grade)
    grade = _numeric_grade(grade_match.group(1)) if grade_match else None
    status = "OK" if grade is not None else CERT_GRADE_UNREADABLE
    subject = (
        _field_after(lines, "Player")
        or _field_after(lines, "Subject")
        or _field_after(lines, "Card Name")
    )
    return PsaCertificate(
        cert_number=cert or expected,
        grade=grade,
        card_number=_field_after(lines, "Card Number"),
        subject=subject,
        year=_field_after(lines, "Year"),
        status=status,
    )



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



def resolve_psa_certificate(cert_number: str, *, http_get=None) -> PsaCertificate:
    global _CERT_LOOKUPS
    cert_number = re.sub(r"\D", "", cert_number or "")
    if not cert_number:
        return PsaCertificate("", None, status=CERT_UNAVAILABLE)
    cached = _CERT_CACHE.get(cert_number)
    if cached is not None:
        return cached
    if _CERT_LOOKUPS >= MAX_CERT_LOOKUPS_PER_RUN:
        return PsaCertificate(cert_number, None, status=CERT_UNAVAILABLE)

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
        certificate = PsaCertificate(cert_number, None, status=CERT_UNAVAILABLE)
    _CERT_CACHE[cert_number] = certificate
    return certificate



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
    certificate: PsaCertificate,
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

    warning = (
        "Potential hidden upgrade; verify slab image and certificate identity before bidding."
        if mismatch.status == POSITIVE_GRADE_MISMATCH
        else "DO NOT VALUE AS THE HIGHER LISTING GRADE. Manual slab/certificate verification required."
    )
    message = (
        f"🚨 {title}\n\n"
        f"{name}\n"
        f"GCC metadata : PSA {mismatch.metadata_grade:g}\n"
        f"PSA certificate #{certificate.cert_number} : PSA {mismatch.resolved_grade:g}\n"
        f"Prix actuel : {_money(current)}\n"
        f"FV metadata : {_money(metadata_fv)}\n"
        f"FV cert scenario : {_money(resolved_fv)}\n"
        + (
            f"Potential hidden discount vs cert grade : {hidden_discount:.1f}%\n"
            if hidden_discount is not None else ""
        )
        + f"{warning}\n"
        "MANUAL REVIEW ONLY — aucun achat/enchère automatique.\n"
        f"{lot.url}"
    )
    watcher.log(f"Mislisted slab détecté: {mismatch.status} | {lot.url}")
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
    """PSA-only manual-review preflight; negative mismatch fails closed.

    Positive mismatches remain visible as manual-review leads while normal V4
    valuation continues using marketplace metadata. Negative mismatches are
    blocked before economic notification so a PSA 9 cert cannot be priced as a
    marketplace PSA 10. No automatic transaction is ever performed.
    """
    if lot.source_type != "auction" or (lot.grader or "").upper() != "PSA":
        return _ORIGINAL_EVALUATE(
            page, lot, position, state, seen_at, run_now, run_diagnostics
        )

    inspected = lot if lot.body else watcher.inspect_item(page, lot)
    if inspected.inspection_error:
        return _ORIGINAL_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )
    serial = _serial_from_lot(inspected)
    metadata_grade = _numeric_grade(inspected.grade)
    if not serial or metadata_grade is None:
        return _ORIGINAL_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    certificate = resolve_psa_certificate(serial)
    mismatch = classify_grade_mismatch(
        metadata_grade, certificate_grade=certificate.grade
    )
    if (
        mismatch is None
        or certificate.status != "OK"
        or mismatch.status in {GRADE_MATCH, CERT_UNAVAILABLE}
    ):
        return _ORIGINAL_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    review_key = f"{serial}:{metadata_grade:g}:{mismatch.resolved_grade:g}"
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

    return _ORIGINAL_EVALUATE(
        page, inspected, position, state, seen_at, run_now, run_diagnostics
    )



def install_v4_mislisted_slab_hunter() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    auction_discovery._auction_api_lot = _auction_api_lot_with_serial
    watcher.evaluate_gcc_candidate_for_arbitration = evaluate_with_mislisted_slab_guard
    _INSTALLED = True
