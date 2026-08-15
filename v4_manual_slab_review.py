from __future__ import annotations

from email.header import Header
from typing import Callable, Optional

import watcher
from v4_mislisted_ocr_hardening import (
    MANUAL_SLAB_CERT_NUMBER,
    MANUAL_SLAB_CERT_STATUS,
    MANUAL_SLAB_OCR_STATUS,
    MANUAL_SLAB_REVIEW_FLAG,
    MANUAL_SLAB_REVIEW_UNRESOLVED,
)


MANUAL_REVIEW_TITLE = "MANUAL SLAB GRADE REVIEW"
MANUAL_REVIEW_REASON = "certificat officiel + OCR non résolus — revue manuelle"
MANUAL_REVIEW_STATE_SENT = "manual_slab_grade_review_sent"

_DELEGATE_NOTIFICATION_DECISION: Optional[Callable] = None
_DELEGATE_UPDATED_NOTIFICATION_STATE: Optional[Callable] = None
_DELEGATE_NOTIFY: Optional[Callable] = None
_INSTALLED = False


def _dimensions(op: watcher.Opportunity) -> dict[str, str]:
    raw = op.lot.commercial_dimensions
    return raw if isinstance(raw, dict) else {}


def _needs_manual_slab_review(op: watcher.Opportunity) -> bool:
    return (
        _dimensions(op).get(MANUAL_SLAB_REVIEW_FLAG)
        == MANUAL_SLAB_REVIEW_UNRESOLVED
    )


def notification_decision_with_manual_slab_review(
    op: watcher.Opportunity,
    previous: Optional[dict],
) -> watcher.NotificationDecision:
    """Force one review alert only after V4 has retained a real opportunity."""
    if _DELEGATE_NOTIFICATION_DECISION is None:
        raise RuntimeError("manual slab review notification hook not installed")

    decision = _DELEGATE_NOTIFICATION_DECISION(op, previous)
    if not _needs_manual_slab_review(op):
        return decision

    already_sent = bool(
        isinstance(previous, dict) and previous.get(MANUAL_REVIEW_STATE_SENT)
    )
    if already_sent:
        return decision

    reasons = list(decision.reasons)
    if MANUAL_REVIEW_REASON not in reasons:
        reasons.append(MANUAL_REVIEW_REASON)
    return watcher.NotificationDecision(
        should_notify=True,
        final_alert=decision.final_alert,
        reasons=tuple(reasons),
    )


def updated_notification_state_with_manual_slab_review(
    op: watcher.Opportunity,
    previous: Optional[dict],
    decision: watcher.NotificationDecision,
    notified_at: str,
) -> dict:
    if _DELEGATE_UPDATED_NOTIFICATION_STATE is None:
        raise RuntimeError("manual slab review state hook not installed")

    state = _DELEGATE_UPDATED_NOTIFICATION_STATE(
        op, previous, decision, notified_at
    )
    if MANUAL_REVIEW_REASON not in decision.reasons:
        return state

    dimensions = _dimensions(op)
    state[MANUAL_REVIEW_STATE_SENT] = True
    state[MANUAL_SLAB_CERT_STATUS] = dimensions.get(MANUAL_SLAB_CERT_STATUS, "")
    state[MANUAL_SLAB_OCR_STATUS] = dimensions.get(MANUAL_SLAB_OCR_STATUS, "")
    return state


def _manual_review_message(op: watcher.Opportunity) -> str:
    dimensions = _dimensions(op)
    identity = watcher.extract_card_identity(op.lot)
    card_name = identity.get("core") or op.lot.title or "Carte GCC"
    reference = identity.get("ref") or op.lot.card_number
    if reference and str(reference).lstrip("#") not in card_name:
        card_name = f"{card_name} #{str(reference).lstrip('#')}"

    grade = watcher.format_grade_label(op.lot.grader, op.lot.grade) or "Grade metadata inconnu"
    cert_status = dimensions.get(MANUAL_SLAB_CERT_STATUS) or "CERT_UNAVAILABLE"
    ocr_status = dimensions.get(MANUAL_SLAB_OCR_STATUS) or "IMAGE_GRADE_UNAVAILABLE"
    cert_number = dimensions.get(MANUAL_SLAB_CERT_NUMBER) or "inconnu"
    timing = ""
    if op.lot.source_type == "auction":
        timing_value = (
            f"{op.lot.minutes_to_end} min"
            if op.lot.minutes_to_end is not None
            else (op.lot.end_text or "inconnue")
        )
        timing = f"Fin enchère : {timing_value}\n"

    return (
        f"{MANUAL_REVIEW_TITLE}\n\n"
        f"{card_name}\n"
        f"Metadata GCC : {grade}\n"
        f"Cert officiel #{cert_number} : {cert_status}\n"
        f"OCR slab ciblé : {ocr_status}\n\n"
        f"Prix actuel : {op.lot.current_price:.2f} €\n"
        f"Valeur V4 : {op.estimate.low:.2f}–{op.estimate.high:.2f} € "
        f"(centrale {op.estimate.central:.2f} €)\n"
        f"Prix max conseillé : {op.max_recommended:.2f} €\n"
        f"Décote : {op.discount_pct:.1f}%\n"
        f"Chemin : {op.valuation_path}\n"
        f"{timing}\n"
        "GRADE NON CONFIRMÉ — vérifier manuellement le certificat officiel "
        "et la photo du slab avant toute décision.\n"
        "Un échec de vérification peut être technique; ce n'est pas une preuve "
        "de mislisting à lui seul.\n\n"
        f"{op.lot.url}"
    )


def notify_with_manual_slab_review(
    op: watcher.Opportunity,
    decision: watcher.NotificationDecision,
) -> None:
    """Use one dedicated alert instead of duplicating the ordinary opportunity alert."""
    if _DELEGATE_NOTIFY is None:
        raise RuntimeError("manual slab review notify hook not installed")
    if MANUAL_REVIEW_REASON not in decision.reasons:
        return _DELEGATE_NOTIFY(op, decision)

    msg = _manual_review_message(op)
    watcher.log("*** NOTIFICATION: MANUAL SLAB GRADE REVIEW ***")
    print(msg, flush=True)

    if not watcher.NTFY_TOPIC:
        return None
    try:
        watcher.requests.post(
            f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={
                "Title": Header(MANUAL_REVIEW_TITLE, "utf-8").encode(),
                "Priority": "5" if decision.final_alert else "4",
                "Tags": "warning,card_index",
            },
            timeout=10,
        ).raise_for_status()
        watcher.log("Notification ntfy MANUAL SLAB GRADE REVIEW envoyée")
    except Exception as error:
        watcher.log(
            "Notification ntfy MANUAL SLAB GRADE REVIEW échouée: "
            f"{type(error).__name__}"
        )
    return None


def install_v4_manual_slab_review_notifications() -> None:
    """Install last, after the ordinary V4 notification-semantics wrapper."""
    global _DELEGATE_NOTIFICATION_DECISION
    global _DELEGATE_UPDATED_NOTIFICATION_STATE
    global _DELEGATE_NOTIFY
    global _INSTALLED

    if _INSTALLED:
        return
    _DELEGATE_NOTIFICATION_DECISION = watcher.notification_decision
    _DELEGATE_UPDATED_NOTIFICATION_STATE = watcher.updated_notification_state
    _DELEGATE_NOTIFY = watcher.notify
    watcher.notification_decision = notification_decision_with_manual_slab_review
    watcher.updated_notification_state = updated_notification_state_with_manual_slab_review
    watcher.notify = notify_with_manual_slab_review
    _INSTALLED = True
