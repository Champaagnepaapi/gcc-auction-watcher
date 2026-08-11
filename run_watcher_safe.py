from __future__ import annotations

from typing import Optional

import watcher
from v4_auction_item_discovery import install_v4_auction_item_discovery


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


def install_current_auction_discovery_diagnostics() -> None:
    """Keep V4 log/coverage text aligned with the installed item-level source."""

    watcher.AUCTION_DISCOVERY_FILTERS = (
        "endpoint=/on-sale-items (official GCC API)",
        "sellingTypeGroup=AUCTION (GCC)",
        "sortType=ENDING_SOON (GCC)",
        "status=ON_SALE (GCC)",
        "endTime=individual lot end time (GCC)",
        f"remaining_time<={watcher.MAX_AUCTION_MINUTES} min (local defense)",
        "category=Pokemon card (existing local rule)",
        f"min_price={watcher.MIN_PRICE:g} EUR (existing local rule)",
        f"max_price={watcher.MAX_PRICE:g} EUR (existing local rule)",
        "grader=ALL",
        "grade=ALL",
        "legacy live-sale pages=fallback only if API coverage cannot be proven",
    )


if __name__ == "__main__":
    # Keep V4 valuation and notification safeguards intact. Auction discovery is
    # item-level through GCC's official /on-sale-items API, ordered ENDING_SOON
    # and filtered by each lot's individual endTime. The previous live-sale
    # collector is preserved strictly as a conservative fallback.
    install_grade_arbitrage_guard()
    install_v4_auction_item_discovery()
    install_current_auction_discovery_diagnostics()
    raise SystemExit(watcher.main())
