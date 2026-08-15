from __future__ import annotations

import re
from dataclasses import replace
from email.header import Header
from typing import Callable, Optional

import watcher
import v4_mislisted_ocr_hardening as ocr
import v4_mislisted_slab_hunter as hunter


FOCUS_GRADERS = ocr.OCR_FOCUS_GRADERS
CERT_PROBLEM_STATE_KEY = "cert_problem_alerts"
CERT_NUMBER_MISSING = "CERT_NUMBER_MISSING"
CERT_LOOKUP_FAILED = "CERT_LOOKUP_FAILED"
CERT_GRADE_UNREADABLE = "CERT_GRADE_UNREADABLE"

_DELEGATE_EVALUATE: Optional[Callable] = None
_ORIGINAL_FIXED_API_LOT = watcher._gcc_fixed_result_to_lot
_INSTALLED = False


def _digits(value: object) -> str:
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits if 5 <= len(digits) <= 14 else ""


def _serial_from_api_result(result: dict) -> str:
    item = result.get("item") if isinstance(result.get("item"), dict) else {}
    for value in (
        item.get("serialNumber"),
        item.get("certificationNumber"),
        item.get("certificateNumber"),
        item.get("certNumber"),
        result.get("serialNumber"),
        result.get("certificationNumber"),
        result.get("certificateNumber"),
        result.get("certNumber"),
    ):
        serial = _digits(value)
        if serial:
            return serial
    return ""


def _lot_with_serial(lot: watcher.Lot, serial: str) -> watcher.Lot:
    serial = _digits(serial)
    if not serial:
        return lot
    dimensions = dict(lot.commercial_dimensions)
    dimensions["cert_number"] = serial
    return replace(lot, commercial_dimensions=dimensions)


def _fixed_api_lot_with_serial(result, item_url, coverage, *args, **kwargs):
    lot = _ORIGINAL_FIXED_API_LOT(result, item_url, coverage, *args, **kwargs)
    if lot is None:
        return None
    return _lot_with_serial(lot, _serial_from_api_result(result))


def _preserve_serial_after_inspection(
    inspected: watcher.Lot,
    serial_before_inspection: str,
) -> watcher.Lot:
    """Restore the snapshotted API cert if in-place inspection erased it."""
    serial = _digits(serial_before_inspection)
    if not serial or hunter._serial_from_lot(inspected):
        return inspected
    return _lot_with_serial(inspected, serial)


