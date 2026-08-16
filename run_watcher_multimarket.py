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
from v4_canonical_multimarket import install_canonical_multimarket_pipeline
from v4_cert_problem_notifications import install_v4_cert_problem_notifications
from v4_edge_hunter_safety import install_v4_edge_hunter_safety
from v4_exact_active_ask_position import install_v4_exact_active_ask_position
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
from v4_ppt_shadow_grader_guard import install_v4_ppt_shadow_grader_guard
from v4_ppt_shadow_language_bridge import install_v4_ppt_shadow_language_bridge
from v4_private_auction_coverage import install_v4_private_auction_coverage
from v4_roi_efficiency import install_v4_roi_efficiency
from v4_smart_external_priority import install_v4_smart_external_priority
from v4_structural_edge_hunter import install_v4_structural_edge_hunter


def _mislisted_slab_hunter_enabled() -> bool:
    return os.getenv("V4_MISLISTED_SLAB_HUNTER_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _cert_problem_notifications_enabled() -> bool:
    """Emergency-safe switch: immediate cert-problem alerts stay off unless explicitly enabled."""
    return os.getenv("V4_CERT_PROBLEM_NOTIFICATIONS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


if __name__ == "__main__":
    install_psa_apr_hydration_guard()
    install_grade_arbitrage_guard()
    install_technical_alert_guard()
    install_fixed_queue_backlog_diagnostics()
    install_v4_auction_item_discovery()
    install_v4_private_auction_coverage()
    install_current_auction_discovery_diagnostics()
    install_canonical_multimarket_pipeline()
    install_multimarket_safety_hardening()
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
        watcher.log("Mislisted slab hunter: safe-off (V4_MISLISTED_SLAB_HUNTER_ENABLED=false)")
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
    # Shadow-only grader scheduler / network hard-stop. Unsupported graders such
    # as PCA/CCC must consume zero PPT requests; supported PPT graders are tried
    # PSA -> BGS -> CGC -> SGC without changing production candidate ordering.
    install_v4_ppt_shadow_grader_guard()
    # Opt-in only. PPT observes EN exact cards directly. FR physical cards are
    # bridged deterministically to the same TCGdex EN card id for retrieval only;
    # the EN market remains a cross-language anchor until an empirical FR/EN
    # same-card + same-grader + same-grade basis is calibrated. Production
    # opportunities are returned bit-for-bit unchanged and no notification is sent.
    install_v4_ppt_shadow_language_bridge()
    # Install last so the passive wrapper sees the final production collectors.
    install_v4_kb_shadow_capture()
    exit_code = 1
    try:
        exit_code = watcher.main()
    finally:
        flush_capture_if_configured()
    raise SystemExit(exit_code)
