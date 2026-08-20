"""Read-only provider coverage diagnostic for the Global confirmation lane.

This module does not change matching, valuation or notification behavior. It reuses
an already-exact Global/TCGdex identity and records bounded, sanitized provider
candidate metadata so recurring PPT/PokeTrace coverage gaps can be classified
without relaxing identity.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import requests

import v4_canonical_multimarket as multimarket
import v4_global_live_shadow as base
import v4_global_live_shadow_hardened as hardened
import v4_global_ppt_confirmation as ppt
import v4_multimarket_safety as safety
import v4_poketrace_market_retrieval as poketrace_retrieval
from v4_global_economic_confirmation import (
    identity_from_card,
    install_global_external_market_stack,
    resolve_global_canonical,
)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _provider_set(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    value = candidate.get("set")
    return value if isinstance(value, Mapping) else {}


def _poketrace_set_relation(
    canonical: multimarket.CanonicalCard,
    candidate: Mapping[str, Any],
) -> str:
    set_payload = _provider_set(candidate)
    provider_set = str(set_payload.get("name") or "").strip()
    if provider_set and multimarket._normalize(provider_set) == multimarket._normalize(
        canonical.set_name
    ):
        return "EXACT_SET_NAME"
    if safety._provider_set_id_prefix_matches(canonical, provider_set):
        return "EXACT_TCGDEX_SET_ID_PREFIX"
    _, candidate_den = multimarket._canonical_number_parts(candidate.get("cardNumber"))
    _, canonical_den = multimarket._canonical_number_parts(canonical.full_number)
    if canonical.unique_name_number and canonical_den and candidate_den == canonical_den:
        return "UNIQUE_NAME_FULL_NUMBER"
    return "UNPROVEN_SET_NAMESPACE"


def classify_poketrace_candidate(
    lot,
    canonical: multimarket.CanonicalCard,
    candidate: Mapping[str, Any],
) -> str:
    """Return the first deterministic gate that rejects one public candidate."""
    if str(candidate.get("productType") or "single").strip().casefold() != "single":
        return "REJECT_PRODUCT_TYPE"
    if not safety._provider_name_matches(canonical, candidate.get("name")):
        return "REJECT_NAME"
    if not multimarket._same_card_number(candidate.get("cardNumber"), canonical.full_number):
        return "REJECT_NUMBER"
    candidate_left, candidate_den = multimarket._canonical_number_parts(
        candidate.get("cardNumber")
    )
    canonical_left, canonical_den = multimarket._canonical_number_parts(
        canonical.full_number
    )
    if not candidate_left or candidate_left != canonical_left:
        return "REJECT_LOCAL_ID"
    if candidate_den and canonical_den and candidate_den != canonical_den:
        return "REJECT_DENOMINATOR"
    if _poketrace_set_relation(canonical, candidate) == "UNPROVEN_SET_NAMESPACE":
        return "REJECT_SET_NAMESPACE"
    if not multimarket._poketrace_language_market_is_exact(lot, candidate):
        return "REJECT_LANGUAGE"
    if multimarket._candidate_exact_for_canonical(lot, canonical, candidate):
        return "EXACT"
    return "REJECT_SENSITIVE_DIMENSION_OR_VARIANT"


def _grade_tier_summary(candidate: Mapping[str, Any], tier_name: str) -> dict[str, Any]:
    prices = candidate.get("prices")
    ebay = prices.get("ebay") if isinstance(prices, Mapping) else None
    tier = ebay.get(tier_name) if isinstance(ebay, Mapping) else None
    if not isinstance(tier, Mapping) and isinstance(ebay, Mapping):
        target = "".join(ch for ch in tier_name.upper() if ch.isalnum())
        for key, value in ebay.items():
            if not isinstance(value, Mapping):
                continue
            observed = "".join(ch for ch in str(key).upper() if ch.isalnum())
            if observed == target:
                tier = value
                break
    if not isinstance(tier, Mapping):
        return {"present": False}
    try:
        sale_count = max(0, int(tier.get("saleCount") or 0))
    except (TypeError, ValueError):
        sale_count = 0
    return {
        "present": True,
        "sale_count": sale_count,
        "avg_present": tier.get("avg") not in (None, ""),
        "low_present": tier.get("low") not in (None, ""),
        "high_present": tier.get("high") not in (None, ""),
    }


def sanitize_poketrace_candidate(
    lot,
    canonical: multimarket.CanonicalCard,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    set_payload = _provider_set(candidate)
    tier_name = multimarket._poketrace_grade_tier(lot)
    return {
        "id": str(candidate.get("id") or ""),
        "name": str(candidate.get("name") or ""),
        "card_number": str(candidate.get("cardNumber") or ""),
        "game": str(candidate.get("game") or ""),
        "product_type": str(candidate.get("productType") or "single"),
        "set": {
            "id": str(set_payload.get("id") or ""),
            "name": str(set_payload.get("name") or ""),
            "slug": str(set_payload.get("slug") or ""),
        },
        "variant": str(candidate.get("variant") or ""),
        "rarity": str(candidate.get("rarity") or ""),
        "set_relation": _poketrace_set_relation(canonical, candidate),
        "verdict": classify_poketrace_candidate(lot, canonical, candidate),
        "target_tier": tier_name,
        "target_tier_summary": _grade_tier_summary(candidate, tier_name),
    }


def _ppt_candidate_verdict(identity, canonical, row: Mapping[str, Any]) -> str:
    reviewed = ppt.reviewed_set_id(identity)
    if reviewed:
        status, _ = ppt._match(identity, [row], reviewed)
        return status
    status, _, proof = ppt._match_canonical(identity, canonical, [row])
    return f"{status}:{proof}" if proof else status


def sanitize_ppt_candidate(identity, canonical, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "external_catalog_id": str(row.get("externalCatalogId") or ""),
        "tcgplayer_id": str(row.get("tcgPlayerId") or row.get("tcgplayerId") or ""),
        "name": str(row.get("name") or ""),
        "card_number": str(row.get("cardNumber") or row.get("number") or ""),
        "language": str(row.get("language") or ""),
        "set_id": str(row.get("setId") or row.get("set_id") or ""),
        "set_name": str(row.get("setName") or row.get("set_name") or ""),
        "printing": str(row.get("printing") or ""),
        "variant": str(row.get("variant") or ""),
        "verdict": _ppt_candidate_verdict(identity, canonical, row),
    }


def _poketrace_probe(
    lot,
    canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
) -> dict[str, Any]:
    context = poketrace_retrieval._provider_retrieval_context(lot, canonical)
    if context is None:
        return {"status": "NOT_APPLICABLE", "candidates": []}
    auth_ok, auth_note = multimarket._ensure_poketrace_auth(budget)
    if not auth_ok:
        return {"status": "AUTH_UNAVAILABLE", "note": auth_note, "candidates": []}
    try:
        status, payload, headers = multimarket._paced_poketrace_get(
            budget,
            f"{multimarket.POKETRACE_BASE_URL}/cards",
            params={
                "search": context.search_name,
                "card_number": context.card_number,
                "game": context.game,
                "market": "US",
                "limit": 20,
                "product_type": "single",
            },
        )
    except Exception as error:
        return {
            "status": "PROVIDER_ERROR",
            "note": type(error).__name__,
            "query": {
                "search": context.search_name,
                "card_number": context.card_number,
                "game": context.game,
            },
            "candidates": [],
        }
    rows = multimarket._extract_list_payload(payload) if status == 200 else []
    sanitized = [sanitize_poketrace_candidate(lot, canonical, row) for row in rows]
    return {
        "status": "OK" if status == 200 else f"HTTP_{status}",
        "query": {
            "search": context.search_name,
            "card_number": context.card_number,
            "game": context.game,
            "market": "US",
            "limit": 20,
        },
        "retry_after": str(headers.get("Retry-After") or "") if isinstance(headers, Mapping) else "",
        "candidate_count": len(sanitized),
        "verdict_counts": dict(Counter(row["verdict"] for row in sanitized)),
        "candidates": sanitized,
    }


def _ppt_probe(
    identity,
    canonical: multimarket.CanonicalCard,
    *,
    api_key: str,
    budget: ppt.PptBudget,
    session: requests.Session,
    timeout: float,
) -> dict[str, Any]:
    if not api_key:
        return {"status": "PROVIDER_DISABLED", "candidates": []}
    reviewed = ppt.reviewed_set_id(identity)
    if reviewed:
        params = {
            "language": "japanese",
            "setId": reviewed,
            "search": ppt._collector(identity.number),
            "limit": 5,
        }
        query_mode = "REVIEWED_SET_ID"
    else:
        params = {"language": "japanese", "search": identity.name, "limit": 5}
        query_mode = "GENERIC_EXACT_COORDINATE_DIAGNOSTIC"
    status, payload = ppt._request(session, api_key, budget, params, timeout)
    if status is None:
        return {
            "status": "PENDING_BUDGET",
            "note": budget.blocked_reason,
            "query_mode": query_mode,
            "candidates": [],
        }
    rows = ppt._rows(payload) if status == 200 else []
    sanitized = [sanitize_ppt_candidate(identity, canonical, row) for row in rows]
    return {
        "status": "OK" if status == 200 else f"HTTP_{status}",
        "query_mode": query_mode,
        "query": {key: value for key, value in params.items() if key != "language"} | {"language": "japanese"},
        "candidate_count": len(sanitized),
        "verdict_counts": dict(Counter(row["verdict"] for row in sanitized)),
        "candidates": sanitized,
    }


def enrich_provider_coverage(report: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(report)
    install_global_external_market_stack()
    multimarket.clear_tcgdex_cache()

    ppt_key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    ppt_budget = ppt.PptBudget(
        max_http_calls=6,
        max_credits=35,
        daily_remaining_floor=15_000,
        interval_seconds=_env_float("GLOBAL_PROVIDER_DIAG_PPT_INTERVAL_SECONDS", 1.10),
    )
    ppt_session = requests.Session()
    poketrace_budget = multimarket.RequestBudget()
    timeout = _env_float("GLOBAL_PROVIDER_DIAG_PPT_TIMEOUT_SECONDS", 15.0, 1.0)

    cards = []
    rejection_totals: Counter[str] = Counter()
    ppt_verdict_totals: Counter[str] = Counter()
    tcgdex_exact = 0
    pt_candidates = 0
    ppt_candidates = 0

    for raw_card in output.get("cards", []):
        card = dict(raw_card) if isinstance(raw_card, Mapping) else {}
        identity = identity_from_card(card)
        if identity is None:
            card["provider_coverage"] = {"status": "BLOCKED_IDENTITY"}
            cards.append(card)
            continue
        lot, canonical = resolve_global_canonical(identity)
        if canonical.status != "EXACT":
            card["provider_coverage"] = {
                "status": f"TCGDEX_{canonical.status}",
                "canonical_reason": canonical.reason,
            }
            cards.append(card)
            continue
        tcgdex_exact += 1
        pt = _poketrace_probe(lot, canonical, poketrace_budget)
        pp = _ppt_probe(
            identity,
            canonical,
            api_key=ppt_key,
            budget=ppt_budget,
            session=ppt_session,
            timeout=timeout,
        )
        pt_candidates += int(pt.get("candidate_count") or 0)
        ppt_candidates += int(pp.get("candidate_count") or 0)
        rejection_totals.update(pt.get("verdict_counts") or {})
        ppt_verdict_totals.update(pp.get("verdict_counts") or {})
        card["provider_coverage"] = {
            "status": "READ_ONLY_DIAGNOSTIC",
            "canonical": {
                "card_id": canonical.card_id,
                "set_id": canonical.set_id,
                "set_name": canonical.set_name,
                "full_number": canonical.full_number,
                "name": canonical.name,
                "language_code": canonical.language_code,
                "reason": canonical.reason,
            },
            "poketrace": pt,
            "ppt": pp,
        }
        cards.append(card)

    output["cards"] = cards
    output["provider_coverage_diagnostic"] = {
        "mode": "READ_ONLY_PROVIDER_COVERAGE",
        "tcgdex_exact": tcgdex_exact,
        "poketrace_candidate_count": pt_candidates,
        "poketrace_verdict_counts": dict(rejection_totals),
        "poketrace_requests": poketrace_budget.poketrace_requests,
        "ppt_candidate_count": ppt_candidates,
        "ppt_verdict_counts": dict(ppt_verdict_totals),
        "ppt_http_calls": ppt_budget.http_calls,
        "ppt_credits": ppt_budget.credits,
        "ppt_daily_remaining": ppt_budget.daily_remaining,
        "ppt_blocked_reason": ppt_budget.blocked_reason,
        "identity_relaxed": False,
        "notifications": False,
        "transactions": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
    }
    output["mode"] = "READ_ONLY_PROVIDER_COVERAGE"
    output["notifications"] = False
    output["transactions"] = False
    return output


def run(args) -> dict[str, Any]:
    shadow = hardened.run(args)
    report = enrich_provider_coverage(shadow)
    output_dir = Path(args.output_dir)
    base.write_report(report, output_dir)
    (output_dir / "global_provider_coverage.json").write_text(
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
                "provider_coverage_diagnostic": report.get(
                    "provider_coverage_diagnostic", {}
                ),
                "output": str(Path(args.output_dir).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
