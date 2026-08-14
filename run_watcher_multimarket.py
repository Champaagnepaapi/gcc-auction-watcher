from __future__ import annotations

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
from v4_kb_shadow_bridge import (
    flush_capture_if_configured,
    install_v4_kb_shadow_capture,
)
from v4_multimarket_safety import install_multimarket_safety_hardening
from v4_private_auction_coverage import install_v4_private_auction_coverage


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
    install_fast_lane_notification_guard()
    # Install last so the passive wrapper sees the final production collectors.
    install_v4_kb_shadow_capture()
    exit_code = 1
    try:
        exit_code = watcher.main()
    finally:
        flush_capture_if_configured()
    raise SystemExit(exit_code)
