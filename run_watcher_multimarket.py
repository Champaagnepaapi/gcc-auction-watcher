from __future__ import annotations

import os

import watcher
from run_watcher_safe import (
    install_current_auction_discovery_diagnostics,
    install_fixed_queue_backlog_diagnostics,
    install_grade_arbitrage_guard,
    install_psa_apr_hydration_guard,
    install_technical_alert_guard,
)
from v4_auction_item_discovery import install_v4_auction_item_discovery
from v4_auction_last_chance import install_fast_lane_notification_guard
from v4_auction_pagination_stability import install_v4_auction_pagination_stability
from v4_canonical_multimarket import install_canonical_multimarket_pipeline
from v4_cert_problem_notifications import install_v4_cert_problem_notifications
from v4_edge_hunter_safety import install_v4_edge_hunter_safety
from v4_exact_active_ask_position import install_v4_exact_active_ask_position
from v4_external_coverage_drain import install_v4_external_coverage_drain
from v4_external_provider_navigation_resilience import (
    install_v4_external_provider_navigation_resilience,
)
from v4_focus_cert_router import install_v4_focus_cert_router
from v4_kb_shadow_bridge import (
    flush_capture_if_configured,
    install_v4_kb_shadow_capture,
)
from v4_manual_slab_review import install_v4_manual_slab_review_notifications
from v4_mislisted_cert_router import install_v4_mislisted_cert_router
from v4_mislisted_ocr_hardening import install_v4_mislisted_ocr_hardening
from v4_mislisted_slab_hunter import install_v4_mislisted_slab_hunter
from v4_multimarket_safety import install_multimarket_safety_hardening
from v4_notification_semantics import install_v4_notification_semantics
from v4_notification_signal_quality_guard import (
    install_v4_notification_signal_quality_guard,
)
from v4_poketrace_market_retrieval import install_v4_poketrace_market_retrieval
from v4_private_auction_coverage import install_v4_private_auction_coverage
from v4_provider_rejection_observability import (
    install_v4_provider_rejection_observability,
)
from v4_roi_efficiency import install_v4_roi_efficiency
from v4_smart_external_priority import install_v4_smart_external_priority
from v4_structural_edge_hunter import install_v4_structural_edge_hunter
from v4_tcgdex_detailed_variants import install_v4_tcgdex_detailed_variants
from v4_tcgdex_exact_coordinate_recovery import install_v4_tcgdex_exact_coordinate_recovery
from v4_tcgdex_generalized_coordinate_recovery import (
    install_v4_tcgdex_generalized_coordinate_recovery,
)
from v4_tcgdex_japanese_set_aliases import install_v4_tcgdex_japanese_set_aliases
from v4_tcgdex_observability import install_v4_tcgdex_observability
from v4_tcgdex_run1054_set_aliases import install_v4_tcgdex_run1054_set_aliases
from v4_tcgdex_source_pinned_finish import install_v4_tcgdex_source_pinned_finish
from v4_tcgdex_two_of_three_backport import (
    install_v4_tcgdex_two_of_three_backport,
)
from v4_tcgdex_unique_coordinate_fallback import (
    install_v4_tcgdex_unique_coordinate_fallback,
)


def _mislisted_slab_hunter_enabled() -> bool:
    """User-disabled in V4 production after repeated OCR/manual-review false positives.

    Keep the implementation available for future diagnostics, but never install it
    in the production watcher regardless of workflow environment overrides.
    """
    return False


