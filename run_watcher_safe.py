from __future__ import annotations

from typing import Optional

import watcher


MIN_EXTERNAL_EXACT_GRADE_COMPS = 2
_ORIGINAL_VALIDATE_SECONDARY_SOURCES = watcher.validate_secondary_sources


def external_exact_target_grade_count(op: watcher.Opportunity) -> int:
    """Count independent exact-card evidence for the exact target grade.

    GCC neighbour-grade sales are intentionally excluded: they are the signal
    being validated, not independent confirmation. PSA APR/eBay exact target
    grade comparables can confirm the candidate.
    """

    target_grade = watcher._target_grade(op.lot)
    target_grader = (op.lot.grader or "").strip().upper()
    if target_grade is None or not target_grader:
        return 0
    return sum(
        bool(sale.exact_card)
        and sale.grade == target_grade
        and (sale.grader or "").strip().upper() == target_grader
        for sale in op.psa_apr_comparables + op.ebay_comparables
    )


def grade_arbitrage_external_validation_sufficient(
    op: watcher.Opportunity,
    minimum: int = MIN_EXTERNAL_EXACT_GRADE_COMPS,
) -> bool:
    if not op.estimate.grade_arbitrage:
        return True
    return external_exact_target_grade_count(op) >= max(1, minimum)


def guarded_validate_secondary_sources(
    page,
    op: watcher.Opportunity,
    budgets: watcher.ValidationBudgets,
    grader_ratios: Optional[list[watcher.EmpiricalGraderRatio]] = None,
    apr_validator=None,
    ebay_validator=None,
) -> Optional[watcher.Opportunity]:
    validated = _ORIGINAL_VALIDATE_SECONDARY_SOURCES(
        page,
        op,
        budgets,
        grader_ratios=grader_ratios,
        apr_validator=apr_validator,
        ebay_validator=ebay_validator,
    )
    if validated is None or not validated.estimate.grade_arbitrage:
        return validated

    exact_external = external_exact_target_grade_count(validated)
    if exact_external < MIN_EXTERNAL_EXACT_GRADE_COMPS:
        card_name = (
            watcher.extract_card_identity(validated.lot).get("core")
            or validated.lot.title
            or "carte inconnue"
        )
        watcher.log(
            "Rejet sécurité arbitrage grade: "
            f"{card_name} | {exact_external}/"
            f"{MIN_EXTERNAL_EXACT_GRADE_COMPS} comparable(s) externe(s) "
            "même carte + même grader + grade cible exact; "
            "un grade inférieur GCC seul ne peut plus déclencher une alerte"
        )
        return None
    return validated


def install_grade_arbitrage_guard() -> None:
    """Install only for the production entrypoint, never merely on import."""

    watcher.validate_secondary_sources = guarded_validate_secondary_sources


if __name__ == "__main__":
    # Keep V4 discovery/valuation intact; harden only the final validation gate
    # used by the production workflow before ntfy notification.
    install_grade_arbitrage_guard()
    raise SystemExit(watcher.main())
