from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import Header
from pathlib import Path
from typing import Callable, Optional

import requests

import watcher


# The fast-lane final auction checker runs independently from the main scan.
# It is the single authoritative owner of the <=5 min last-chance alert.
# It does NOT perform discovery or valuation. It inspects only already-armed
# auctions (persisted with alert_15m_sent=True and remaining <= 15 min),
# refreshes their exact GCC price and timer, and sends the final alert if
# they remain under the immutable persisted max_recommended.
FINAL_CHECK_ARM_MINUTES = 15
FINAL_CHECK_WINDOW_MINUTES = 5
FINAL_CHECK_STALE_GRACE_SECONDS = 90
FINAL_ALERTS_STATE_FILE = os.getenv("FINAL_ALERTS_STATE_FILE", "final_alerts.json")


def is_fast_lane_enabled(override: Optional[bool] = None) -> bool:
    """True ONLY when explicitly enabled via override or truthy V4_FAST_LANE_FINAL_CHECK_ENABLED (true/1/yes)."""
    if override is not None:
        return override
    val = os.getenv("V4_FAST_LANE_FINAL_CHECK_ENABLED")
    if not val:
        return False
    return val.strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class ArmedFinalCheck:
    url: str
    due_at: datetime
    estimated_end_at: datetime
    max_recommended: float
    estimated_minutes_remaining: float


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


