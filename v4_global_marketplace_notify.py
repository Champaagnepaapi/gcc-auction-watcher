from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import requests

from ecb_fx import ECBCurrencyConverter
import v4_global_live_confirmed as confirmed
import v4_global_live_shadow as base
import v4_global_marketplace_economic as marketplace_economic
import v4_global_notify as legacy_notify
from v4_global_marketplace_discovery import (
    MarketplaceListing,
    acknowledge_evaluated,
    cards_from_listings,
    load_discovery_state,
    reconcile_inventory,
    save_discovery_state,
    select_pending_listings,
)
from v4_global_marketplace_scan import (
    ScanStatus,
    build_identity_catalog,
    load_cardova_files,
    scan_comc_inventory,
    scan_fanatics_inventory,
    scan_gcc_inventory,
    scan_magi_inventory,
)
from v4_global_market_core import AUCTION_SNAPSHOT_LE5, FIXED_ASK


MODE_DRY = "READ_ONLY_MARKETPLACE_DISCOVERY_VALIDATION"
MODE_ACTIVE = "GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE"
TERMINAL_EXTERNAL = {
    "MATCHED",
    "CLEAN_NO_MATCH",
    "CLEAN_INSUFFICIENT",
    "STALE_OR_UNDATED",
    "BLOCKED_IDENTITY",
}
RETRY_EXTERNAL = {
    "PROVIDER_ERROR",
    "TRANSIENT_UNAVAILABLE",
    "RATE_LIMIT",
    "PENDING_BUDGET",
    "UNAVAILABLE",
}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _enabled() -> bool:
    return os.getenv("GLOBAL_NOTIFY_ENABLED", "false").strip().casefold() == "true"


def _scan(args: argparse.Namespace, *, observed_at: datetime):
    seeds, gcc_fair, catalog_status = build_identity_catalog(
        observed_at=observed_at,
        gcc_sold_pages=max(1, int(args.gcc_sold_pages)),
    )
    listings: list[MarketplaceListing] = []
    statuses: list[ScanStatus] = []

    gcc_rows, gcc_status = scan_gcc_inventory(
        observed_at=observed_at,
        max_pages_each=max(1, int(args.gcc_live_pages)),
    )
    listings.extend(gcc_rows)
    statuses.append(gcc_status)

    cardova_rows, cardova_status = load_cardova_files(
        observed_at=observed_at,
        fixed_path=Path(args.cardova_fixed_json) if args.cardova_fixed_json else None,
        auction_path=Path(args.cardova_auction_json) if args.cardova_auction_json else None,
    )
    listings.extend(cardova_rows)
    statuses.append(cardova_status)

    if not args.no_browser_sources and seeds:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()

            fanatics_rows, fanatics_status = scan_fanatics_inventory(
                page,
                seeds,
                observed_at=observed_at,
                max_detail_pages=max(1, int(args.browser_detail_cap)),
                scroll_rounds=max(1, int(args.browser_scroll_rounds)),
            )
            listings.extend(fanatics_rows)
            statuses.append(fanatics_status)

            magi_rows, magi_status = scan_magi_inventory(
                page,
                seeds,
                observed_at=observed_at,
                max_detail_pages=max(1, int(args.browser_detail_cap)),
            )
            listings.extend(magi_rows)
            statuses.append(magi_status)

            comc_rows, comc_status = scan_comc_inventory(
                page,
                seeds,
                observed_at=observed_at,
                max_pages=max(1, int(args.comc_pages)),
                max_detail_pages=max(1, int(args.browser_detail_cap)),
            )
            listings.extend(comc_rows)
            statuses.append(comc_status)

            context.close()
            browser.close()
    else:
        detail = "browser sources disabled" if args.no_browser_sources else "identity catalog unavailable"
        for market in ("fanatics", "magi", "comc"):
            statuses.append(ScanStatus(market, "SKIPPED", detail=detail, complete=False))

    deduped = {listing.stable_key: listing for listing in listings}
    return list(deduped.values()), statuses, gcc_fair, catalog_status


def _with_marketplace_evaluator(report: Mapping[str, Any]) -> dict[str, Any]:
    old_eval = confirmed.evaluate_card
    old_payload = confirmed.decision_payload
    confirmed.evaluate_card = marketplace_economic.evaluate_marketplace_card
    confirmed.decision_payload = marketplace_economic.decision_payload
    try:
        enriched = confirmed.enrich_confirmation(report)
    finally:
        confirmed.evaluate_card = old_eval
        confirmed.decision_payload = old_payload
    enriched["mode"] = MODE_ACTIVE if _enabled() else MODE_DRY
    enriched["economic_confirmation"]["marketplace_first"] = True
    enriched["economic_confirmation"]["gcc_fair_optional"] = True
    return enriched


