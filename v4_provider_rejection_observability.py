from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import watcher
import v4_canonical_multimarket as multimarket


@dataclass(frozen=True)
class PokeTraceProbeContext:
    lot: watcher.Lot
    canonical: multimarket.CanonicalCard


_ACTIVE_POKETRACE_PROBE: ContextVar[Optional[PokeTraceProbeContext]] = ContextVar(
    "v4_poketrace_probe_context", default=None
)
_ORIGINAL_TCGDEX_RESOLVER: Any = None
_ORIGINAL_POKETRACE_EVIDENCE: Any = None
_ORIGINAL_PACED_GET: Any = None
_INSTALLED = False


def _display(value: object, *, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _provider_set(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    payload = candidate.get("set")
    if not isinstance(payload, Mapping):
        return "", "", ""
    return (
        str(payload.get("name") or "").strip(),
        str(payload.get("slug") or "").strip(),
        str(payload.get("id") or "").strip(),
    )


def _candidate_rejection_reason(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    candidate: Mapping[str, Any],
) -> str:
    """Explain the existing final V4 PokeTrace gate without changing it."""

    if str(candidate.get("productType") or "single").strip().casefold() != "single":
        return "PRODUCT_TYPE"
    if multimarket._normalize(candidate.get("name")) != multimarket._normalize(
        canonical.name
    ):
        return "NAME"
    if not multimarket._same_card_number(
        candidate.get("cardNumber"), canonical.full_number
    ):
        return "CARD_NUMBER"

    candidate_left, candidate_den = multimarket._canonical_number_parts(
        candidate.get("cardNumber")
    )
    canonical_left, canonical_den = multimarket._canonical_number_parts(
        canonical.full_number
    )
    if not candidate_left or candidate_left != canonical_left:
        return "CARD_NUMBER_LOCAL"
    if canonical_den and candidate_den and candidate_den != canonical_den:
        return "CARD_NUMBER_DENOMINATOR"

    provider_set_name, _, _ = _provider_set(candidate)
    set_exact = bool(
        provider_set_name
        and multimarket._normalize(provider_set_name)
        == multimarket._normalize(canonical.set_name)
    )
    unique_bridge = bool(
        canonical.unique_name_number
        and canonical_den
        and candidate_den == canonical_den
    )
    if not (set_exact or unique_bridge):
        return "SET"
    if not multimarket._poketrace_language_market_is_exact(lot, candidate):
        return "LANGUAGE_GAME"

    # The function installed at runtime is the hardened production gate. If all
    # macro coordinates above agree but it still rejects, the blocker is one of
    # the existing sensitive-dimension/catalog-applicability safeguards.
    if not multimarket._candidate_exact_for_canonical(lot, canonical, candidate):
        return "SENSITIVE_DIMENSIONS_OR_HARDENING"
    return "MATCH"


def _candidate_example(
    candidate: Mapping[str, Any], reason: str
) -> str:
    set_name, set_slug, set_id = _provider_set(candidate)
    return (
        f"reason={reason} id={_display(candidate.get('id')) or '-'} "
        f"name={_display(candidate.get('name')) or '-'} "
        f"number={_display(candidate.get('cardNumber')) or '-'} "
        f"set={_display(set_name) or '-'} "
        f"set_slug={_display(set_slug) or '-'} "
        f"set_id={_display(set_id) or '-'} "
        f"game={_display(candidate.get('game')) or '-'} "
        f"variant={_display(candidate.get('variant')) or '-'}"
    )


def _diagnostic_paced_get(
    budget: multimarket.RequestBudget,
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
):
    result = _ORIGINAL_PACED_GET(budget, url, params=params)
    context = _ACTIVE_POKETRACE_PROBE.get()
    if context is None or not url.rstrip("/").endswith("/cards"):
        return result

    status, payload, _headers = result
    if status != 200:
        watcher.log(
            "PokeTrace probe: "
            f"{_display(context.canonical.name)} #{_display(context.canonical.full_number)} "
            f"| HTTP {status}"
        )
        return result

    candidates = multimarket._extract_list_payload(payload)
    reasons = [
        _candidate_rejection_reason(context.lot, context.canonical, candidate)
        for candidate in candidates
    ]
    counts = Counter(reasons)
    reason_text = ", ".join(
        f"{reason}={count}" for reason, count in sorted(counts.items())
    ) or "NONE"
    watcher.log(
        "PokeTrace probe: "
        f"{_display(context.canonical.name)} #{_display(context.canonical.full_number)} "
        f"| tcgdex_set={_display(context.canonical.set_id)}/{_display(context.canonical.set_name)} "
        f"| language={_display(context.canonical.language_code)} "
        f"| provider_candidates={len(candidates)} | reasons {reason_text}"
    )
    for candidate, reason in list(zip(candidates, reasons))[:3]:
        watcher.log("PokeTrace probe candidate: " + _candidate_example(candidate, reason))
    return result


def _diagnostic_poketrace_evidence(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
    now,
):
    token = _ACTIVE_POKETRACE_PROBE.set(PokeTraceProbeContext(lot, canonical))
    try:
        evidence = _ORIGINAL_POKETRACE_EVIDENCE(lot, canonical, budget, now)
    finally:
        _ACTIVE_POKETRACE_PROBE.reset(token)

    if canonical.status == "EXACT":
        watcher.log(
            "PokeTrace final: "
            f"{_display(canonical.name)} #{_display(canonical.full_number)} "
            f"| tcgdex_set={_display(canonical.set_id)}/{_display(canonical.set_name)} "
            f"| status={_display(evidence.status)} strength={_display(evidence.strength)} "
            f"| note={_display(evidence.note, limit=160)}"
        )
    return evidence


def _diagnostic_tcgdex_resolver(lot: watcher.Lot) -> multimarket.CanonicalCard:
    result = _ORIGINAL_TCGDEX_RESOLVER(lot)
    if result.status != "EXACT":
        identity = watcher.extract_card_identity(lot)
        watcher.log(
            "TCGdex blocker: "
            f"status={_display(result.status)} "
            f"name={_display(identity.get('core') or lot.title)} "
            f"number={_display(lot.card_number or identity.get('ref')) or '-'} "
            f"listing_set={_display(lot.card_set or identity.get('series')) or '-'} "
            f"language={_display(lot.language or identity.get('language')) or '-'} "
            f"reason={_display(result.reason, limit=180) or '-'}"
        )
    return result


def install_v4_provider_rejection_observability() -> None:
    """Install bounded, identity-only diagnostics around the final V4 gates."""

    global _INSTALLED, _ORIGINAL_TCGDEX_RESOLVER, _ORIGINAL_POKETRACE_EVIDENCE, _ORIGINAL_PACED_GET
    if _INSTALLED:
        return

    _ORIGINAL_TCGDEX_RESOLVER = multimarket.resolve_tcgdex_card
    _ORIGINAL_POKETRACE_EVIDENCE = multimarket._poketrace_evidence
    _ORIGINAL_PACED_GET = multimarket._paced_poketrace_get

    multimarket.resolve_tcgdex_card = _diagnostic_tcgdex_resolver
    multimarket._poketrace_evidence = _diagnostic_poketrace_evidence
    multimarket._paced_poketrace_get = _diagnostic_paced_get
    _INSTALLED = True