def load_final_alerts(filepath: Optional[Path | str] = None) -> dict[str, dict]:
    """Load the dedicated final-alert deduplication namespace."""
    path = Path(filepath or FINAL_ALERTS_STATE_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as error:
        watcher.log(f"Avertissement lecture final_alerts: {type(error).__name__}")
        return {}


def save_final_alerts(
    final_alerts: dict[str, dict], filepath: Optional[Path | str] = None
) -> None:
    """Save the dedicated final-alert deduplication namespace."""
    path = Path(filepath or FINAL_ALERTS_STATE_FILE)
    try:
        path.write_text(
            json.dumps(final_alerts, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as error:
        watcher.log(f"Erreur sauvegarde final_alerts: {type(error).__name__}")


def is_final_alert_sent(
    url: str,
    state: dict,
    final_alerts: Optional[dict[str, dict]] = None,
) -> bool:
    """Check if a final alert was already recorded in either state source."""
    if final_alerts is not None and url in final_alerts:
        return True
    notified = state.get("notified")
    if isinstance(notified, dict):
        raw = notified.get(url)
        if isinstance(raw, dict) and bool(raw.get("final_alert_sent")):
            return True
    return False


def armed_final_checks(
    state: dict,
    now: Optional[datetime] = None,
    *,
    final_alerts: Optional[dict[str, dict]] = None,
    due_only: bool = True,
    max_due_minutes: float = FINAL_CHECK_WINDOW_MINUTES,
) -> list[ArmedFinalCheck]:
    """Return previously-notified auctions that are currently due for final check.

    Accepts any already-armed auction with stored countdown <= 15 minutes
    (including items refreshed to <= 5 minutes by the normal watcher) as long
    as the calculated or refreshed live end time is within the target window.
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
        if is_final_alert_sent(url, state, final_alerts):
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
        if not (0 < minutes <= FINAL_CHECK_ARM_MINUTES):
            continue
        if current_price > max_recommended:
            continue

        estimated_end = notified_at + timedelta(minutes=minutes)
        if estimated_end + timedelta(seconds=FINAL_CHECK_STALE_GRACE_SECONDS) <= reference:
            # Auction has already completed past the grace window.
            continue

        remaining_seconds = (estimated_end - reference).total_seconds()
        remaining_minutes = max(0.0, remaining_seconds / 60.0)
        if due_only and remaining_minutes > max_due_minutes:
            # Not yet in the <=5 min window.
            continue

        armed.append(
            ArmedFinalCheck(
                url=url,
                due_at=estimated_end - timedelta(minutes=FINAL_CHECK_WINDOW_MINUTES),
                estimated_end_at=estimated_end,
                max_recommended=max_recommended,
                estimated_minutes_remaining=remaining_minutes,
            )
        )

    return sorted(armed, key=lambda item: (item.estimated_end_at, item.url))


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


def run_targeted_final_checks(
    *,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    inspect_fn: Optional[Callable[[object, str], watcher.Lot]] = None,
    notify_fn: Callable[[watcher.Lot, float], bool] = send_final_last_chance_notification,
    final_alerts_file: Optional[Path | str] = None,
    fast_lane_enabled: Optional[bool] = None,
) -> int:
    """Run immediate zero-sleep last-chance checks for due auctions.

    No discovery, GCC history parsing, PSA APR, eBay Sold, PokeTrace or economic
    recomputation occurs here. The existing ``max_recommended`` is immutable;
    the only live inputs refreshed are the exact item's current GCC price and
    countdown.

    ``state.json`` remains read-only in this workflow. Final alert deduplication
    is recorded exclusively into ``final_alerts.json``.
    """

    if not is_fast_lane_enabled(fast_lane_enabled):
        watcher.log(
            "Dernière chance: fast-lane désactivée (V4_FAST_LANE_FINAL_CHECK_ENABLED absent ou false)"
        )
        return 0

    state = watcher.load_state()
    final_alerts = load_final_alerts(final_alerts_file)
    initial_now = now_fn()
    armed = armed_final_checks(
        state, initial_now, final_alerts=final_alerts, due_only=True
    )
    if not armed:
        watcher.log("Dernière chance: aucune enchère due (<=5 min) à vérifier")
        return 0

    watcher.log(
        "Dernière chance: "
        f"{len(armed)} enchère(s) due(s) à vérifier immédiatement; "
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
                final_alerts[candidate.url] = {
                    "sent_at": sent_at.astimezone(timezone.utc).isoformat(),
                    "price": fresh.current_price,
                    "minutes_to_end": fresh.minutes_to_end,
                }
                save_final_alerts(final_alerts, final_alerts_file)
                sent += 1
    finally:
        close()

    watcher.log(f"Dernière chance: {sent} alerte(s) finale(s) envoyée(s)")
    return sent


_ORIGINAL_NOTIFICATION_DECISION = watcher.notification_decision


def fast_lane_guarded_notification_decision(
    op: watcher.Opportunity,
    previous: Optional[dict],
    *,
    final_alerts_file: Optional[Path | str] = None,
    fast_lane_enabled: Optional[bool] = None,
) -> watcher.NotificationDecision:
    """Notification decision delegating <=5 min final alerts to the fast lane.

    When fast lane mode is enabled, the normal watcher emits initial opportunity
    alerts and <=15 min reminders ('passage sous 15 minutes'), but suppresses
    the synchronous <=5 min final alert to prevent duplicate notifications.
    """

    enabled = is_fast_lane_enabled(fast_lane_enabled)

    # Check if the fast lane has already emitted an alert for this item
    final_alerts = load_final_alerts(final_alerts_file)
    if op.lot.url in final_alerts and isinstance(previous, dict):
        previous["final_alert_sent"] = True

    decision = _ORIGINAL_NOTIFICATION_DECISION(op, previous)
    if enabled and decision.final_alert:
        filtered_reasons = tuple(
            r
            for r in decision.reasons
            if r != "toujours sous le prix max dans les 5 dernières minutes"
        )
        return watcher.NotificationDecision(
            should_notify=bool(filtered_reasons),
            final_alert=False,
            reasons=filtered_reasons,
        )
    return decision


def install_fast_lane_notification_guard(
    *, final_alerts_file: Optional[Path | str] = None
) -> None:
    """Install guard so normal watcher delegates <=5 min alerts to fast lane."""

    def _guard(op, prev):
        return fast_lane_guarded_notification_decision(
            op, prev, final_alerts_file=final_alerts_file, fast_lane_enabled=None
        )

    watcher.notification_decision = _guard