def _card_by_identity(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    output = {}
    for card in report.get("cards", []):
        if not isinstance(card, Mapping):
            continue
        identity = marketplace_economic.legacy.identity_from_card(card)
        if identity is not None:
            output[identity.strict_key] = card
    return output


def _evaluation_complete(card: Mapping[str, Any]) -> bool:
    confirmation = card.get("economic_confirmation")
    if not isinstance(confirmation, Mapping):
        return False
    canonical = confirmation.get("external_canonical")
    canonical_status = str(canonical.get("status") or "") if isinstance(canonical, Mapping) else ""
    if canonical_status == "ERROR":
        return False
    if canonical_status in {"NO_MATCH", "AMBIGUOUS"}:
        return True
    ppt = confirmation.get("ppt")
    poketrace = confirmation.get("poketrace")
    ppt_status = str(ppt.get("status") or "UNAVAILABLE") if isinstance(ppt, Mapping) else "UNAVAILABLE"
    pt_status = str(poketrace.get("status") or "UNAVAILABLE") if isinstance(poketrace, Mapping) else "UNAVAILABLE"
    if ppt_status in RETRY_EXTERNAL and pt_status in RETRY_EXTERNAL:
        return False
    return ppt_status in TERMINAL_EXTERNAL or pt_status in TERMINAL_EXTERNAL


def marketplace_notification_candidates(report: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    output = []
    for card in report.get("cards", []):
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
        if str(decision.get("valuation_basis") or "") not in {"EXTERNAL_ONLY", "GCC_PLUS_EXTERNAL"}:
            continue
        try:
            offer_all_in = float(decision.get("offer_all_in_eur"))
            external_fair = float(decision.get("external_fair_eur"))
            confirmed_fair = float(decision.get("confirmed_fair_eur"))
            discount = float(decision.get("discount_pct"))
            sales = int(decision.get("external_sales_count"))
        except (TypeError, ValueError):
            continue
        if min(offer_all_in, external_fair, confirmed_fair) <= 0 or discount < 0 or sales < 3:
            continue
        offer = legacy_notify._matching_offer(card, decision)
        if offer is None or offer.get("evidence_type") not in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}:
            continue
        output.append((card, decision, offer))
    return output


def _format_notification(card: Mapping[str, Any], decision: Mapping[str, Any], offer: Mapping[str, Any]) -> tuple[str, str]:
    identity = card.get("identity") if isinstance(card.get("identity"), Mapping) else {}
    name = str(identity.get("name") or "Pokémon")
    number = str(identity.get("number") or "")
    grader = str(identity.get("grader") or "")
    grade = str(identity.get("grade") or "")
    language = str(identity.get("language") or "")
    evidence = str(offer.get("evidence_type") or "")
    evidence_label = "ASK FIXE" if evidence == FIXED_ASK else "SNAPSHOT ENCHÈRE ≤5 MIN"
    gcc = decision.get("gcc_fair_eur")
    gcc_line = f"€{float(gcc):.2f}" if gcc not in {None, ""} else "absent"
    body = "\n".join(
        (
            f"{name} {number} | {grader} {grade} | {language}",
            f"{decision.get('best_market')}: {evidence_label} rendu €{float(decision.get('offer_all_in_eur')):.2f}",
            f"Fair confirmé: €{float(decision.get('confirmed_fair_eur')):.2f} | décote {float(decision.get('discount_pct')):.1f}%",
            f"GCC SOLD fair: {gcc_line} | externe: €{float(decision.get('external_fair_eur')):.2f}",
            f"Base: {decision.get('valuation_basis')} | {decision.get('external_provider')} ({int(decision.get('external_sales_count'))} ventes agrégées)",
            "PAS UNE VENTE. Vérification manuelle uniquement.",
            str(decision.get("source_url") or ""),
        )
    )
    return "GLOBAL EDGE CONFIRMÉ", body


def _notify(
    report: Mapping[str, Any],
    *,
    notify_state_path: Path,
    now: datetime,
) -> dict[str, Any]:
    enabled = _enabled()
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if enabled and not topic:
        raise RuntimeError("GLOBAL_NOTIFY_ENABLED_WITHOUT_TOPIC")
    state, state_status = legacy_notify.load_state(notify_state_path, strict=enabled)
    ttl_days = _env_int("GLOBAL_NOTIFY_DEDUPE_TTL_DAYS", 14, 1)
    reprice = float(os.getenv("GLOBAL_NOTIFY_REPRICE_DROP_PCT", "5") or 5)
    candidates = marketplace_notification_candidates(report)
    sent = deduped = would_send = 0
    reasons: Counter[str] = Counter()
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    for card, decision, offer in candidates:
        fingerprint = legacy_notify.notification_fingerprint(card, decision)
        previous = state["notified"].get(fingerprint)
        deliver, reason = legacy_notify._should_deliver(
            previous,
            current_price=float(decision["offer_all_in_eur"]),
            now=now,
            ttl_days=ttl_days,
            reprice_drop_pct=reprice,
        )
        reasons[reason] += 1
        if not deliver:
            deduped += 1
            continue
        would_send += 1
        if not enabled:
            continue
        title, body = _format_notification(card, decision, offer)
        response = requests.post(
            f"{server}/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
            timeout=8,
        )
        response.raise_for_status()
        state["notified"][fingerprint] = {
            "notified_at": now.isoformat().replace("+00:00", "Z"),
            "offer_all_in_eur": float(decision["offer_all_in_eur"]),
            "source_url": str(decision.get("source_url") or ""),
        }
        legacy_notify.save_state(notify_state_path, state)
        sent += 1
    return {
        "enabled": enabled,
        "state_status": state_status,
        "confirmed_candidates": len(candidates),
        "would_send_after_dedupe": would_send,
        "sent": sent,
        "deduped": deduped,
        "reasons": dict(reasons),
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    enabled = _enabled()
    if enabled and not os.getenv("NTFY_TOPIC", "").strip():
        raise RuntimeError("GLOBAL_NOTIFY_ENABLED_WITHOUT_TOPIC")
    observed_at = datetime.now(timezone.utc)
    state_root = Path(args.state_dir)
    discovery_path = state_root / "discovery.json"
    notify_path = state_root / "notifications.json"
    discovery_state, discovery_state_status = load_discovery_state(discovery_path, strict=enabled)

    listings, statuses, gcc_fair, catalog_status = _scan(args, observed_at=observed_at)
    complete_markets = {status.market for status in statuses if status.status == "OK" and status.complete}
    discovery_state, reconciliation = reconcile_inventory(
        discovery_state,
        listings,
        observed_at=observed_at,
        complete_markets=complete_markets,
    )
    save_discovery_state(discovery_path, discovery_state)

    current = {listing.stable_key: listing for listing in listings}
    selected, selected_keys = select_pending_listings(
        discovery_state,
        current,
        limit=max(1, int(args.max_evaluations)),
    )
    fx_converter = ECBCurrencyConverter()
    fx = base._fx_map(fx_converter)
    cards = cards_from_listings(
        selected,
        currency_per_eur=fx,
        gcc_fair_by_identity=gcc_fair,
        observed_at=observed_at,
    )
    raw_report = {
        "schema_version": 4,
        "observed_at": observed_at.isoformat(),
        "mode": MODE_DRY,
        "notifications": False,
        "transactions": False,
        "cards": cards,
    }
    report = _with_marketplace_evaluator(raw_report) if cards else raw_report

    by_identity = _card_by_identity(report)
    acknowledged_keys = []
    for listing, key in zip(selected, selected_keys):
        card = by_identity.get(listing.identity.strict_key)
        if card is not None and _evaluation_complete(card):
            acknowledged_keys.append(key)
    discovery_state = acknowledge_evaluated(discovery_state, acknowledged_keys)
    save_discovery_state(discovery_path, discovery_state)

    delivery = _notify(report, notify_state_path=notify_path, now=observed_at)
    report["mode"] = MODE_ACTIVE if enabled else MODE_DRY
    report["notifications"] = enabled
    report["transactions"] = False
    report["marketplace_discovery"] = {
        "strategy": "MARKETPLACE_FIRST",
        "bootstrap_detects_edges": True,
        "baseline_then_incremental": True,
        "scan_status": [asdict(status) for status in statuses],
        "catalog_status": catalog_status,
        "discovery_state_status": discovery_state_status,
        "inventory": reconciliation,
        "selected_for_evaluation": len(selected),
        "acknowledged": len(acknowledged_keys),
        "pending_after": len(discovery_state.get("pending", [])),
        "seed_rotation_used_for_discovery": False,
        "known_gcc_history_identities_are_retrieval_catalog_only": True,
        "provider_disappearance_is_sold": False,
    }
    report["notification_delivery"] = delivery
    report["safety"] = {
        "identity_gate_relaxed": False,
        "marketplace_ask_is_sold": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "global_marketplace_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default=".global-marketplace-state")
    p.add_argument("--output-dir", default="global_marketplace_out")
    p.add_argument("--max-evaluations", type=int, default=10)
    p.add_argument("--gcc-sold-pages", type=int, default=30)
    p.add_argument("--gcc-live-pages", type=int, default=100)
    p.add_argument("--browser-detail-cap", type=int, default=200)
    p.add_argument("--browser-scroll-rounds", type=int, default=20)
    p.add_argument("--comc-pages", type=int, default=20)
    p.add_argument("--cardova-fixed-json", default="")
    p.add_argument("--cardova-auction-json", default="")
    p.add_argument("--no-browser-sources", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    report = run(args)
    print(
        json.dumps(
            {
                "mode": report.get("mode"),
                "marketplace_discovery": report.get("marketplace_discovery"),
                "economic_confirmation": report.get("economic_confirmation", {}),
                "notification_delivery": report.get("notification_delivery", {}),
                "safety": report.get("safety", {}),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
