from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import Header
from pathlib import Path
from typing import Callable, Optional

import requests

import watcher


# The normal production scan is externally dispatched about every ten minutes.
# A candidate first observed below 15 minutes can therefore jump straight from
# ~10 minutes remaining to ended.  This helper does NOT run a second scan.  It
# only arms auctions that have already passed the full V4 valuation gates, waits
# until roughly four minutes remain, then re-opens that exact GCC item page once
# to refresh price + timer before deciding whether to send the one-time final
# alert.
FINAL_CHECK_ARM_MINUTES = 15
FINAL_CHECK_WINDOW_MINUTES = 5
FINAL_CHECK_TARGET_MINUTES = 4
FINAL_CHECK_MAX_WAIT_SECONDS = 11 * 60
FINAL_CHECK_STALE_GRACE_SECONDS = 90


@dataclass(frozen=True)
class ArmedFinalCheck:
    url: str
    due_at: datetime
    estimated_end_at: datetime
    max_recommended: float


def _as_float(value: object) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _as_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def armed_final_checks(
    state: dict,
    now: Optional[datetime] = None,
) -> list[ArmedFinalCheck]:
    """Return only previously-notified auctions that still need a final check.

    The state written by ``watcher.updated_notification_state`` is deliberately
    sufficient here: fixed-price listings have no ``minutes_to_end``; auction
    entries crossing <=15 minutes set ``alert_15m_sent`` and retain the exact
    ``max_recommended`` used by the economic decision.
    """

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)

    notified = state.get("notified")
    if not isinstance(notified, dict):
        return []

    armed: list[ArmedFinalCheck] = []
    for url, raw in notified.items():
        if not isinstance(url, str) or not url or not isinstance(raw, dict):
            continue
        if bool(raw.get("final_alert_sent")):
            continue
        if not bool(raw.get("alert_15m_sent")):
            continue

        minutes = _as_float(raw.get("minutes_to_end"))
        current_price = _as_float(raw.get("price"))
        max_recommended = _as_float(raw.get("max_recommended"))
        notified_at = _as_datetime(raw.get("notified_at"))
        if (
            minutes is None
            or current_price is None
            or max_recommended is None
            or notified_at is None
        ):
            continue
        if not (FINAL_CHECK_WINDOW_MINUTES < minutes <= FINAL_CHECK_ARM_MINUTES):
            # <=5 min is already handled synchronously by watcher.notification_decision.
            continue
        if current_price > max_recommended:
            continue

        estimated_end = notified_at + timedelta(minutes=minutes)
        due_at = estimated_end - timedelta(minutes=FINAL_CHECK_TARGET_MINUTES)
        if estimated_end + timedelta(seconds=FINAL_CHECK_STALE_GRACE_SECONDS) <= reference:
            continue
        wait_seconds = max(0.0, (due_at - reference).total_seconds())
        if wait_seconds > FINAL_CHECK_MAX_WAIT_SECONDS:
            continue
        armed.append(
            ArmedFinalCheck(
                url=url,
                due_at=due_at,
                estimated_end_at=estimated_end,
                max_recommended=max_recommended,
            )
        )

    return sorted(armed, key=lambda item: (item.due_at, item.url))


def _format_money(value: float) -> str:
    return f"{value:.2f} €"


