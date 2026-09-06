"""V4/Global policy: always consult PriceCharting as a valuation guide.

PriceCharting remains a GUIDE source, never an item-level SOLD source. The policy
accepts the public Grade 9 / Grade 8 guide buckets as PSA 9 / PSA 8-equivalent
valuation guides for an already-proved exact PSA listing. This is a product-level
valuation equivalence, not a claim that PriceCharting proved the grader of any
underlying sale.

Stronger exact/recent SOLD-derived evidence keeps economic priority. A usable
PriceCharting guide can nevertheless stand alone when the SOLD-derived paths are
unavailable. It uses the ordinary V4 discount threshold; there is no special 40%
penalty simply because the source is a guide.
"""
from __future__ import annotations

import os
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_marketplace_economic as global_economic
import v4_pricecharting_valuation as pricecharting


_POLICY_MARKER = "_v4_pricecharting_mandatory_guide_policy_installed"
_GLOBAL_MARKER = "_v4_global_pricecharting_mandatory_guide_policy_installed"
_DEFAULT_MIN_RUN_BUDGET = 50
_CACHE: dict[str, watcher.ExternalMarketEvidence] = {}
_BASE_PRICECHARTING_EVIDENCE = pricecharting.pricecharting_evidence_for_lot
_BASE_POKETRACE_EVIDENCE = multimarket._poketrace_evidence


def _psa_grade(lot: watcher.Lot) -> Optional[float]:
    if str(lot.grader or "").strip().upper() != "PSA":
        return None
    try:
        grade = float(lot.grade) if lot.grade is not None else None
    except (TypeError, ValueError):
        return None
    return grade


def _accepted_guide_label(lot: watcher.Lot) -> str:
    grade = _psa_grade(lot)
    if grade == 10.0:
        return "PSA 10"
    if grade == 9.0:
        return "Grade 9 -> PSA 9"
    if grade == 8.0:
        return "Grade 8 -> PSA 8"
    return ""


def _upgrade_guide_evidence(
    lot: watcher.Lot,
    evidence: watcher.ExternalMarketEvidence,
) -> watcher.ExternalMarketEvidence:
    """Apply the operator-approved PSA 8/9/10 PriceCharting guide policy."""
    label = _accepted_guide_label(lot)
    estimate = evidence.estimate
    if (
        not label
        or evidence.status != watcher.EXTERNAL_MATCHED
        or estimate is None
        or estimate.central <= 0
    ):
        return evidence

    normal_threshold = max(0.0, float(watcher.MIN_DISCOUNT))
    upgraded_estimate = replace(
        estimate,
        confidence="moyenne",
        adaptive_discount_pct=normal_threshold,
        rationale=(
            f"PriceCharting guide {label} accepté comme estimation de prix pour "
            "la carte PSA exacte; guide calculé depuis l'historique de marché, "
            "jamais présenté comme un SOLD item-level"
        ),
        source_counts={"pricecharting_guide": 1},
        exact_grade_count=0,
        same_grader_count=0,
    )
    note = (
        f"{evidence.note}; policy={label}; guide obligatoire de référence; "
        "pas un SOLD item-level"
    ).strip("; ")
    return replace(
        evidence,
        strength=watcher.EVIDENCE_STRONG,
        estimate=upgraded_estimate,
        note=note,
    )


def _cache_key(lot: watcher.Lot) -> str:
    return watcher.external_commercial_identity_key(lot)


def _mandatory_budget_floor() -> int:
    try:
        return max(
            1,
            int(
                os.getenv(
                    "PRICECHARTING_MANDATORY_MAX_CARDS_PER_RUN",
                    str(_DEFAULT_MIN_RUN_BUDGET),
                )
            ),
        )
    except ValueError:
        return _DEFAULT_MIN_RUN_BUDGET


def _ensure_provider_budget() -> None:
    """Keep the guide bounded but large enough to be a systematic reference."""
    current = pricecharting._PROVIDER
    if current is not None:
        if current.config.max_cards_per_run >= _mandatory_budget_floor():
            return
        config = replace(
            current.config,
            max_cards_per_run=_mandatory_budget_floor(),
        )
        pricecharting._PROVIDER = pricecharting.PriceChartingProvider(config=config)
        return

    config = pricecharting.PriceChartingConfig.from_env()
    if config.max_cards_per_run < _mandatory_budget_floor():
        config = replace(
            config,
            max_cards_per_run=_mandatory_budget_floor(),
        )
    pricecharting._PROVIDER = pricecharting.PriceChartingProvider(config=config)


