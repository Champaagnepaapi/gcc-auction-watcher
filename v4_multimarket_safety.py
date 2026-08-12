from __future__ import annotations

from email.header import Header
from typing import Any, Mapping

import requests

import watcher
import v4_canonical_multimarket as mm


_ORIGINAL_PROVIDER_EXACT = mm._candidate_exact_for_canonical


def _canonical_number_parts(value: object) -> tuple[str, str]:
    left, right = mm._number_parts(value)

    def normalize_part(part: str) -> str:
        if part.isdigit():
            return str(int(part))
        return part

    return normalize_part(left), normalize_part(right)


def _same_card_number(first: object, second: object) -> bool:
    first_left, first_right = _canonical_number_parts(first)
    second_left, second_right = _canonical_number_parts(second)
    if not first_left or not second_left or first_left != second_left:
        return False
    if first_right and second_right:
        return first_right == second_right
    return True


def _candidate_sensitive_dimensions(candidate: Mapping[str, Any]) -> dict[str, set[str]]:
    raw_variant = str(candidate.get("variant") or "").replace("_", " ")
    normalized_variant = (
        raw_variant
        .replace("Holofoil", "Holo")
        .replace("holofoil", "holo")
    )
    if mm._normalize(raw_variant) == "normal":
        normalized_variant += " non holo"
    text = " ".join(
        (
            normalized_variant,
            str(candidate.get("rarity") or ""),
            str(candidate.get("name") or ""),
        )
    )
    return watcher._commercial_dimension_candidates(text)


def _catalog_only_finish(canonical: mm.CanonicalCard) -> str:
    variants = canonical.variants if isinstance(canonical.variants, Mapping) else {}
    observed = [
        finish
        for finish, key in (
            ("non_holo", "normal"),
            ("holo", "holo"),
            ("reverse", "reverse"),
        )
        if variants.get(key) is True
    ]
    return observed[0] if len(observed) == 1 else ""


def hardened_candidate_exact_for_canonical(
    lot: watcher.Lot,
    canonical: mm.CanonicalCard,
    candidate: Mapping[str, Any],
) -> bool:
    """Exact macro identity plus fail-closed material-variant compatibility.

    Provider metadata can narrow a hypothesis, never manufacture a premium
    microvariant that the GCC listing/catalog did not deterministically prove.
    """
    if str(candidate.get("productType") or "single").strip().casefold() != "single":
        return False
    if mm._normalize(candidate.get("name")) != mm._normalize(canonical.name):
        return False
    if not _same_card_number(candidate.get("cardNumber"), canonical.full_number):
        return False

    candidate_left, candidate_den = _canonical_number_parts(candidate.get("cardNumber"))
    canonical_left, canonical_den = _canonical_number_parts(canonical.full_number)
    if not candidate_left or candidate_left != canonical_left:
        return False
    if candidate_den and canonical_den and candidate_den != canonical_den:
        return False

    set_payload = candidate.get("set")
    provider_set = (
        str(set_payload.get("name") or "").strip()
        if isinstance(set_payload, Mapping)
        else ""
    )
    set_exact = bool(
        provider_set and mm._normalize(provider_set) == mm._normalize(canonical.set_name)
    )
    # If provider omitted the denominator, do not let catalog uniqueness bridge
    # a mismatching set. Exact set + exact localId is still deterministic.
    unique_bridge = bool(
        canonical.unique_name_number
        and canonical_den
        and candidate_den == canonical_den
    )
    if not (set_exact or unique_bridge):
        return False
    if not mm._poketrace_language_market_is_exact(lot, candidate):
        return False

    expected = watcher.expected_commercial_dimensions(lot)
    if any(value == "__conflict__" for value in expected.values()):
        return False
    observed = _candidate_sensitive_dimensions(candidate)

    # Listing-proven sensitive dimensions must be present and equal provider-side.
    for dimension in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS:
        expected_value = expected.get(dimension)
        if not expected_value:
            continue
        if expected_value not in observed.get(dimension, set()):
            return False

    # Conversely, provider-only premium metadata cannot become listing evidence.
    # Finish is the sole exception when the exact TCGdex card has only one
    # possible normal/holo/reverse printing.
    catalog_finish = _catalog_only_finish(canonical)
    for dimension in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS:
        values = observed.get(dimension, set())
        if not values or expected.get(dimension):
            continue
        if dimension == "finish" and len(values) == 1:
            if catalog_finish and next(iter(values)) == catalog_finish:
                continue
        return False

    variants = canonical.variants if isinstance(canonical.variants, Mapping) else {}
    # `firstEdition: true` means that material edition differentiation is
    # applicable, not that this particular listing is First Edition. Without a
    # listing edition signal, automatic graded economics must stop here.
    if variants.get("firstEdition") is True and not expected.get("edition"):
        return False

    # Multiple possible exact-card finishes require a listing-level finish.
    possible_finishes = sum(
        variants.get(key) is True for key in ("normal", "holo", "reverse")
    )
    if possible_finishes > 1 and not expected.get("finish"):
        return False
    return True


