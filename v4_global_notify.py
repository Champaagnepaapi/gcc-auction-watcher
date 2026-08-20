"""Notification-capable Global Multi-Vault runner, default-off and fail-closed.

This runner reuses the validated read-only Global confirmation pipeline and exact
provider-coordinate bridge. Notification delivery is a final side effect only for
already-confirmed MULTIMARKET_CONFIRMED decisions. No purchase/bid/checkout/payment
capability exists here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import requests

import v4_global_live_confirmed as confirmed
import v4_global_live_shadow as base
from v4_global_market_core import AUCTION_SNAPSHOT_LE5, FIXED_ASK
from v4_global_provider_exact_bridge import install_global_provider_exact_bridge


STATE_SCHEMA_VERSION = 1
DEFAULT_DEDUPE_TTL_DAYS = 14
DEFAULT_REPRICE_DROP_PCT = 5.0
_TRUE = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in _TRUE


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "cursor": 0,
        "notified": {},
    }


def _validate_state(payload: object) -> tuple[bool, str]:
    if not isinstance(payload, Mapping):
        return False, "STATE_NOT_OBJECT"
    try:
        schema_version = int(payload.get("schema_version") or 0)
    except (TypeError, ValueError):
        return False, "STATE_SCHEMA_MISMATCH"
    if schema_version != STATE_SCHEMA_VERSION:
        return False, "STATE_SCHEMA_MISMATCH"
    try:
        cursor = int(payload.get("cursor", 0))
    except (TypeError, ValueError):
        return False, "STATE_CURSOR_INVALID"
    if cursor < 0:
        return False, "STATE_CURSOR_INVALID"
    notified = payload.get("notified")
    if not isinstance(notified, Mapping):
        return False, "STATE_NOTIFIED_INVALID"
    for key, raw in notified.items():
        if not isinstance(key, str) or not key or not isinstance(raw, Mapping):
            return False, "STATE_ENTRY_INVALID"
        if _parse_time(raw.get("notified_at")) is None:
            return False, "STATE_ENTRY_TIME_INVALID"
        try:
            price = float(raw.get("offer_all_in_eur"))
        except (TypeError, ValueError):
            return False, "STATE_ENTRY_PRICE_INVALID"
        if price <= 0:
            return False, "STATE_ENTRY_PRICE_INVALID"
    return True, ""


def load_state(path: Path, *, strict: bool) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return _empty_state(), "STATE_NEW"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        if strict:
            raise RuntimeError(f"GLOBAL_NOTIFY_STATE_INVALID:{type(error).__name__}") from error
        return _empty_state(), f"STATE_RESET:{type(error).__name__}"
    ok, reason = _validate_state(payload)
    if not ok:
        if strict:
            raise RuntimeError(f"GLOBAL_NOTIFY_STATE_INVALID:{reason}")
        return _empty_state(), f"STATE_RESET:{reason}"
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "cursor": int(payload.get("cursor", 0)),
        "notified": {str(k): dict(v) for k, v in dict(payload.get("notified", {})).items()},
    }, "STATE_OK"


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _identity_key(card: Mapping[str, Any]) -> str:
    raw = card.get("identity")
    identity = raw if isinstance(raw, Mapping) else {}
    fields = (
        "name",
        "set_name",
        "number",
        "language",
        "grader",
        "grade",
        "edition",
        "finish",
        "variant",
    )
    return "|".join(str(identity.get(field) or "").strip().casefold() for field in fields)


def notification_fingerprint(card: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    raw = "|".join(
        (
            _identity_key(card),
            str(decision.get("best_market") or "").strip().casefold(),
            str(decision.get("source_url") or "").strip(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _matching_offer(card: Mapping[str, Any], decision: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    source_url = str(decision.get("source_url") or "").strip()
    market = str(decision.get("best_market") or "").strip().casefold()
    raw = card.get("offers")
    offers = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
    for offer in offers:
        if not isinstance(offer, Mapping):
            continue
        if str(offer.get("market") or "").strip().casefold() != market:
            continue
        if str(offer.get("source_url") or "").strip() != source_url:
            continue
        if offer.get("evidence_type") not in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}:
            continue
        try:
            all_in = float(offer.get("all_in_eur"))
        except (TypeError, ValueError):
            continue
        if all_in > 0:
            return offer
    return None


def confirmed_notification_candidates(report: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    output: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    raw_cards = report.get("cards")
    cards = raw_cards if isinstance(raw_cards, Sequence) and not isinstance(raw_cards, (str, bytes)) else []
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        confirmation = card.get("economic_confirmation")
        if not isinstance(confirmation, Mapping):
            continue
        decision = confirmation.get("decision")
        if not isinstance(decision, Mapping):
            continue
        if decision.get("status") != "MULTIMARKET_CONFIRMED" or decision.get("would_notify") is not True:
            continue
        if decision.get("ask_is_sold") is not False:
            continue
        try:
            offer_all_in = float(decision.get("offer_all_in_eur"))
            gcc_fair = float(decision.get("gcc_fair_eur"))
            external_fair = float(decision.get("external_fair_eur"))
            confirmed_fair = float(decision.get("confirmed_fair_eur"))
            discount = float(decision.get("discount_pct"))
            external_sales = int(decision.get("external_sales_count") or 0)
        except (TypeError, ValueError):
            continue
        if (
            offer_all_in <= 0
            or gcc_fair <= 0
            or external_fair <= 0
            or confirmed_fair <= 0
            or discount < 0
            or external_sales < 3
        ):
            continue
        if not str(decision.get("external_provider") or "").strip():
            continue
        source_url = str(decision.get("source_url") or "").strip()
        if not source_url.startswith(("https://", "http://")):
            continue
        offer = _matching_offer(card, decision)
        if offer is None:
            continue
        output.append((card, decision, offer))
    return output


def _should_deliver(
    previous: Optional[Mapping[str, Any]],
    *,
    current_price: float,
    now: datetime,
    ttl_days: int,
    reprice_drop_pct: float,
) -> tuple[bool, str]:
    if previous is None:
        return True, "FIRST_SEEN"
    previous_at = _parse_time(previous.get("notified_at"))
    if previous_at is None:
        return True, "PREVIOUS_TIME_INVALID"
    if now - previous_at >= timedelta(days=max(1, ttl_days)):
        return True, "TTL_EXPIRED"
    try:
        previous_price = float(previous.get("offer_all_in_eur"))
    except (TypeError, ValueError):
        return True, "PREVIOUS_PRICE_INVALID"
    threshold = previous_price * (1.0 - max(0.0, reprice_drop_pct) / 100.0)
    if current_price <= threshold + 1e-9:
        return True, "PRICE_IMPROVED"
    return False, "DEDUPED"


def _format_notification(card: Mapping[str, Any], decision: Mapping[str, Any], offer: Mapping[str, Any]) -> tuple[str, str]:
    identity = card.get("identity")
    ident = identity if isinstance(identity, Mapping) else {}
    evidence = str(offer.get("evidence_type") or "")
    evidence_label = "ASK FIXE" if evidence == FIXED_ASK else "SNAPSHOT ENCHÈRE ≤5 MIN"
    title = "GLOBAL EDGE CONFIRMÉ ≥30%"
    body = (
        f"{ident.get('name','')} {ident.get('number','')} · {str(ident.get('language','')).upper()} "
        f"{ident.get('grader','')} {ident.get('grade','')}\n"
        f"{decision.get('best_market','')} · {evidence_label}\n"
        f"All-in: €{float(decision.get('offer_all_in_eur')):.2f}\n"
        f"Fair confirmé: €{float(decision.get('confirmed_fair_eur')):.2f} "
        f"(GCC €{float(decision.get('gcc_fair_eur')):.2f} / externe €{float(decision.get('external_fair_eur')):.2f})\n"
        f"Décote: {float(decision.get('discount_pct')):.1f}%\n"
        f"Externe: {decision.get('external_provider','')} · {int(decision.get('external_sales_count') or 0)} ventes agrégées\n"
        "ASK/SNAPSHOT, PAS UNE VENTE. Vérification manuelle uniquement.\n"
        f"{decision.get('source_url','')}"
    )
    return title, body


def _post_notification(server: str, topic: str, *, title: str, body: str) -> None:
    requests.post(
        f"{server.rstrip('/')}/{topic}",
        data=body.encode("utf-8"),
        headers={"Title": title, "Priority": "high"},
        timeout=8,
    ).raise_for_status()


def _rotating_seed_builder(cursor: int, tracker: dict[str, int]):
    original = base.build_seed_panel

    def build(sales, *, observed_at, max_identities):
        all_seeds = original(
            sales,
            observed_at=observed_at,
            max_identities=max(1, len(sales)),
        )
        total = len(all_seeds)
        tracker["total"] = total
        if total == 0:
            tracker["start"] = 0
            tracker["next"] = 0
            tracker["selected"] = 0
            return []
        start = max(0, int(cursor)) % total
        count = min(max(1, int(max_identities)), total)
        selected = [all_seeds[(start + offset) % total] for offset in range(count)]
        tracker["start"] = start
        tracker["next"] = (start + count) % total
        tracker["selected"] = count
        return selected

    return build


def _install_external_stack_with_exact_bridge(original_install) -> None:
    original_install()
    install_global_provider_exact_bridge()


def run(args: argparse.Namespace) -> dict[str, Any]:
    notify_enabled = _env_bool("GLOBAL_NOTIFY_ENABLED", False)
    topic = os.getenv("NTFY_TOPIC", "").strip()
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip() or "https://ntfy.sh"
    ttl_days = _env_int("GLOBAL_NOTIFY_DEDUPE_TTL_DAYS", DEFAULT_DEDUPE_TTL_DAYS, 1)
    reprice_drop_pct = _env_float("GLOBAL_NOTIFY_REPRICE_DROP_PCT", DEFAULT_REPRICE_DROP_PCT, 0.0)

    if notify_enabled and not topic:
        raise RuntimeError("GLOBAL_NOTIFY_ENABLED_WITHOUT_TOPIC")

    state_path = Path(args.state)
    state, state_status = load_state(state_path, strict=notify_enabled)
    old_cursor = int(state.get("cursor", 0))
    tracker: dict[str, int] = {"start": old_cursor, "next": old_cursor, "selected": 0, "total": 0}

    original_builder = base.build_seed_panel
    original_install = confirmed.install_global_external_market_stack
    base.build_seed_panel = _rotating_seed_builder(old_cursor, tracker)
    confirmed.install_global_external_market_stack = (
        lambda: _install_external_stack_with_exact_bridge(original_install)
    )
    try:
        report = confirmed.run(args)
    finally:
        base.build_seed_panel = original_builder
        confirmed.install_global_external_market_stack = original_install

    observed_at = _parse_time(report.get("observed_at")) or _utc_now()
    candidates = confirmed_notification_candidates(report)
    sent = 0
    deduped = 0
    would_send = 0
    reasons: dict[str, int] = {}
    notified = dict(state.get("notified", {}))

    # Keep stale entries bounded; TTL expiry itself still makes an offer eligible again.
    prune_before = observed_at - timedelta(days=max(2, ttl_days * 2))
    notified = {
        key: dict(value)
        for key, value in notified.items()
        if (_parse_time(value.get("notified_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= prune_before
    }
    state["notified"] = notified
    state["updated_at"] = _iso(observed_at)

    for card, decision, offer in candidates:
        fingerprint = notification_fingerprint(card, decision)
        current_price = float(decision.get("offer_all_in_eur"))
        deliver, reason = _should_deliver(
            notified.get(fingerprint),
            current_price=current_price,
            now=observed_at,
            ttl_days=ttl_days,
            reprice_drop_pct=reprice_drop_pct,
        )
        reasons[reason] = reasons.get(reason, 0) + 1
        if not deliver:
            deduped += 1
            continue
        would_send += 1
        if not notify_enabled:
            continue
        title, body = _format_notification(card, decision, offer)
        try:
            _post_notification(server, topic, title=title, body=body)
        except Exception:
            # Preserve successful deliveries already made, but deliberately keep
            # the old cursor so the failed batch is retried next schedule.
            save_state(state_path, state)
            raise
        sent += 1
        notified[fingerprint] = {
            "notified_at": _iso(observed_at),
            "offer_all_in_eur": round(current_price, 2),
            "source_url": str(decision.get("source_url") or ""),
            "best_market": str(decision.get("best_market") or ""),
        }
        state["notified"] = notified
        save_state(state_path, state)

    # Advance durable rotation only after the complete notification batch succeeds.
    state["cursor"] = int(tracker.get("next", old_cursor))
    state["updated_at"] = _iso(observed_at)
    save_state(state_path, state)

    report["mode"] = "GLOBAL_NOTIFICATION_ACTIVE" if notify_enabled else "READ_ONLY_NOTIFICATION_VALIDATION"
    report["notifications"] = bool(notify_enabled)
    report["transactions"] = False
    economic = report.get("economic_confirmation")
    if isinstance(economic, dict):
        economic["notification_capable"] = True
        economic["notification_enabled"] = bool(notify_enabled)
        economic["activation_requires_separate_validation"] = not bool(notify_enabled)
    report["notification_delivery"] = {
        "capable": True,
        "enabled": bool(notify_enabled),
        "state_status": state_status,
        "state_schema_version": STATE_SCHEMA_VERSION,
        "dedupe_ttl_days": ttl_days,
        "reprice_drop_pct": reprice_drop_pct,
        "confirmed_candidates": len(candidates),
        "would_send_after_dedupe": would_send,
        "sent": sent,
        "deduped": deduped,
        "reasons": reasons,
        "rotation": {
            "eligible_seed_total": int(tracker.get("total", 0)),
            "start_cursor": int(tracker.get("start", old_cursor)),
            "selected": int(tracker.get("selected", 0)),
            "next_cursor": int(tracker.get("next", old_cursor)),
        },
        "marketplace_evidence_is_sold": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }

    output_dir = Path(args.output_dir)
    base.write_report(report, output_dir)
    (output_dir / "global_market_confirmed.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "global_notification_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def parser() -> argparse.ArgumentParser:
    value = confirmed.parser()
    value.description = "Global notification candidate runner; delivery is env-gated and default-off"
    value.add_argument("--state", default=".global-notify-state/state.json")
    return value


def main() -> int:
    args = parser().parse_args()
    report = run(args)
    print(
        json.dumps(
            {
                "mode": report.get("mode"),
                "cards": len(report.get("cards", [])),
                "economic_confirmation": report.get("economic_confirmation", {}),
                "notification_delivery": report.get("notification_delivery", {}),
                "output": str(Path(args.output_dir).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
