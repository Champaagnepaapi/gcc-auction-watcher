from __future__ import annotations

import re
from email.header import Header

import requests

import watcher


_BAD_TITLE_PREFIXES = (
    "aucune note plus elevee",
    "aucune note plus élevée",
    "population",
    "note :",
    "note:",
)


def _normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _body_field(body: str, *labels: str) -> str:
    """Read a label/value pair from GCC body text without inventing metadata."""
    if not body:
        return ""
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*(?:\n|:)\s*([^\n\r]{{1,160}})",
            body,
            re.I,
        )
        if match:
            value = _normalize_space(match.group(1))
            if value:
                return value
    return ""


def _safe_card_name(lot: watcher.Lot) -> str:
    # The dedicated GCC item field is preferred over the page heading. This
    # prevents UI badges such as "Aucune note plus élevée" from becoming the
    # card name in the <=5 min notification.
    explicit = _body_field(lot.body, "Personnage", "Character", "Card Name", "Item Name")
    if explicit:
        return explicit

    identity = watcher.extract_card_identity(lot)
    candidate = _normalize_space(identity.get("core") or lot.title)
    lowered = candidate.casefold()
    if candidate and not any(lowered.startswith(prefix) for prefix in _BAD_TITLE_PREFIXES):
        return candidate
    return "Carte GCC"


def _identity_lines(lot: watcher.Lot) -> list[str]:
    identity = watcher.extract_card_identity(lot)
    name = _safe_card_name(lot)
    reference = _normalize_space(lot.card_number or identity.get("ref"))
    if reference and not reference.startswith("#"):
        reference = f"#{reference}"

    first = f"{name} {reference}".strip()
    lines = [first]

    series = _normalize_space(lot.card_set or identity.get("series"))
    year = _normalize_space(lot.year or identity.get("year"))
    language = _normalize_space(lot.language or identity.get("language"))
    variant = _normalize_space(lot.variant)

    details = [value for value in (series, year, language, variant) if value]
    if details:
        lines.append(" · ".join(details))

    grade = watcher.format_grade_label(lot.grader, lot.grade) or "Grade inconnu"
    lines.append(grade)
    return lines


def _format_money(value: float) -> str:
    return f"{value:.2f} €"


def send_identity_rich_final_notification(
    lot: watcher.Lot,
    max_recommended: float,
) -> bool:
    """Final <=5 min alert with card identity + refreshed price/timer only.

    This notifier does not discover, value, bid, buy, checkout, or call market
    providers. It only improves the presentation of the already-armed final
    alert while preserving the immutable persisted max_recommended.
    """
    if not watcher.NTFY_TOPIC:
        watcher.log("Dernière chance: NTFY_TOPIC absent, alerte non marquée envoyée")
        return False

    title = "GCC AUCTION — DERNIÈRES 5 MIN — SOUS PRIX MAX"
    remaining = lot.end_text or (
        f"{lot.minutes_to_end} min" if lot.minutes_to_end is not None else "inconnue"
    )
    current_price = float(lot.current_price or 0.0)
    margin = max(0.0, max_recommended - current_price)
    identity_block = "\n".join(_identity_lines(lot))

    message = (
        f"{title}\n\n"
        f"{identity_block}\n\n"
        f"Prix actuel : {_format_money(current_price)}\n"
        f"Prix max conseillé : {_format_money(max_recommended)}\n"
        f"Marge restante sous plafond : {_format_money(margin)}\n"
        f"Fin : {remaining}\n\n"
        "Vérification ciblée finale : prix et timer GCC relus sur cette fiche uniquement.\n"
        f"{lot.url}"
    )

    try:
        requests.post(
            f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": Header(title, "utf-8").encode(),
                "Priority": "5",
                "Tags": "rotating_light,moneybag",
            },
            timeout=10,
        ).raise_for_status()
        watcher.log("Dernière chance: notification ntfy enrichie envoyée")
        return True
    except Exception as error:
        watcher.log(
            f"Dernière chance: notification ntfy enrichie échouée ({type(error).__name__})"
        )
        return False