def safe_notify_manual_review(lead: mm.ManualReviewLead) -> None:
    title = "GCC MANUAL REVIEW — GRADED MARKET PENDING"
    grade = watcher.format_grade_label(lead.lot.grader, lead.lot.grade)
    message = (
        f"{title}\n\n"
        f"{lead.canonical.name} #{lead.canonical.full_number}\n"
        f"{lead.canonical.set_name} · TCGdex {lead.canonical.card_id}\n"
        f"{grade}\n\n"
        f"Prix GCC : {lead.lot.current_price:.2f} €\n"
        f"Marché RAW externe : {lead.raw.low:.2f}–{lead.raw.high:.2f} €\n"
        f"RAW central : {lead.raw.central:.2f} €\n"
        f"Sources RAW : {', '.join(lead.raw.sources)}\n"
        f"Écart prudent vs RAW : {lead.gap_pct:.1f}%\n"
        f"Marché gradé : {lead.graded_note or 'non confirmé'}\n\n"
        "RAW ≠ valeur du slab gradé. Aucun prix max conseillé n'est "
        "calculé depuis le RAW; revue manuelle uniquement.\n"
        f"{lead.lot.url}"
    )
    watcher.log("*** MANUAL REVIEW: graded market pending ***")
    print(message, flush=True)
    if watcher.NTFY_TOPIC:
        try:
            requests.post(
                f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers={
                    "Title": Header(title, "utf-8").encode(),
                    "Priority": "3",
                    "Tags": "mag,card_index",
                },
                timeout=10,
            ).raise_for_status()
        except Exception as error:
            watcher.log(
                f"Notification manual review échouée: {type(error).__name__}"
            )


def _combine_retry_with_fallback(
    primary: watcher.ExternalMarketEvidence,
    fallback: watcher.ExternalMarketEvidence,
) -> watcher.ExternalMarketEvidence:
    if (
        fallback.status == watcher.EXTERNAL_MATCHED
        and fallback.strength == watcher.EVIDENCE_STRONG
        and fallback.estimate is not None
    ):
        return fallback
    if fallback.status in watcher.EXTERNAL_RETRY_STATUSES:
        return fallback
    if fallback.status == watcher.EXTERNAL_PENDING:
        return fallback
    if primary.status in watcher.EXTERNAL_RETRY_STATUSES:
        return watcher.replace(
            primary,
            note=(
                f"{primary.note}; fallback {fallback.source or 'external'} "
                f"{fallback.status}: {fallback.note}"
            ).strip("; "),
        )
    if primary.status == watcher.EXTERNAL_PENDING:
        return watcher.replace(
            primary,
            note=(
                f"{primary.note}; fallback {fallback.source or 'external'} "
                f"{fallback.status}: {fallback.note}"
            ).strip("; "),
        )
    return fallback