def _mandatory_pricecharting_evidence(
    lot: watcher.Lot,
    *,
    now: Optional[datetime] = None,
    provider: Optional[pricecharting.PriceChartingProvider] = None,
) -> watcher.ExternalMarketEvidence:
    """Fetch once per exact commercial identity and upgrade accepted PSA guides."""
    effective_now = now or datetime.now(timezone.utc)
    if provider is not None:
        return _upgrade_guide_evidence(
            lot,
            _BASE_PRICECHARTING_EVIDENCE(
                lot, now=effective_now, provider=provider
            ),
        )

    key = _cache_key(lot)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    evidence = _upgrade_guide_evidence(
        lot,
        _BASE_PRICECHARTING_EVIDENCE(lot, now=effective_now),
    )
    _CACHE[key] = evidence
    return evidence


def _guide_summary(evidence: watcher.ExternalMarketEvidence) -> str:
    estimate = evidence.estimate
    if (
        evidence.status == watcher.EXTERNAL_MATCHED
        and estimate is not None
        and estimate.central > 0
    ):
        return (
            f"PriceCharting guide={estimate.central:.2f} EUR "
            f"({evidence.strength}; not item-level SOLD)"
        )
    return f"PriceCharting={evidence.status} ({evidence.note or 'no guide'})"


