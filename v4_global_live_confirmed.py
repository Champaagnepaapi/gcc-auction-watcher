"""Read-only Global Multi-Vault economic confirmation diagnostic.

Runs the hardened Global shadow, then requires an exact correlated external
aggregate (PPT and/or PokeTrace/eBay) before marking any current ASK as a
would-notify opportunity. Notifications and transactions remain hard-disabled in
this validation runner; activation is a separate post-live decision.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

from ecb_fx import ECBCurrencyConverter
import v4_canonical_multimarket as multimarket
import v4_global_live_shadow as base
import v4_global_live_shadow_hardened as hardened
from v4_global_economic_confirmation import (
    ExternalAggregate,
    decision_payload,
    evaluate_card,
    fetch_poketrace_external,
    identity_from_card,
    ppt_external,
)
from v4_global_ppt_confirmation import PptBudget, PptSnapshot, fetch_snapshot


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


def _ppt_payload(snapshot: PptSnapshot) -> dict[str, object]:
    payload = asdict(snapshot)
    if snapshot.last_sale_at is not None:
        payload["last_sale_at"] = snapshot.last_sale_at.isoformat()
    payload["production_decision_use"] = snapshot.status == "MATCHED"
    payload["notification_use"] = False
    return payload


def _external_payload(external: ExternalAggregate) -> dict[str, object]:
    payload = asdict(external)
    if external.last_sale_at is not None:
        payload["last_sale_at"] = external.last_sale_at.isoformat()
    payload["notification_use"] = False
    return payload


def enrich_confirmation(report: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(report)
    now_raw = output.get("observed_at")
    try:
        now = datetime.fromisoformat(str(now_raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    ppt_key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    ppt_budget = PptBudget(
        max_http_calls=_env_int("GLOBAL_PPT_MAX_HTTP_CALLS", 8, 1),
        max_credits=_env_int("GLOBAL_PPT_MAX_CREDITS", 40, 1),
        daily_remaining_floor=_env_int("GLOBAL_PPT_DAILY_REMAINING_FLOOR", 15_000, 0),
        interval_seconds=_env_float("GLOBAL_PPT_INTERVAL_SECONDS", 1.10, 0.0),
    )
    ppt_session = requests.Session()
    fx = ECBCurrencyConverter()
    poketrace_budget = multimarket.RequestBudget()
    min_discount = _env_float("GLOBAL_CONFIRM_MIN_DISCOUNT_PCT", 30.0, 0.0)

    cards: list[dict[str, Any]] = []
    confirmed = 0
    conflicts = 0
    no_external = 0
    ppt_matched = 0
    poketrace_matched = 0

    for raw_card in output.get("cards", []):
        card = dict(raw_card) if isinstance(raw_card, Mapping) else {}
        identity = identity_from_card(card)
        if identity is None:
            ppt_snapshot = PptSnapshot("BLOCKED_IDENTITY")
            ppt_evidence = ExternalAggregate("PokemonPriceTracker", "BLOCKED_IDENTITY")
            poketrace = ExternalAggregate("PokeTrace/eBay SOLD", "BLOCKED_IDENTITY")
        else:
            ppt_snapshot = fetch_snapshot(
                identity,
                api_key=ppt_key,
                budget=ppt_budget,
                session=ppt_session,
                fx=fx,
                timeout=_env_float("GLOBAL_PPT_TIMEOUT_SECONDS", 15.0, 1.0),
                now=now,
            )
            ppt_evidence = ppt_external(ppt_snapshot, now=now)
            poketrace = fetch_poketrace_external(identity, budget=poketrace_budget, now=now)

        if ppt_snapshot.status == "MATCHED":
            ppt_matched += 1
        if poketrace.status == "MATCHED":
            poketrace_matched += 1
        decision = evaluate_card(
            card,
            ppt=ppt_evidence,
            poketrace=poketrace,
            min_discount=min_discount,
        )
        if decision.status == "MULTIMARKET_CONFIRMED":
            confirmed += 1
        elif decision.status == "MARKET_CONFLICT_BLOCKED":
            conflicts += 1
        elif decision.status == "NO_EXTERNAL_CONFIRMATION":
            no_external += 1
        card["economic_confirmation"] = {
            "ppt": _ppt_payload(ppt_snapshot),
            "poketrace": _external_payload(poketrace),
            "decision": decision_payload(decision),
        }
        cards.append(card)

    output["cards"] = cards
    output["schema_version"] = max(2, int(output.get("schema_version") or 1))
    output["mode"] = "READ_ONLY_ECONOMIC_CONFIRMATION"
    output["notifications"] = False
    output["transactions"] = False
    output["economic_confirmation"] = {
        "enabled": True,
        "notification_capable": False,
        "activation_requires_separate_validation": True,
        "min_discount_pct": min_discount,
        "external_family": "EBAY_GRADED_AGGREGATE",
        "ppt_and_poketrace_count_as_independent_markets": False,
        "confirmed_would_notify": confirmed,
        "market_conflicts_blocked": conflicts,
        "no_external_confirmation": no_external,
        "ppt_matched": ppt_matched,
        "poketrace_matched": poketrace_matched,
        "ppt_http_calls": ppt_budget.http_calls,
        "ppt_credits": ppt_budget.credits,
        "ppt_daily_remaining": ppt_budget.daily_remaining,
        "ppt_blocked_reason": ppt_budget.blocked_reason,
        "poketrace_requests": poketrace_budget.poketrace_requests,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
    }
    return output


def run(args) -> dict[str, Any]:
    shadow = hardened.run(args)
    report = enrich_confirmation(shadow)
    output_dir = Path(args.output_dir)
    base.write_report(report, output_dir)
    (output_dir / "global_market_confirmed.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def parser():
    return hardened.parser()


def main() -> int:
    args = parser().parse_args()
    report = run(args)
    print(
        json.dumps(
            {
                "mode": report.get("mode"),
                "cards": len(report.get("cards", [])),
                "economic_confirmation": report.get("economic_confirmation", {}),
                "output": str(Path(args.output_dir).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