def hardened_multimarket_process_external_market_candidates(
    page,
    candidates: list[watcher.ValuationCandidate],
    state: dict,
    budgets: watcher.ValidationBudgets,
    run_diagnostics: watcher.RunDiagnostics,
    now,
    *,
    provider=None,
    ttl_hours: int = watcher.EXTERNAL_EVIDENCE_TTL_HOURS,
) -> list[watcher.Opportunity]:
    """All candidates get external evidence; provider outages remain retryable."""
    mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
    watcher.EXTERNAL_CACHE_SCHEMA_VERSION = mm.MULTIMARKET_EXTERNAL_CACHE_SCHEMA_VERSION
    request_budget = mm.RequestBudget()
    leads: dict[str, mm.ManualReviewLead] = {}

    def maybe_record_lead(
        candidate: watcher.ValuationCandidate,
        canonical: mm.CanonicalCard,
        raw: mm.RawMarketSignal | None,
        graded_note: str,
    ) -> None:
        should_review, gap = mm._should_manual_review(candidate.lot, raw)
        if should_review and raw is not None:
            key = mm._manual_review_key(candidate.lot)
            leads[key] = mm.ManualReviewLead(
                key,
                candidate.lot,
                canonical,
                raw,
                gap,
                graded_note,
            )

    def fetch(candidate, validation_budgets, fetch_now):
        if provider is not None:
            return provider(candidate, validation_budgets, fetch_now)

        canonical = mm._canonical_from_lot(candidate.lot)
        raw = mm.raw_market_signal(candidate.lot, canonical)
        poketrace = mm._poketrace_evidence(
            candidate.lot, canonical, request_budget, fetch_now
        )
        if (
            poketrace.status == watcher.EXTERNAL_MATCHED
            and poketrace.strength == watcher.EVIDENCE_STRONG
            and poketrace.estimate is not None
        ):
            return poketrace

        # APR/eBay remain independent fallbacks even when PokeTrace is pending
        # or transient. A strong fallback can complete valuation immediately.
        fallback = mm._fallback_external(
            page,
            candidate,
            validation_budgets,
            run_diagnostics.external_market,
            fetch_now,
        )
        combined = _combine_retry_with_fallback(poketrace, fallback)
        if not (
            combined.status == watcher.EXTERNAL_MATCHED
            and combined.strength == watcher.EVIDENCE_STRONG
            and combined.estimate is not None
        ):
            maybe_record_lead(
                candidate,
                canonical,
                raw,
                "; ".join(
                    value for value in (poketrace.note, fallback.note) if value
                ),
            )
        return combined

    opportunities = mm._ORIGINAL_PROCESS_EXTERNAL(
        page,
        candidates,
        state,
        budgets,
        run_diagnostics,
        now,
        provider=fetch,
        ttl_hours=ttl_hours,
    )
    opportunity_keys = {
        watcher.external_commercial_identity_key(op.lot) for op in opportunities
    }
    for key, lead in leads.items():
        if key in opportunity_keys:
            continue
        mm._DIAGNOSTICS.manual_raw_leads += 1
        if mm._manual_review_should_notify(state, lead, now):
            mm._notify_manual_review(lead)
            mm._DIAGNOSTICS.manual_raw_notified += 1
        else:
            mm._DIAGNOSTICS.manual_raw_deduped += 1

    diagnostics = mm._DIAGNOSTICS
    watcher.log("=== CANONICAL MULTI-MARKET ===")
    watcher.log(
        "TCGdex: "
        f"attempted {diagnostics.tcgdex_attempted} | exact {diagnostics.tcgdex_exact} | "
        f"no-match {diagnostics.tcgdex_no_match} | ambiguous {diagnostics.tcgdex_ambiguous} | "
        f"errors {diagnostics.tcgdex_error}"
    )
    watcher.log(
        "RAW external: "
        f"signals {diagnostics.raw_signal_found} | "
        f"variant-ambiguous {diagnostics.raw_signal_variant_ambiguous}"
    )
    watcher.log(
        "PokeTrace: "
        f"attempted {diagnostics.poketrace_attempted} | exact {diagnostics.poketrace_exact} | "
        f"strong {diagnostics.poketrace_strong} | weak {diagnostics.poketrace_weak} | "
        f"no-match {diagnostics.poketrace_no_match} | ambiguous {diagnostics.poketrace_ambiguous} | "
        f"errors {diagnostics.poketrace_error} | 429 {diagnostics.poketrace_rate_limited} | "
        f"budget-pending {diagnostics.poketrace_budget_pending}"
    )
    watcher.log(
        "Manual graded-market pending: "
        f"leads {diagnostics.manual_raw_leads} | notified {diagnostics.manual_raw_notified} | "
        f"deduped {diagnostics.manual_raw_deduped}"
    )
    watcher.log(
        "PSA scope: "
        f"below-8 excluded {diagnostics.psa_below_8_excluded} | "
        f"unsupported excluded {diagnostics.psa_unsupported_grade_excluded}"
    )
    return opportunities


def install_multimarket_safety_hardening() -> None:
    mm._candidate_exact_for_canonical = hardened_candidate_exact_for_canonical
    mm._notify_manual_review = safe_notify_manual_review
    watcher.process_external_market_candidates = (
        hardened_multimarket_process_external_market_candidates
    )