def _poketrace_with_mandatory_pricecharting(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> watcher.ExternalMarketEvidence:
    """Consult the guide even when PokeTrace itself is already strong."""
    poketrace_result = _BASE_POKETRACE_EVIDENCE(lot, canonical, budget, now)
    try:
        guide = pricecharting.pricecharting_evidence_for_lot(lot, now=now)
        summary = _guide_summary(guide)
    except Exception as error:  # provider failure must not erase stronger SOLD evidence
        summary = f"PriceCharting=PROVIDER_ERROR ({type(error).__name__})"
    return replace(
        poketrace_result,
        note=f"{poketrace_result.note}; {summary}".strip("; "),
    )


def install_v4_pricecharting_mandatory_guide_policy() -> None:
    """Install systematic PriceCharting guide use in the canonical V4 lane."""
    current = pricecharting.pricecharting_evidence_for_lot
    if getattr(current, _POLICY_MARKER, False):
        return

    _ensure_provider_budget()
    _CACHE.clear()
    setattr(_mandatory_pricecharting_evidence, _POLICY_MARKER, True)
    pricecharting.pricecharting_evidence_for_lot = _mandatory_pricecharting_evidence
    multimarket._poketrace_evidence = _poketrace_with_mandatory_pricecharting
    watcher.log(
        "PriceCharting policy: mandatory guide reference for exact PSA 8/9/10; "
        "normal V4 discount threshold; SOLD-derived evidence remains primary"
    )


def _observed_at(report: Mapping[str, Any]) -> datetime:
    raw = report.get("observed_at")
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def install_global_pricecharting_mandatory_guide_policy() -> None:
    """Make PriceCharting systematic in Global while preserving SOLD priority."""
    import v4_global_live_confirmed as confirmed
    import v4_global_marketplace_notify as marketplace

    if getattr(marketplace._with_marketplace_evaluator, _GLOBAL_MARKER, False):
        return

    install_v4_pricecharting_mandatory_guide_policy()
    global_economic.PRICECHARTING_MIN_DISCOUNT_PCT = float(
        global_economic.legacy.DEFAULT_MIN_DISCOUNT
    )

    old_formatter = marketplace._format_notification

    def with_mandatory_pricecharting(report: Mapping[str, Any]) -> dict[str, Any]:
        old_eval = confirmed.evaluate_card
        old_payload = confirmed.decision_payload
        observed_at = _observed_at(report)
        pricecharting_by_identity: dict[str, dict[str, Any]] = {}

        def marketplace_eval(
            card: Mapping[str, object],
            *,
            ppt: global_economic.legacy.ExternalAggregate,
            poketrace: global_economic.legacy.ExternalAggregate,
            min_discount: float = global_economic.legacy.DEFAULT_MIN_DISCOUNT,
        ) -> global_economic.MarketplaceDecision:
            # Mandatory reference: always query PriceCharting for a supported
            # exact PSA identity. The economic selector still prefers stronger
            # SOLD-derived evidence when available.
            pc = marketplace._pricecharting_aggregate(card, now=observed_at)
            identity = global_economic.legacy.identity_from_card(card)
            if identity is not None:
                pricecharting_by_identity[identity.strict_key] = asdict(pc)
            return global_economic.evaluate_marketplace_card(
                card,
                ppt=ppt,
                poketrace=poketrace,
                pricecharting=pc,
                min_discount=min_discount,
            )

        confirmed.evaluate_card = marketplace_eval
        confirmed.decision_payload = global_economic.decision_payload
        try:
            enriched = confirmed.enrich_confirmation(report)
        finally:
            confirmed.evaluate_card = old_eval
            confirmed.decision_payload = old_payload

        for raw_card in enriched.get("cards", []):
            if not isinstance(raw_card, dict):
                continue
            identity = global_economic.legacy.identity_from_card(raw_card)
            confirmation = raw_card.get("economic_confirmation")
            if (
                identity is not None
                and isinstance(confirmation, dict)
                and identity.strict_key in pricecharting_by_identity
            ):
                confirmation["pricecharting"] = pricecharting_by_identity[
                    identity.strict_key
                ]

        payloads = list(pricecharting_by_identity.values())
        enriched["mode"] = marketplace.MODE_ACTIVE if marketplace._enabled() else marketplace.MODE_DRY
        enriched["economic_confirmation"]["marketplace_first"] = True
        enriched["economic_confirmation"]["gcc_fair_optional"] = True
        enriched["economic_confirmation"]["gcc_history_economic_authority"] = False
        enriched["economic_confirmation"]["marketplace_sources_are_opportunity_only"] = True
        enriched["economic_confirmation"]["pricecharting_required_reference"] = True
        enriched["economic_confirmation"]["pricecharting_attempted"] = len(payloads)
        enriched["economic_confirmation"]["pricecharting_matched"] = sum(
            payload.get("status") == "MATCHED" for payload in payloads
        )
        enriched["economic_confirmation"]["valuation_source_priority"] = [
            "exact/recent SOLD-derived evidence when available",
            "PriceCharting guide required as systematic reference",
            "PriceCharting guide may stand alone for accepted PSA 8/9/10 buckets",
        ]
        return enriched

    def format_with_pricecharting_reference(card, decision, offer):
        title, body = old_formatter(card, decision, offer)
        identity = card.get("identity") if isinstance(card.get("identity"), Mapping) else {}
        grade = str(identity.get("grade") or "")
        valuation_type = str(decision.get("valuation_evidence_type") or "")
        if valuation_type == "PRICE_GUIDE":
            label = (
                "PSA 10"
                if grade in {"10", "10.0"}
                else f"Grade {grade} -> PSA {grade}"
            )
            body = body.replace(
                "PriceCharting: guide PSA 10 exact (pas un SOLD item-level)",
                f"PriceCharting: guide {label} (pas un SOLD item-level)",
            )
        confirmation = card.get("economic_confirmation")
        pc_payload = (
            confirmation.get("pricecharting")
            if isinstance(confirmation, Mapping)
            else None
        )
        if isinstance(pc_payload, Mapping):
            fair = pc_payload.get("fair_eur")
            status = str(pc_payload.get("status") or "UNAVAILABLE")
            if fair not in {None, ""}:
                try:
                    reference = f"PriceCharting référence: €{float(fair):.2f} ({status}, GUIDE)"
                except (TypeError, ValueError):
                    reference = f"PriceCharting référence: {status}"
            else:
                reference = f"PriceCharting référence: {status}"
            body = body.replace(
                "PAS UNE VENTE. Vérification manuelle uniquement.",
                f"{reference}\nPAS UNE VENTE. Vérification manuelle uniquement.",
            )
        return title, body

    setattr(with_mandatory_pricecharting, _GLOBAL_MARKER, True)
    marketplace._with_marketplace_evaluator = with_mandatory_pricecharting
    marketplace._format_notification = format_with_pricecharting_reference
