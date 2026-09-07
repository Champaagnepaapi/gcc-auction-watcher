from __future__ import annotations

"""Bounded cross-grader/cross-language recall lane for manual review only.

The lane exists to avoid silently losing cards whose exact target grader or
language has sparse market data. It never calls a proxy grader/language an exact
target-market fair value. TCGdex must first prove the exact macro card, any
language bridge must resolve the same TCGdex card id/set/localId, and every
cross-grader reference is conservatively haircut before a clearly-labelled
manual-review alert can be emitted.

Proxy policy:
- non-PSA half grades require a same-numeric-grade CGC/BGS proxy; they never fall
  back to a lower whole PSA grade;
- non-PSA whole grades prefer same-grade CGC, then may use PSA same-grade as a
  conservative fallback;
- PriceCharting is an optional sanity cap on a compatible PSA guide, never SOLD.
"""

import math
import os
from dataclasses import dataclass, replace
from datetime import datetime
from email.header import Header
from typing import Mapping, Optional

import watcher
import v4_canonical_multimarket as multimarket
import v4_pricecharting_valuation as pricecharting


_STATE_KEY = "v4_crossmarket_recall_review"
_SCHEMA_VERSION = 2
_ORIGINAL_PROCESS = None
_ORIGINAL_POKETRACE = None
_INSTALLED = False

_CROSS_GRADER_REVIEW_FLOOR_PCT = 30.0
_CROSS_LANGUAGE_HAIRCUT_PCT = 20.0

# Conservative uncertainty haircuts, not empirical conversion ratios.
_SECONDARY_PROXY_HAIRCUT_PCT = {
    "PCA": 10.0,
    "CCC": 15.0,
    "CA": 20.0,
}
_PSA_FALLBACK_HAIRCUT_PCT = {
    "PCA": 30.0,
    "CCC": 35.0,
    "CA": 45.0,
}


@dataclass(frozen=True)
class ReferenceResult:
    evidence: watcher.ExternalMarketEvidence
    reference_grader: str
    reference_grade: float
    cross_grader: bool
    cross_language: bool
    basis: str
    raw_reference_eur: float
    pricecharting_guide_eur: Optional[float] = None


def _max_cards() -> int:
    try:
        value = int(os.getenv("V4_CROSSMARKET_REVIEW_MAX_CARDS_PER_RUN", "3"))
    except ValueError:
        value = 3
    return max(0, min(5, value))


def _min_discount() -> float:
    try:
        value = float(os.getenv("V4_CROSSMARKET_REVIEW_MIN_DISCOUNT_PCT", "20"))
    except ValueError:
        value = 20.0
    return max(15.0, min(45.0, value))


def _required_review_discount(*, cross_grader: bool) -> float:
    base = _min_discount()
    return max(base, _CROSS_GRADER_REVIEW_FLOOR_PCT) if cross_grader else base


def _state_key(lot: watcher.Lot) -> str:
    url = str(lot.url or "").strip().rstrip("/")
    return url or watcher.external_commercial_identity_key(lot)


