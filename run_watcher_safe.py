from __future__ import annotations

from math import ceil
from typing import Optional

import watcher
from v4_auction_item_discovery import install_v4_auction_item_discovery


MIN_EXTERNAL_EXACT_GRADE_COMPS = 2
FIXED_DISCOVERY_ALERT_TOLERANCE_RATIO = 0.002
FIXED_DISCOVERY_ALERT_TOLERANCE_MIN_ROWS = 3
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


def fixed_discovery_requires_technical_alert(
    diagnostics: watcher.RunDiagnostics,
) -> bool:
    """Return True only when incomplete fixed discovery is materially risky.

    GCC's declared total can move while the paginated scan is running. A tiny
    same-query delta with every page fetched successfully is useful diagnostic
    information, but it should not look like an economic opportunity on ntfy.
    Structural failures and material gaps remain phone-worthy.
    """

    fixed = diagnostics.fixed_coverage
    if fixed.status != watcher.COVERAGE_INCOMPLETE:
        return False

    if any(
        (
            fixed.pages_failed > 0,
            fixed.internal_errors > 0,
            fixed.parse_failures > 0,
            fixed.unaccounted_listings > 0,
            fixed.unaccounted_reconciled > 0,
        )
    ):
        return True

    # Only benign pagination endings are eligible for small-drift suppression.
    # Repeated pages, malformed payloads, max-page limits, no-progress, etc.
    # remain technical alerts even if the numerical gap happens to be small.
    benign_dynamic_endings = {
        watcher.END_TOTAL_NOT_REACHED,
        watcher.END_SHORT_FINAL_PAGE,
        watcher.END_NO_NEXT_PAGE,
    }
    if fixed.pagination_end_reason not in benign_dynamic_endings:
        return True

    missing = fixed.missing_vs_declared_total
    if missing is None:
        return True

    expected_total = max(0, int(fixed.expected_total or 0))
    tolerance = max(
        FIXED_DISCOVERY_ALERT_TOLERANCE_MIN_ROWS,
        ceil(expected_total * FIXED_DISCOVERY_ALERT_TOLERANCE_RATIO),
    )
    return missing > tolerance


def guarded_technical_alert_required(diagnostics: watcher.RunDiagnostics) -> bool:
    """Keep ntfy for actionable scan failures, not harmless inventory drift."""

    queue = diagnostics.fixed_queue
    fixed_risk = fixed_discovery_requires_technical_alert(diagnostics)
    other_risk = any(
        (
            diagnostics.auction_coverage.status == watcher.COVERAGE_INCOMPLETE,
            diagnostics.auction_economic_coverage.status
            == watcher.COVERAGE_INCOMPLETE,
            queue.budget_skipped_count(watcher.QUEUE_P0_NEW) > 0,
            queue.budget_skipped_count(watcher.QUEUE_P1_CHANGED) > 0,
            bool(queue.failed_ids),
            bool(diagnostics.state_issue),
            queue.initialized and not queue.accounting_coherent,
            diagnostics.fixed_economic_coverage.missing_attempts > 0,
        )
    )
    required = fixed_risk or other_risk

    if (
        not required
        and diagnostics.fixed_coverage.status == watcher.COVERAGE_INCOMPLETE
    ):
        fixed = diagnostics.fixed_coverage
        watcher.log(
            "Alerte ntfy technique supprimée: petit drift d'inventaire fixed "
            f"({fixed.unique_listings}/{fixed.expected_total}, "
            f"missing={fixed.missing_vs_declared_total}) sans panne ni backlog"
        )
    return required


def install_technical_alert_guard() -> None:
    """Separate actionable technical failures from harmless count drift."""

    watcher._technical_alert_required = guarded_technical_alert_required


def estimated_all_queue_backlog_runs(
    queue: watcher.FixedEconomicQueueDiagnostics,
) -> int:
    """Estimate runs needed to drain every queued item, including STALE.

    Coverage semantics stay unchanged: only NEW/CHANGED/NEVER_EVALUATED are
    coverage-critical. This helper only fixes the human-facing backlog metric so
    a remaining STALE queue is not reported as zero runs.
    """

    backlog = queue.queued_backlog
    if backlog <= 0:
        return 0
    budget = max(1, int(queue.processing_budget))
    return ceil(backlog / budget)


def install_fixed_queue_backlog_diagnostics() -> None:
    """Make the production backlog-run estimate include stale reevaluations."""

    watcher.FixedEconomicQueueDiagnostics.estimated_backlog_runs = property(
        estimated_all_queue_backlog_runs
    )


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
    install_technical_alert_guard()
    install_fixed_queue_backlog_diagnostics()
    install_v4_auction_item_discovery()
    install_current_auction_discovery_diagnostics()
    raise SystemExit(watcher.main())
