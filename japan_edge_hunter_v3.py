"""Japan Edge Hunter V3: GCC + external exact graded SOLD context.

V3 keeps Japanese marketplace listings as ASK inventory only. Discovery still starts
from strict Japanese PSA 10 GCC SOLD references, then each exact cheap candidate is
checked against an independent exact Japanese PSA 10 graded market aggregate from
PokeTrace/eBay SOLD data before high-priority notification.

PokemonPriceTracker can additionally be displayed as a separate JP PSA10 market
context after the economic decision is already made. PPT never creates/suppresses
an opportunity or changes the V3 fair value/verdict.

No purchase, bid, checkout or payment code exists here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Optional

import requests

import japan_edge_hunter as base
import japan_edge_hunter_v2 as v2
import japan_edge_ppt_notification_context as ppt_context
import v4_canonical_multimarket as multimarket
import watcher


GLOBAL_CONFLICT_RATIO = 1.35
GLOBAL_PROVIDER = "PokeTrace/eBay SOLD"


@dataclass(frozen=True)
class ExternalReference:
    status: str
    fair_eur: Optional[float] = None
    sold_count: int = 0
    source: str = GLOBAL_PROVIDER
    evidence_strength: str = "UNAVAILABLE"
    note: str = ""


@dataclass(frozen=True)
class MarketDecision:
    status: str
    gcc_fair_eur: float
    external_fair_eur: Optional[float]
    global_fair_eur: float
    discount_vs_gcc_pct: float
    discount_vs_external_pct: Optional[float]
    discount_vs_global_pct: float
    market_ratio: Optional[float]
    should_notify: bool
    priority: str


def _op_from_dict(raw: dict) -> base.Opportunity:
    ident = base.Identity(**raw["identity"])
    values = dict(raw)
    values["identity"] = ident
    return base.Opportunity(**values)


def _lot_for_external(op: base.Opportunity) -> watcher.Lot:
    identity = op.identity
    sensitive = " ".join(x for x in (identity.attribute, identity.variety) if x).strip()
    clean_title = " ".join(
        x
        for x in (
            identity.name,
            identity.set_name,
            identity.number,
            "Japanese",
            "PSA 10",
            sensitive,
        )
        if x
    )
    return watcher.Lot(
        url=op.url,
        title=clean_title,
        current_price=op.landed_eur,
        source_type="FIXED_PRICE",
        grader="PSA",
        grade="10",
        listing_text=clean_title,
        card_set=identity.set_name,
        card_number=identity.number,
        language="Japanese",
        year=identity.year,
        variant=sensitive,
    )


def _canonical_for_external(op: base.Opportunity) -> multimarket.CanonicalCard:
    identity = op.identity
    local_id = identity.number.split("/", 1)[0]
    return multimarket.CanonicalCard(
        status="EXACT",
        card_id=f"japan-edge:{hashlib.sha256(identity.key.encode()).hexdigest()[:16]}",
        set_id="japan-edge-gcc-exact",
        set_name=identity.set_name,
        local_id=local_id,
        full_number=identity.number,
        name=identity.name,
        language_code="ja",
        reason="JAPAN_EDGE_GCC_EXACT_IDENTITY",
        unique_name_number=False,
    )


def fetch_external_reference(
    op: base.Opportunity,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> ExternalReference:
    lot = _lot_for_external(op)
    canonical = _canonical_for_external(op)
    evidence = multimarket._poketrace_evidence(lot, canonical, budget, now)
    estimate = evidence.estimate
    if (
        evidence.status == watcher.EXTERNAL_MATCHED
        and evidence.strength == watcher.EVIDENCE_STRONG
        and estimate is not None
        and estimate.central > 0
    ):
        return ExternalReference(
            status="EXACT_SOLD_CONFIRMED",
            fair_eur=round(float(estimate.central), 2),
            sold_count=max(0, int(estimate.exact_grade_count or 0)),
            evidence_strength=evidence.strength,
            note=evidence.note,
        )
    return ExternalReference(
        status=evidence.status or "UNAVAILABLE",
        evidence_strength=evidence.strength or "UNAVAILABLE",
        note=evidence.note,
    )


def classify_market(
    op: base.Opportunity,
    external: ExternalReference,
    min_discount: float,
) -> MarketDecision:
    gcc = float(op.fair_eur)
    landed = float(op.landed_eur)
    discount_gcc = (gcc - landed) / gcc * 100 if gcc > 0 else 0.0

    if external.fair_eur is None or external.fair_eur <= 0:
        return MarketDecision(
            status="GCC_ONLY_UNCONFIRMED",
            gcc_fair_eur=round(gcc, 2),
            external_fair_eur=None,
            global_fair_eur=round(gcc, 2),
            discount_vs_gcc_pct=round(discount_gcc, 1),
            discount_vs_external_pct=None,
            discount_vs_global_pct=round(discount_gcc, 1),
            market_ratio=None,
            should_notify=discount_gcc + 1e-9 >= min_discount,
            priority="default",
        )

    ext = float(external.fair_eur)
    discount_ext = (ext - landed) / ext * 100 if ext > 0 else 0.0
    global_fair = float(median([gcc, ext]))
    discount_global = (global_fair - landed) / global_fair * 100 if global_fair > 0 else 0.0
    ratio = max(gcc, ext) / min(gcc, ext) if min(gcc, ext) > 0 else None

    if ratio is not None and ratio > GLOBAL_CONFLICT_RATIO:
        status = "MARKET_CONFLICT_BLOCKED"
        should_notify = False
        priority = "default"
    elif discount_ext + 1e-9 >= min_discount and discount_global + 1e-9 >= min_discount:
        status = "MULTIMARKET_CONFIRMED"
        should_notify = True
        priority = "high"
    else:
        status = "GCC_EDGE_NOT_GLOBAL"
        should_notify = False
        priority = "default"

    return MarketDecision(
        status=status,
        gcc_fair_eur=round(gcc, 2),
        external_fair_eur=round(ext, 2),
        global_fair_eur=round(global_fair, 2),
        discount_vs_gcc_pct=round(discount_gcc, 1),
        discount_vs_external_pct=round(discount_ext, 1),
        discount_vs_global_pct=round(discount_global, 1),
        market_ratio=round(ratio, 3) if ratio is not None else None,
        should_notify=should_notify,
        priority=priority,
    )


def _notification_fingerprint(op: base.Opportunity) -> str:
    return hashlib.sha256(f"v3|{op.provider}|{op.url}|{op.price_jpy}".encode()).hexdigest()


def notify(
    op: base.Opportunity,
    external: ExternalReference,
    decision: MarketDecision,
    server: str,
    topic: str,
    ppt: ppt_context.PptNotificationContext | None = None,
) -> None:
    landed = f"{op.landed_chf:.0f} CHF" if op.landed_chf is not None else f"€{op.landed_eur:.0f}"
    identity = op.identity
    title = (
        "JAPAN EDGE GLOBAL >=30%"
        if decision.status == "MULTIMARKET_CONFIRMED"
        else "JAPAN EDGE GCC >=30% — EXTERNE À CONFIRMER"
    )

    market_lines = [
        f"Prix Japon: ¥{op.price_jpy:,} | rendu estimé {landed}",
        "",
        f"GCC exact JP PSA10: €{decision.gcc_fair_eur:.0f} | {op.gcc_sold_count} SOLD ({op.gcc_recent_90} <90j)",
        f"→ décote vs GCC: -{decision.discount_vs_gcc_pct:.0f}%",
    ]
    ppt_lines = ppt_context.notification_lines(ppt) if ppt is not None else []
    if ppt_lines:
        market_lines.extend(["", *ppt_lines])
    market_lines.append("")

    if external.fair_eur is not None and decision.discount_vs_external_pct is not None:
        market_lines.extend(
            [
                f"Marché externe exact: €{external.fair_eur:.0f} | {external.source} | {external.sold_count} SOLD",
                f"→ décote vs externe: -{decision.discount_vs_external_pct:.0f}%",
                "",
                f"Fair multi-marché: €{decision.global_fair_eur:.0f}",
                f"→ décote globale: -{decision.discount_vs_global_pct:.0f}%",
            ]
        )
    else:
        market_lines.extend(
            [
                f"Marché externe exact: non confirmé ({external.status})",
                "Fair multi-marché: non confirmé — référence GCC seule",
            ]
        )

    body = "\n".join(
        [
            f"{identity.name} {identity.number} | {identity.set_name}",
            "Japanese | PSA 10",
            "",
            *market_lines,
            "",
            f"VERDICT: {decision.status}",
            "PPT = CONTEXTE AFFICHÉ, PAS DÉCIDEUR",
            "ASK, PAS UNE VENTE",
            op.url,
        ]
    )
    requests.post(
        f"{server.rstrip('/')}/{topic}",
        data=body.encode(),
        headers={"Title": title, "Priority": decision.priority},
        timeout=8,
    ).raise_for_status()


def enrich_payload(
    raw_payload: dict,
    state_path: Path,
    output_path: Path,
    *,
    min_discount: float,
    notify_enabled: bool,
    server: str,
    topic: str,
    max_external_candidates: int,
) -> dict:
    now = datetime.now(timezone.utc)
    budget = multimarket.RequestBudget()
    ppt_client = ppt_context.PptNotificationClient.from_env()
    rows = []
    state = base.load_state(state_path)
    cutoff = now - timedelta(days=14)
    notified = {
        key: value
        for key, value in state.get("notified", {}).items()
        if (base.parse_time(value) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    }

    opportunities = [_op_from_dict(item) for item in raw_payload.get("opportunities", [])]
    for index, op in enumerate(opportunities):
        if index < max(0, max_external_candidates):
            try:
                external = fetch_external_reference(op, budget, now)
            except Exception as error:
                external = ExternalReference(status=f"ERROR_{type(error).__name__}", note="external lookup failed closed")
        else:
            external = ExternalReference(status="PENDING_BUDGET", note="global market candidate cap reached")

        decision = classify_market(op, external, min_discount)
        fp = _notification_fingerprint(op)
        is_new_notification = fp not in notified

        if decision.should_notify:
            # In a diagnostic/no-ntfy run, fetch context for the report. In
            # production, avoid spending PPT credits again on an already-deduped
            # notification.
            if not notify_enabled or not topic or is_new_notification:
                ppt_display = ppt_client.fetch(op, now)
            else:
                ppt_display = ppt_context.not_requested("NOT_REQUESTED_ALREADY_NOTIFIED")
        else:
            ppt_display = ppt_context.not_requested("NOT_REQUESTED_DECISION_NOT_NOTIFYING")

        row = asdict(op)
        row["external_reference"] = asdict(external)
        row["market_decision"] = asdict(decision)
        row["ppt_notification_context"] = ppt_context.as_payload(ppt_display)
        rows.append(row)

        if notify_enabled and topic and decision.should_notify and is_new_notification:
            notify(op, external, decision, server, topic, ppt_display)
            notified[fp] = now.isoformat().replace("+00:00", "Z")

    base.save_state(
        state_path,
        {
            "cursor": state.get("cursor", 0),
            "notified": notified,
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        },
    )
    output = dict(raw_payload)
    output["generated_at"] = now.isoformat().replace("+00:00", "Z")
    output["mode"] = "READ_ONLY_PRODUCTION_MULTI_MARKET"
    output["opportunities"] = rows
    output["global_market"] = {
        "policy": "GCC exact Japanese PSA10 SOLD + independent exact Japanese PSA10 PokeTrace/eBay SOLD aggregate",
        "high_priority_rule": "discount >= threshold versus external and provider-level multi-market fair; material market conflict blocks high-priority alert",
        "gcc_only_rule": "if external exact SOLD is unavailable, retain clearly labelled GCC-only unconfirmed alert",
        "conflict_ratio": GLOBAL_CONFLICT_RATIO,
        "max_external_candidates": max_external_candidates,
        "poketrace_requests_used": budget.poketrace_requests,
        "ppt_notification_context": ppt_client.summary(),
        "ppt_policy": "display-only after market decision; SOLD_AGGREGATED; same eBay correlation family; never changes verdict/FV/notification eligibility",
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    return output


def env_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> None:
    v2.install()
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".japan-edge-state/state.json")
    parser.add_argument("--output", default="japan_edge_report.json")
    args = parser.parse_args()
    state_path = Path(args.state)
    output_path = Path(args.output)
    min_discount = max(0.0, env_f("JAPAN_EDGE_MIN_DISCOUNT_PCT", 30))
    notify_enabled = os.getenv("JAPAN_EDGE_NOTIFY_ENABLED", "false").lower() == "true"
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh")
    topic = os.getenv("NTFY_TOPIC", "").strip()

    raw = base.run(
        state_path,
        output_path,
        max(1, env_i("JAPAN_EDGE_GCC_PAGES", 20)),
        max(1, env_i("JAPAN_EDGE_MAX_SEEDS_PER_RUN", 12)),
        max(1, env_i("JAPAN_EDGE_MAX_ITEMS_PER_SEARCH", 25)),
        min_discount,
        max(0, env_i("JAPAN_EDGE_PROXY_FIXED_JPY", 500)),
        max(0.0, env_f("JAPAN_EDGE_LOGISTICS_BUFFER_PCT", 12)),
        False,
        server,
        topic,
    )
    enriched = enrich_payload(
        raw,
        state_path,
        output_path,
        min_discount=min_discount,
        notify_enabled=notify_enabled,
        server=server,
        topic=topic,
        max_external_candidates=max(0, min(20, env_i("JAPAN_EDGE_GLOBAL_MAX_CANDIDATES", 12))),
    )
    summary = {
        "opportunities": len(enriched.get("opportunities", [])),
        "multimarket_confirmed": sum(
            1 for row in enriched.get("opportunities", []) if row["market_decision"]["status"] == "MULTIMARKET_CONFIRMED"
        ),
        "gcc_only_unconfirmed": sum(
            1 for row in enriched.get("opportunities", []) if row["market_decision"]["status"] == "GCC_ONLY_UNCONFIRMED"
        ),
        "market_blocked": sum(
            1 for row in enriched.get("opportunities", []) if row["market_decision"]["status"] in {"MARKET_CONFLICT_BLOCKED", "GCC_EDGE_NOT_GLOBAL"}
        ),
        "ppt_context": enriched.get("global_market", {}).get("ppt_notification_context", {}),
        "diagnostics": enriched.get("diagnostics", {}),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