def _already_sent(state: dict, lot: watcher.Lot) -> bool:
    root = state.get(_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != _SCHEMA_VERSION:
        return False
    entries = root.get("entries")
    return isinstance(entries, dict) and bool(entries.get(_state_key(lot)))


def _mark_sent(
    state: dict,
    lot: watcher.Lot,
    now: datetime,
    reference: float,
    *,
    basis: str,
) -> None:
    root = state.get(_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != _SCHEMA_VERSION:
        root = {"schema_version": _SCHEMA_VERSION, "entries": {}}
        state[_STATE_KEY] = root
    root.setdefault("entries", {})[_state_key(lot)] = {
        "notified_at": now.isoformat(),
        "reference_eur": round(reference, 2),
        "gcc_price": round(float(lot.current_price or 0.0), 2),
        "basis": basis,
    }


def _priority(candidate: watcher.ValuationCandidate) -> tuple[int, float, float]:
    lot = candidate.lot
    if lot.source_type == "auction":
        minutes = float(
            lot.minutes_to_end if lot.minutes_to_end is not None else 9999
        )
        return (
            0 if minutes <= 12 else 1,
            minutes,
            float(lot.current_price or 0.0),
        )
    return (2, float(lot.current_price or 0.0), 0.0)


def _numeric_grade(lot: watcher.Lot) -> Optional[float]:
    value = watcher._target_grade(lot)
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if number is None or not math.isfinite(number) or number <= 0 or number > 10:
        return None
    return number


def _reference_psa_grade(target: float) -> float:
    """Legacy helper retained for diagnostics/tests; never creates PSA 9.5."""
    if target >= 10:
        return 10.0
    if float(target).is_integer():
        return target
    return max(1.0, float(math.floor(target)))


def _same_grade_proxy_graders(target_grade: float) -> tuple[str, ...]:
    if not float(target_grade).is_integer():
        return ("CGC", "BGS")
    return ("CGC",)


def _english_bridge(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
) -> tuple[watcher.Lot, multimarket.CanonicalCard, bool] | None:
    """Return same-card English identity only when TCGdex proves it directly."""
    if canonical.language_code in {"en", "ja"}:
        return lot, canonical, False
    if not canonical.card_id or not canonical.set_id or not canonical.local_id:
        return None
    try:
        status, detail = multimarket._fetch_tcgdex_card_detail(
            "en", canonical.card_id
        )
    except Exception:
        return None
    if status != 200 or not isinstance(detail, Mapping):
        return None
    if str(detail.get("id") or canonical.card_id).strip() != canonical.card_id:
        return None
    if not multimarket._same_card_number(detail.get("localId"), canonical.local_id):
        return None
    set_payload = detail.get("set")
    if not isinstance(set_payload, Mapping):
        return None
    if str(set_payload.get("id") or "").strip() != canonical.set_id:
        return None
    name = str(detail.get("name") or "").strip()
    set_name = str(set_payload.get("name") or "").strip()
    if not name or not set_name:
        return None

    proxy_canonical = multimarket.CanonicalCard(
        status="EXACT",
        card_id=canonical.card_id,
        set_id=canonical.set_id,
        set_name=set_name,
        local_id=str(detail.get("localId") or canonical.local_id),
        full_number=canonical.full_number,
        name=name,
        language_code="en",
        pricing=(
            detail.get("pricing")
            if isinstance(detail.get("pricing"), Mapping)
            else {}
        ),
        variants=(
            detail.get("variants")
            if isinstance(detail.get("variants"), Mapping)
            else canonical.variants
        ),
        reason=canonical.reason,
        unique_name_number=canonical.unique_name_number,
    )
    proxy_lot = replace(
        lot,
        title=name,
        card_set=set_name,
        language="English",
    )
    return proxy_lot, proxy_canonical, True


def _strong_proxy_evidence(
    proxy_lot: watcher.Lot,
    proxy_canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> Optional[watcher.ExternalMarketEvidence]:
    evidence = _ORIGINAL_POKETRACE(proxy_lot, proxy_canonical, budget, now)
    if (
        evidence.status != watcher.EXTERNAL_MATCHED
        or evidence.strength != watcher.EVIDENCE_STRONG
        or evidence.estimate is None
        or evidence.estimate.central <= 0
    ):
        return None
    return evidence


def _pricecharting_cap(
    proxy_lot: watcher.Lot,
    *,
    now: datetime,
) -> Optional[float]:
    """Return a compatible PSA PriceCharting guide only as a conservative cap."""
    grade = _numeric_grade(proxy_lot)
    if grade not in {8.0, 8.5, 9.0, 10.0}:
        return None
    try:
        evidence = pricecharting.pricecharting_evidence_for_lot(proxy_lot, now=now)
    except Exception:
        return None
    if (
        evidence.status != watcher.EXTERNAL_MATCHED
        or evidence.estimate is None
        or evidence.estimate.central <= 0
    ):
        return None
    return float(evidence.estimate.central)


def _with_pricecharting_cap(
    raw_reference_eur: float,
    proxy_lot: watcher.Lot,
    *,
    now: datetime,
) -> tuple[float, Optional[float]]:
    guide = _pricecharting_cap(proxy_lot, now=now)
    if guide is None:
        return raw_reference_eur, None
    return min(raw_reference_eur, guide), guide


def _reference_evidence(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> Optional[ReferenceResult]:
    target_grade = _numeric_grade(lot)
    if target_grade is None:
        return None
    bridged = _english_bridge(lot, canonical)
    if bridged is None:
        return None
    proxy_lot, proxy_canonical, cross_language = bridged

    target_grader = str(lot.grader or "").strip().upper()
    if not target_grader:
        return None

    # Same-grader PSA cross-language review remains possible at the exact grade.
    if target_grader == "PSA":
        grade_text = (
            str(int(target_grade))
            if float(target_grade).is_integer()
            else str(target_grade)
        )
        psa_lot = replace(proxy_lot, grader="PSA", grade=grade_text)
        evidence = _strong_proxy_evidence(psa_lot, proxy_canonical, budget, now)
        if evidence is None or evidence.estimate is None:
            return None
        raw, guide = _with_pricecharting_cap(
            float(evidence.estimate.central), psa_lot, now=now
        )
        if not cross_language:
            return None
        return ReferenceResult(
            evidence=evidence,
            reference_grader="PSA",
            reference_grade=target_grade,
            cross_grader=False,
            cross_language=True,
            basis="SAME_GRADER_CROSS_LANGUAGE",
            raw_reference_eur=raw,
            pricecharting_guide_eur=guide,
        )

    # For non-PSA slabs, prefer a same-numeric-grade secondary-grader market.
    same_grade_matches: list[
        tuple[float, str, watcher.ExternalMarketEvidence, watcher.Lot]
    ] = []
    grade_text = (
        str(int(target_grade))
        if float(target_grade).is_integer()
        else str(target_grade)
    )
    for grader in _same_grade_proxy_graders(target_grade):
        candidate_lot = replace(proxy_lot, grader=grader, grade=grade_text)
        evidence = _strong_proxy_evidence(
            candidate_lot, proxy_canonical, budget, now
        )
        if evidence is None or evidence.estimate is None:
            continue
        same_grade_matches.append(
            (
                float(evidence.estimate.central),
                grader,
                evidence,
                candidate_lot,
            )
        )

    if same_grade_matches:
        _, grader, evidence, chosen_lot = min(
            same_grade_matches, key=lambda item: item[0]
        )
        raw = float(evidence.estimate.central)
        # PriceCharting is a PSA-oriented guide. Use an exact-grade PSA proxy only
        # as a ceiling on a secondary-grader aggregate, never as a SOLD row.
        psa_cap_lot = replace(proxy_lot, grader="PSA", grade=grade_text)
        raw, guide = _with_pricecharting_cap(raw, psa_cap_lot, now=now)
        return ReferenceResult(
            evidence=evidence,
            reference_grader=grader,
            reference_grade=target_grade,
            cross_grader=True,
            cross_language=cross_language,
            basis="SAME_GRADE_SECONDARY_PROXY",
            raw_reference_eur=raw,
            pricecharting_guide_eur=guide,
        )

    # Critical safety rule: PCA/CA/CCC/BGS/CGC half grades do not collapse to
    # a lower whole PSA grade. No same-grade proxy => no cross-grader alert.
    if not float(target_grade).is_integer():
        return None

    # Whole grades may use PSA same-grade as a conservative last resort.
    psa_lot = replace(proxy_lot, grader="PSA", grade=grade_text)
    evidence = _strong_proxy_evidence(psa_lot, proxy_canonical, budget, now)
    if evidence is None or evidence.estimate is None:
        return None
    raw, guide = _with_pricecharting_cap(
        float(evidence.estimate.central), psa_lot, now=now
    )
    return ReferenceResult(
        evidence=evidence,
        reference_grader="PSA",
        reference_grade=target_grade,
        cross_grader=True,
        cross_language=cross_language,
        basis="PSA_FALLBACK_CONSERVATIVE",
        raw_reference_eur=raw,
        pricecharting_guide_eur=guide,
    )


def _cross_grader_haircut(target_grader: str, basis: str) -> float:
    target = str(target_grader or "").strip().upper()
    if basis == "PSA_FALLBACK_CONSERVATIVE":
        return _PSA_FALLBACK_HAIRCUT_PCT.get(target, 40.0)
    if basis == "SAME_GRADE_SECONDARY_PROXY":
        return _SECONDARY_PROXY_HAIRCUT_PCT.get(target, 20.0)
    return 0.0


def _notify(
    lot: watcher.Lot,
    result: ReferenceResult,
    *,
    haircut_pct: float,
    reference_eur: float,
    discount_pct: float,
    required_discount_pct: float,
) -> None:
    flags = []
    if result.cross_grader:
        flags.append("CROSS-GRADER")
    if result.cross_language:
        flags.append("CROSS-LANGUAGE")
    flags_text = " + ".join(flags)
    target_grade = (
        watcher.format_grade_label(lot.grader, lot.grade) or "grade inconnu"
    )
    ref_grade = f"{result.reference_grader} {result.reference_grade:g}"
    timing = ""
    if lot.source_type == "auction" and lot.minutes_to_end is not None:
        timing = f"Fin: {lot.minutes_to_end} min\n"
    sales = (
        result.evidence.estimate.exact_grade_count
        if result.evidence.estimate is not None
        else 0
    )
    provider_raw = (
        float(result.evidence.estimate.central)
        if result.evidence.estimate is not None
        else result.raw_reference_eur
    )
    pc_line = ""
    if result.pricecharting_guide_eur is not None:
        pc_line = (
            f"Guide PriceCharting compatible: {result.pricecharting_guide_eur:.2f} € "
            "(GUIDE, PAS SOLD)\n"
        )
    msg = (
        f"GCC REVIEW — {flags_text}\n\n"
        f"{lot.title}\n"
        f"Cible GCC: {target_grade}\n"
        f"Proxy marché: {ref_grade}, {sales} vente(s) agrégée(s) PokeTrace\n"
        f"Base proxy: {result.basis}\n"
        f"Prix GCC: {float(lot.current_price or 0):.2f} €\n"
        f"Référence PokeTrace brute: {provider_raw:.2f} €\n"
        f"{pc_line}"
        f"Référence brute conservatrice retenue: {result.raw_reference_eur:.2f} €\n"
        f"Haircut incertitude {haircut_pct:.0f}%: {reference_eur:.2f} €\n"
        f"Décote vs référence haircutée: {discount_pct:.1f}% "
        f"(seuil revue {required_discount_pct:.0f}%)\n"
        f"{timing}"
        "SIGNAL DE REVUE: le grader/langue de référence n'est PAS traité comme "
        "un comparable exact.\n"
        "Vérifier manuellement les SOLD exacts de la cible avant décision.\n\n"
        f"{lot.url}"
    )
    watcher.log(f"*** NOTIFICATION: {flags_text} MANUAL REVIEW ***")
    print(msg, flush=True)
    if not watcher.NTFY_TOPIC:
        return
    try:
        watcher.requests.post(
            f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={
                "Title": Header(
                    f"GCC REVIEW — {flags_text}", "utf-8"
                ).encode(),
                "Priority": "4",
                "Tags": "mag,card_index",
            },
            timeout=10,
        ).raise_for_status()
    except Exception as exc:
        watcher.log(f"Cross-market review ntfy échouée: {type(exc).__name__}")


def _process_delegate(page, candidates, state, budgets, diagnostics, run_now):
    opportunities = _ORIGINAL_PROCESS(
        page, candidates, state, budgets, diagnostics, run_now
    )
    if (
        _max_cards() <= 0
        or not multimarket.POKETRACE_ENABLED
        or not multimarket.POKETRACE_API_KEY
    ):
        return opportunities

    actionable = {str(op.lot.url or "") for op in opportunities}
    budget = multimarket.RequestBudget()
    reviewed = 0
    for candidate in sorted(candidates, key=_priority):
        if reviewed >= _max_cards():
            break
        lot = candidate.lot
        if str(lot.url or "") in actionable or _already_sent(state, lot):
            continue
        if float(lot.current_price or 0.0) <= 0:
            continue
        canonical = multimarket._canonical_from_lot(lot)
        if canonical.status != "EXACT":
            continue

        result = _reference_evidence(lot, canonical, budget, run_now)
        reviewed += 1
        if result is None:
            continue

        haircut = 0.0
        if result.cross_grader:
            haircut += _cross_grader_haircut(
                str(lot.grader or ""), result.basis
            )
        if result.cross_language:
            haircut += _CROSS_LANGUAGE_HAIRCUT_PCT
        haircut = min(65.0, haircut)

        reference = result.raw_reference_eur * (1.0 - haircut / 100.0)
        price = float(lot.current_price or 0.0)
        if reference <= 0:
            continue
        discount = (reference - price) / reference * 100.0
        required_discount = _required_review_discount(
            cross_grader=result.cross_grader
        )
        if discount < required_discount:
            continue

        _notify(
            lot,
            result,
            haircut_pct=haircut,
            reference_eur=reference,
            discount_pct=discount,
            required_discount_pct=required_discount,
        )
        _mark_sent(
            state,
            lot,
            run_now,
            reference,
            basis=result.basis,
        )

    watcher.log(
        "Cross-market recall review: "
        f"probed={reviewed}/{_max_cards()} | "
        f"poketrace_requests={budget.poketrace_requests} | "
        f"base_min_discount={_min_discount():.0f}% | "
        f"cross_grader_floor={_CROSS_GRADER_REVIEW_FLOOR_PCT:.0f}%"
    )
    return opportunities


def install_v4_crossmarket_recall_review() -> None:
    global _ORIGINAL_PROCESS, _ORIGINAL_POKETRACE, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_PROCESS = watcher.process_external_market_candidates
    _ORIGINAL_POKETRACE = multimarket._poketrace_evidence
    watcher.process_external_market_candidates = _process_delegate
    _INSTALLED = True