def _cert_problem_notifications_enabled() -> bool:
    """Emergency-safe switch: immediate cert-problem alerts stay off unless explicitly enabled."""
    return os.getenv("V4_CERT_PROBLEM_NOTIFICATIONS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


if __name__ == "__main__":
    install_psa_apr_hydration_guard()
    # eBay/PSA public pages sometimes finish rendering usable DOM after
    # Playwright's domcontentloaded deadline. Reuse that already-loaded DOM only
    # when the expected provider host + structured controls/items are proven;
    # never retry the network request and never relax provider matching.
    install_v4_external_provider_navigation_resilience()
    install_grade_arbitrage_guard()
    install_technical_alert_guard()
    install_fixed_queue_backlog_diagnostics()
    install_v4_auction_item_discovery()
    # GCC's ENDING_SOON inventory is live. Stabilize page-number pagination
    # across anchored snapshots before the private legacy safety net augments it.
    install_v4_auction_pagination_stability()
    install_v4_private_auction_coverage()
    install_current_auction_discovery_diagnostics()
    install_canonical_multimarket_pipeline()
    # First preserve the bounded reviewed per-card bridges from PR #119.
    install_v4_tcgdex_exact_coordinate_recovery()
    # Register reviewed set-level aliases before the generic exact-coordinate
    # layer. Run-1054 aliases stay intact; the Japanese registry extension is
    # separately source-pinned and conflict-checked.
    install_v4_tcgdex_run1054_set_aliases()
    install_v4_tcgdex_japanese_set_aliases()
    # Then recover whole exact set/namespaces and bounded display suffix cases.
    # This remains exact set + localId proof: no fuzzy matching or variant bypass.
    install_v4_tcgdex_generalized_coordinate_recovery()
    # Backport the already-proven V5 PR #31 catalogue-cardinality rules before
    # the broader coordinate-only fallback: exact name+full-number may recover
    # one set, and exact set+name may recover one printed number. Two exact
    # coordinates are mandatory and ambiguity remains fail-closed.
    install_v4_tcgdex_two_of_three_backport()
    # Last TCGdex identity fallback: after every existing exact path says
    # NO_MATCH, prove a globally unique printed coordinate without adding aliases.
    install_v4_tcgdex_unique_coordinate_fallback()
    # Correct only immutable, source-pinned finish metadata when the exact same
    # TCGdex card's REST projection is known to disagree with cards-database.
    # This runs after identity is fully proven and before any market provider.
    install_v4_tcgdex_source_pinned_finish()
    # PokeTrace stays market-only. Recover V5's proven structured retrieval
    # contract (card_number + language game) only after TCGdex has resolved the
    # canonical card; all exact candidate/commercial/grade gates remain V4's.
    install_v4_poketrace_market_retrieval()
    install_multimarket_safety_hardening()
    # TCGdex variants_detailed is consumed only after the final V4 provider gate
    # exists, so it can narrow a proven exact card without creating a resolver or
    # bypassing the source-pinned Japanese finish fallback. Missing detail keeps
    # legacy behavior; malformed/conflicting material detail fails closed.
    install_v4_tcgdex_detailed_variants()
    # Install after the canonical/multimarket pipeline so these guards wrap the
    # final Edge Hunter functions rather than being overwritten by an installer.
    install_v4_edge_hunter_safety()
    # V4 is a graded-slab pipeline: RAW Cardmarket/TCGplayer cannot rescue
    # opportunities. Install after Edge Hunter safety so identity fail-closed
    # semantics stay underneath the notification-quality filter.
    install_v4_notification_signal_quality_guard()
    # Reorders only scarce fixed external-provider calls. Auctions retain the
    # canonical ending-soon ordering and economics are untouched.
    install_v4_smart_external_priority()
    # Keep auction ordering intact but reserve bounded eBay SOLD capacity for
    # fixed cards, and treat provider-budget exhaustion as scheduling pressure
    # rather than a six-hour provider failure backoff.
    install_v4_external_coverage_drain()
    if _mislisted_slab_hunter_enabled():
        # Generic official-cert coverage stays available for supported graders.
        # PSA/PCA/CCC then receive the hardened browser/direct routes, followed
        # by focused image OCR only when the official cert is unavailable.
        install_v4_mislisted_cert_router()
        install_v4_focus_cert_router()
        install_v4_mislisted_ocr_hardening()
        install_v4_mislisted_slab_hunter()
        # Immediate broad cert-problem alerts are intentionally safe-off after
        # false CERT_NUMBER_MISSING spam from collapsed GCC Gradation panels.
        if _cert_problem_notifications_enabled():
            install_v4_cert_problem_notifications()
        else:
            watcher.log(
                "Cert problem notifications: safe-off "
                "(V4_CERT_PROBLEM_NOTIFICATIONS_ENABLED=false)"
            )
    else:
        watcher.log("Mislisted slab hunter: disabled by production policy")
    install_fast_lane_notification_guard()
    # Only changes user-facing opportunity labels; economics and decisions stay intact.
    install_v4_notification_semantics()
    # Install last in the notification stack: unresolved cert+OCR review alerts
    # must not be overwritten by the ordinary external-confirmation title wrapper.
    if _mislisted_slab_hunter_enabled():
        install_v4_manual_slab_review_notifications()
    # Adds read-only stale-listing/SOLD-momentum context and a fixed-queue
    # information-value bonus. It cannot create an opportunity or alter FV/max.
    install_v4_roi_efficiency()
    # Active asks are context only and must wrap the final opportunity/ntfy stack.
    # They never create an opportunity or alter FV/max_recommended. Positive
    # exact asks are briefly cached by strict commercial identity.
    install_v4_exact_active_ask_position()
    # Structural edges consume exact SOLD + active-ask context. Expected Profit
    # is secondary/ranking-only and can never suppress a V4 notification.
    install_v4_structural_edge_hunter()
    # IMPORTANT: multimarket safety replaces watcher.process_external_market_candidates.
    # Finalize TCGdex observability only after every runtime installer that can
    # replace/wrap that entrypoint, otherwise the preservation wrapper is lost.
    # This remains diagnostics-only: no identity, matching, valuation or budget change.
    install_v4_tcgdex_observability()
    # Final bounded reason logging wraps the already-installed TCGdex/PokeTrace
    # gates. It records only public card/provider identity fields and cannot
    # change matching, evidence, budgets, valuation, notifications or state.
    install_v4_provider_rejection_observability()
    # Install last so the passive wrapper sees the final production collectors.
    install_v4_kb_shadow_capture()
    exit_code = 1
    try:
        exit_code = watcher.main()
    finally:
        flush_capture_if_configured()
    raise SystemExit(exit_code)