def _serial_from_text(text: str) -> str:
    patterns = (
        r"(?:Num[ée]ro de s[ée]rie|Serial Number|Certification Number|"
        r"Num[ée]ro de certification|Cert(?:ification)?(?: Number)?)"
        r"\s*:?\s*\n?\s*([0-9][0-9 ]{4,14})",
        r"(?:Certification|Certificat)\s*\n\s*([0-9][0-9 ]{4,14})",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", re.I)
        if match:
            serial = _digits(match.group(1))
            if serial:
                return serial
    return ""


def _click_visible_text(page, pattern: str) -> bool:
    rx = re.compile(pattern, re.I)
    for locator in (
        page.get_by_role("button", name=rx),
        page.get_by_text(rx, exact=True),
    ):
        try:
            count = min(locator.count(), 8)
        except Exception:
            continue
        for index in range(count):
            node = locator.nth(index)
            try:
                if node.is_visible():
                    node.click(timeout=1200)
                    page.wait_for_timeout(150)
                    return True
            except Exception:
                continue
    return False


def _serial_from_gradation_panel(page, lot_url: str) -> str:
    """Last-resort GCC UI proof before declaring a certificate number missing.

    GCC keeps the cert under Description -> Gradation while the collapsed body
    omits it. This helper is read-only and is used only when no structured cert
    survived from the API/detail data.
    """
    if page is None or not lot_url:
        return ""
    try:
        current_url = str(getattr(page, "url", "") or "").split("?", 1)[0]
        target_url = str(lot_url).split("?", 1)[0]
        if current_url != target_url:
            page.goto(target_url, wait_until="domcontentloaded", timeout=watcher.NAV_TIMEOUT)
            page.wait_for_timeout(250)
        _click_visible_text(page, r"^(Description|Détails?|Details?)$")
        _click_visible_text(page, r"^(Gradation|Grading)$")
        text = page.locator("body").inner_text(timeout=2500)
        return _serial_from_text(text)
    except Exception as error:
        watcher.log(
            f"Cert problem: lecture Description/Gradation impossible "
            f"({type(error).__name__}) | {lot_url}"
        )
        return ""


def _normalized_grader(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def _issue_title(issue: str) -> str:
    if issue == CERT_NUMBER_MISSING:
        return "CERT NUMBER MISSING — MANUAL REVIEW"
    if issue == CERT_GRADE_UNREADABLE:
        return "CERT GRADE UNREADABLE — MANUAL REVIEW"
    return "CERT LOOKUP FAILED — MANUAL REVIEW"


def _money(value: Optional[float]) -> str:
    return "indisponible" if value is None else f"{value:.2f} €"


def _send_cert_problem_review(
    lot: watcher.Lot,
    state: dict,
    *,
    grader: str,
    cert_number: str,
    issue: str,
    cert_status: str,
) -> bool:
    """Send one immediate manual-review alert per listing + cert problem state."""
    key = f"{grader}:{cert_number or 'MISSING'}:{issue}:{cert_status}"
    reviewed = state.setdefault(CERT_PROBLEM_STATE_KEY, {})
    if reviewed.get(lot.url) == key:
        return False

    identity = watcher.extract_card_identity(lot)
    card_name = identity.get("core") or lot.title or "Carte GCC"
    reference = identity.get("ref") or lot.card_number
    if reference and str(reference).lstrip("#") not in card_name:
        card_name = f"{card_name} #{str(reference).lstrip('#')}"

    grade = watcher.format_grade_label(lot.grader, lot.grade) or "Grade metadata inconnu"
    title = _issue_title(issue)
    cert_label = f"#{cert_number}" if cert_number else "ABSENT"
    message = (
        f"{title}\n\n"
        f"{card_name}\n"
        f"Metadata GCC : {grade}\n"
        f"Certificat : {cert_label}\n"
        f"Problème : {issue}\n"
        f"Statut vérificateur officiel : {cert_status or 'N/A'}\n"
        f"Prix GCC : {_money(lot.current_price)}\n\n"
        "Vérifier manuellement le numéro, le certificat officiel et la photo du slab.\n"
        "Un échec de lookup peut être technique et ne prouve pas un mislisting.\n"
        "MANUAL REVIEW ONLY — aucun achat/enchère automatique.\n\n"
        f"{lot.url}"
    )

    watcher.log(f"Cert problem: {issue} / {cert_status or 'N/A'} | {lot.url}")
    print(message, flush=True)
    sent = False
    if watcher.NTFY_TOPIC:
        try:
            watcher.requests.post(
                f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers={
                    "Title": Header(title, "utf-8").encode(),
                    "Priority": "4",
                    "Tags": "warning,card_index",
                },
                timeout=10,
            ).raise_for_status()
            sent = True
            watcher.log(f"Notification ntfy {title} envoyée")
        except Exception as error:
            watcher.log(f"Notification ntfy cert problem échouée: {type(error).__name__}")
    if sent or not watcher.NTFY_TOPIC:
        reviewed[lot.url] = key
    return sent


def _resolve_cert_with_attempt_marker(page, grader: str, serial: str):
    """Differentiate a real lookup failure from the per-run lookup budget being exhausted."""
    cache_key = (grader, serial)
    had_cache = cache_key in hunter._CERT_CACHE
    before = hunter._CERT_LOOKUPS
    certificate = hunter.resolve_grader_certificate(page, grader, serial)
    after = hunter._CERT_LOOKUPS
    attempted_or_cached = had_cache or after > before
    return certificate, attempted_or_cached


def evaluate_with_cert_problem_notifications(
    page,
    lot: watcher.Lot,
    position: int,
    state: dict,
    seen_at: str,
    run_now,
    run_diagnostics: watcher.RunDiagnostics,
):
    """Alert immediately on every actual PSA/PCA/CCC certificate problem.

    A structured GCC API certificate survives inspection. Only when no cert is
    available do we explicitly open Description -> Gradation before declaring
    CERT_NUMBER_MISSING. Present certs alert when an official lookup was actually
    attempted (or reused from cache) and did not return a readable grade. Per-run
    budget exhaustion alone is not labelled as a certificate problem. The normal
    cert-first -> OCR -> V4 path then continues unchanged.
    """
    if _DELEGATE_EVALUATE is None:
        raise RuntimeError("cert problem notification hook not installed")

    grader = _normalized_grader(lot.grader)
    if grader not in FOCUS_GRADERS:
        return _DELEGATE_EVALUATE(
            page, lot, position, state, seen_at, run_now, run_diagnostics
        )

    # inspect_item mutates Lot in place. Snapshot the structured cert *before*
    # inspection so a collapsed GCC body cannot erase the only cert evidence.
    serial_before_inspection = hunter._serial_from_lot(lot)
    inspected = lot if lot.body else watcher.inspect_item(page, lot)
    inspected = _preserve_serial_after_inspection(
        inspected, serial_before_inspection
    )
    if inspected.inspection_error:
        return _DELEGATE_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    serial = hunter._serial_from_lot(inspected)
    if not serial:
        serial = _serial_from_gradation_panel(page, inspected.url)
        if serial:
            inspected = _lot_with_serial(inspected, serial)

    if not serial:
        _send_cert_problem_review(
            inspected,
            state,
            grader=grader,
            cert_number="",
            issue=CERT_NUMBER_MISSING,
            cert_status=CERT_NUMBER_MISSING,
        )
        return _DELEGATE_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    certificate, lookup_was_attempted = _resolve_cert_with_attempt_marker(
        page, grader, serial
    )
    if (
        lookup_was_attempted
        and not (certificate.status == "OK" and certificate.grade is not None)
    ):
        issue = (
            CERT_GRADE_UNREADABLE
            if certificate.status == hunter.CERT_GRADE_UNREADABLE
            else CERT_LOOKUP_FAILED
        )
        _send_cert_problem_review(
            inspected,
            state,
            grader=grader,
            cert_number=serial,
            issue=issue,
            cert_status=certificate.status or hunter.CERT_UNAVAILABLE,
        )

    return _DELEGATE_EVALUATE(
        page, inspected, position, state, seen_at, run_now, run_diagnostics
    )


def install_v4_cert_problem_notifications() -> None:
    """Install after the slab hunter so this wrapper observes the final cert router."""
    global _DELEGATE_EVALUATE
    global _INSTALLED
    if _INSTALLED:
        return
    watcher._gcc_fixed_result_to_lot = _fixed_api_lot_with_serial
    _DELEGATE_EVALUATE = watcher.evaluate_gcc_candidate_for_arbitration
    watcher.evaluate_gcc_candidate_for_arbitration = evaluate_with_cert_problem_notifications
    _INSTALLED = True
