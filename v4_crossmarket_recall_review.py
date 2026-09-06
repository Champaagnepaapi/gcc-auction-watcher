from __future__ import annotations

"""Bounded cross-grader/cross-language recall lane for manual review only.

The lane exists to avoid silently losing cards whose exact target grader or
language has sparse market data. It never calls a PSA/English reference an exact
PCA/French fair value. TCGdex must first prove the exact macro card, any language
bridge must resolve the same TCGdex card id/set/localId, and the reference is
haircut before a clearly-labelled manual-review alert can be emitted.
"""

import math
import os
from dataclasses import replace
from datetime import datetime
from email.header import Header
from typing import Mapping, Optional

import watcher
import v4_canonical_multimarket as multimarket


_STATE_KEY = "v4_crossmarket_recall_review"
_SCHEMA_VERSION = 1
_ORIGINAL_PROCESS = None
_ORIGINAL_POKETRACE = None
_INSTALLED = False


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


def _state_key(lot: watcher.Lot) -> str:
    url = str(lot.url or "").strip().rstrip("/")
    return url or watcher.external_commercial_identity_key(lot)


def _already_sent(state: dict, lot: watcher.Lot) -> bool:
    root = state.get(_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != _SCHEMA_VERSION:
        return False
    entries = root.get("entries")
    return isinstance(entries, dict) and bool(entries.get(_state_key(lot)))


def _mark_sent(state: dict, lot: watcher.Lot, now: datetime, reference: float) -> None:
    root = state.get(_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != _SCHEMA_VERSION:
        root = {"schema_version": _SCHEMA_VERSION, "entries": {}}
        state[_STATE_KEY] = root
    root.setdefault("entries", {})[_state_key(lot)] = {
        "notified_at": now.isoformat(),
        "reference_eur": round(reference, 2),
        "gcc_price": round(float(lot.current_price or 0.0), 2),
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
    # Never synthesize PSA 9.5. For half grades, use the lower whole PSA grade as
    # the conservative cross-grader reference; 10 remains 10.
    if target >= 10:
        return 10.0
    if float(target).is_integer():
        return target
    return max(1.0, float(math.floor(target)))


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


def _reference_evidence(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> tuple[watcher.ExternalMarketEvidence, float, bool, bool] | None:
    target_grade = _numeric_grade(lot)
    if target_grade is None:
        return None
    bridged = _english_bridge(lot, canonical)
    if bridged is None:
        return None
    proxy_lot, proxy_canonical, cross_language = bridged

    target_grader = str(lot.grader or "").strip().upper()
    reference_grade = _reference_psa_grade(target_grade)
    cross_grader = target_grader != "PSA" or reference_grade != target_grade
    if not cross_grader and not cross_language:
        return None

    grade_text = (
        str(int(reference_grade))
        if reference_grade.is_integer()
        else str(reference_grade)
    )
    proxy_lot = replace(proxy_lot, grader="PSA", grade=grade_text)
    evidence = _ORIGINAL_POKETRACE(proxy_lot, proxy_canonical, budget, now)
    if (
        evidence.status != watcher.EXTERNAL_MATCHED
        or evidence.strength != watcher.EVIDENCE_STRONG
        or evidence.estimate is None
        or evidence.estimate.central <= 0
    ):
        return None
    return evidence, reference_grade, cross_grader, cross_language


def _notify(
    lot: watcher.Lot,
    evidence: watcher.ExternalMarketEvidence,
    *,
    reference_grade: float,
    cross_grader: bool,
    cross_language: bool,
    haircut_pct: float,
    reference_eur: float,
    discount_pct: float,
) -> None:
    flags = []
    if cross_grader:
        flags.append("CROSS-GRADER")
    if cross_language:
        flags.append("CROSS-LANGUAGE")
    flags_text = " + ".join(flags)
    target_grade = (
        watcher.format_grade_label(lot.grader, lot.grade) or "grade inconnu"
    )
    ref_grade = f"PSA {reference_grade:g}"
    timing = ""
    if lot.source_type == "auction" and lot.minutes_to_end is not None:
        timing = f"Fin: {lot.minutes_to_end} min\n"
    sales = evidence.estimate.exact_grade_count if evidence.estimate is not None else 0
    msg = (
        f"GCC REVIEW — {flags_text}\n\n"
        f"{lot.title}\n"
        f"Cible GCC: {target_grade}\n"
        f"Référence PokeTrace: {ref_grade}, {sales} vente(s) agrégée(s)\n"
        f"Prix GCC: {float(lot.current_price or 0):.2f} €\n"
        f"Référence externe brute: {evidence.estimate.central:.2f} €\n"
        f"Haircut incertitude {haircut_pct:.0f}%: {reference_eur:.2f} €\n"
        f"Décote vs référence haircutée: {discount_pct:.1f}%\n"
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
        evidence, reference_grade, cross_grader, cross_language = result

        haircut = 0.0
        if cross_grader:
            haircut += 20.0
        if cross_language:
            haircut += 20.0
        target_grade = _numeric_grade(lot)
        if target_grade is not None and reference_grade != target_grade:
            haircut += 10.0
        haircut = min(45.0, haircut)
        reference = evidence.estimate.central * (1.0 - haircut / 100.0)
        price = float(lot.current_price or 0.0)
        if reference <= 0:
            continue
        discount = (reference - price) / reference * 100.0
        if discount < _min_discount():
            continue

        _notify(
            lot,
            evidence,
            reference_grade=reference_grade,
            cross_grader=cross_grader,
            cross_language=cross_language,
            haircut_pct=haircut,
            reference_eur=reference,
            discount_pct=discount,
        )
        _mark_sent(state, lot, run_now, reference)

    watcher.log(
        "Cross-market recall review: "
        f"probed={reviewed}/{_max_cards()} | "
        f"poketrace_requests={budget.poketrace_requests} | "
        f"min_discount={_min_discount():.0f}%"
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