def send_final_last_chance_notification(
    lot: watcher.Lot,
    max_recommended: float,
) -> bool:
    """Send a minimal final alert; never bids, buys or changes the auction."""

    if not watcher.NTFY_TOPIC:
        watcher.log("Dernière chance: NTFY_TOPIC absent, alerte non marquée envoyée")
        return False

    title = "GCC AUCTION — DERNIÈRES 5 MIN — SOUS PRIX MAX"
    grade = watcher.format_grade_label(lot.grader, lot.grade) or "Grade inconnu"
    remaining = lot.end_text or (
        f"{lot.minutes_to_end} min" if lot.minutes_to_end is not None else "inconnue"
    )
    current_price = float(lot.current_price or 0.0)
    margin = max(0.0, max_recommended - current_price)
    message = (
        f"{title}\n\n"
        f"{lot.title or 'Carte GCC'}\n"
        f"{grade}\n\n"
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
        watcher.log("Dernière chance: notification ntfy envoyée")
        return True
    except Exception as error:
        watcher.log(
            f"Dernière chance: notification ntfy échouée ({type(error).__name__})"
        )
        return False


def _refresh_exact_auction(page, url: str) -> watcher.Lot:
    lot = watcher.Lot(
        url=url,
        title="",
        current_price=None,
        source_type="auction",
    )
    return watcher.inspect_item(page, lot, log_listing_errors=False)


def _mark_final_sent(
    state: dict,
    url: str,
    lot: watcher.Lot,
    sent_at: datetime,
) -> None:
    entry = state.setdefault("notified", {}).get(url)
    if not isinstance(entry, dict):
        return
    entry["price"] = lot.current_price
    entry["minutes_to_end"] = lot.minutes_to_end
    entry["notified_at"] = sent_at.astimezone(timezone.utc).isoformat()
    entry["final_alert_sent"] = True
    entry["last_reasons"] = [
        "vérification ciblée dernière chance toujours sous le prix max"
    ]


def run_targeted_final_checks(
    *,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep_fn: Callable[[float], None] = time.sleep,
    inspect_fn: Optional[Callable[[object, str], watcher.Lot]] = None,
    notify_fn: Callable[[watcher.Lot, float], bool] = send_final_last_chance_notification,
) -> int:
    """Run bounded last-chance checks after the normal V4 scan.

    No discovery, GCC history parsing, PSA APR, eBay Sold, PokeTrace or economic
    recomputation occurs here.  The existing ``max_recommended`` is immutable;
    the only live inputs refreshed are the exact item's current GCC price and
    countdown.
    """

    state = watcher.load_state()
    initial_now = now_fn()
    armed = armed_final_checks(state, initial_now)
    if not armed:
        watcher.log("Dernière chance: aucune enchère déjà valorisée à armer")
        return 0

    watcher.log(
        "Dernière chance: "
        f"{len(armed)} enchère(s) déjà valorisée(s) armée(s); "
        "aucun second scan ni appel marché externe"
    )

    # Unit tests inject an inspector and therefore do not need a browser.
    if inspect_fn is not None:
        page = object()
        close = lambda: None
    else:
        playwright = watcher.sync_playwright().start()
        browser = playwright.chromium.launch(headless=watcher.HEADLESS)
        session_file = Path("gcc_session.json")
        context_kwargs = {
            "locale": "fr-FR",
            "timezone_id": "Europe/Zurich",
        }
        if session_file.exists():
            context_kwargs["storage_state"] = str(session_file)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(watcher.TEXT_TIMEOUT)
        page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)

        def close() -> None:
            try:
                browser.close()
            finally:
                playwright.stop()

    inspector = inspect_fn or _refresh_exact_auction
    sent = 0
    try:
        for candidate in armed:
            current = now_fn()
            wait_seconds = max(0.0, (candidate.due_at - current).total_seconds())
            if wait_seconds > FINAL_CHECK_MAX_WAIT_SECONDS:
                watcher.log(
                    f"Dernière chance: attente hors plafond ignorée ({wait_seconds:.0f}s)"
                )
                continue
            if wait_seconds > 0:
                watcher.log(
                    f"Dernière chance: attente ciblée {wait_seconds:.0f}s avant relecture "
                    f"de {candidate.url}"
                )
                sleep_fn(wait_seconds)

            fresh = inspector(page, candidate.url)
            if fresh.inspection_error:
                watcher.log(
                    "Dernière chance: fiche non relue, aucune alerte finale "
                    f"({fresh.inspection_error})"
                )
                continue
            if fresh.current_price is None or fresh.minutes_to_end is None:
                watcher.log(
                    "Dernière chance: prix/timer non lisible, aucune alerte finale"
                )
                continue
            if not (0 < fresh.minutes_to_end <= FINAL_CHECK_WINDOW_MINUTES):
                watcher.log(
                    "Dernière chance: fenêtre finale non confirmée "
                    f"({fresh.minutes_to_end} min), aucune alerte"
                )
                continue
            if fresh.current_price > candidate.max_recommended:
                watcher.log(
                    "Dernière chance: prix monté au-dessus du plafond "
                    f"({_format_money(fresh.current_price)} > "
                    f"{_format_money(candidate.max_recommended)}), aucune alerte"
                )
                continue

            if notify_fn(fresh, candidate.max_recommended):
                sent_at = now_fn()
                _mark_final_sent(state, candidate.url, fresh, sent_at)
                watcher.save_state(state)
                sent += 1
    finally:
        close()

    watcher.log(f"Dernière chance: {sent} alerte(s) finale(s) envoyée(s)")
    return sent
