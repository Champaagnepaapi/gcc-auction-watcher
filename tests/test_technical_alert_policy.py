from __future__ import annotations

import unittest
from types import SimpleNamespace

import watcher
from run_watcher_safe import (
    fixed_discovery_requires_technical_alert,
    guarded_technical_alert_required,
)


class _Queue:
    def __init__(
        self,
        *,
        new_skipped=0,
        changed_skipped=0,
        failed=False,
        accounting_coherent=True,
    ):
        self._new_skipped = new_skipped
        self._changed_skipped = changed_skipped
        self.failed_ids = {"failed"} if failed else set()
        self.initialized = True
        self.accounting_coherent = accounting_coherent

    def budget_skipped_count(self, category):
        if category == watcher.QUEUE_P0_NEW:
            return self._new_skipped
        if category == watcher.QUEUE_P1_CHANGED:
            return self._changed_skipped
        return 0


def _fixed(
    *,
    unique=2953,
    expected=2954,
    status=watcher.COVERAGE_INCOMPLETE,
    pages_failed=0,
    internal_errors=0,
    parse_failures=0,
    unaccounted=0,
    reconciled=0,
    end_reason=watcher.END_TOTAL_NOT_REACHED,
):
    return SimpleNamespace(
        status=status,
        unique_listings=unique,
        expected_total=expected,
        pages_failed=pages_failed,
        internal_errors=internal_errors,
        parse_failures=parse_failures,
        unaccounted_listings=unaccounted,
        unaccounted_reconciled=reconciled,
        pagination_end_reason=end_reason,
        missing_vs_declared_total=(
            None if expected is None else max(0, expected - unique)
        ),
    )


def _diagnostics(*, fixed=None, auction_status=watcher.COVERAGE_COMPLETE, queue=None):
    return SimpleNamespace(
        fixed_coverage=fixed or _fixed(),
        auction_coverage=SimpleNamespace(status=auction_status),
        auction_economic_coverage=SimpleNamespace(status=watcher.COVERAGE_COMPLETE),
        fixed_economic_coverage=SimpleNamespace(missing_attempts=0),
        fixed_queue=queue or _Queue(),
        state_issue="",
    )


class TechnicalAlertPolicyTests(unittest.TestCase):
    def test_one_row_dynamic_fixed_drift_is_log_only(self):
        diagnostics = _diagnostics(fixed=_fixed(unique=2953, expected=2954))

        self.assertFalse(fixed_discovery_requires_technical_alert(diagnostics))
        self.assertFalse(guarded_technical_alert_required(diagnostics))

    def test_material_fixed_gap_still_alerts(self):
        diagnostics = _diagnostics(fixed=_fixed(unique=2940, expected=2954))

        self.assertTrue(fixed_discovery_requires_technical_alert(diagnostics))
        self.assertTrue(guarded_technical_alert_required(diagnostics))

    def test_failed_page_alerts_even_for_one_missing_row(self):
        diagnostics = _diagnostics(
            fixed=_fixed(unique=2953, expected=2954, pages_failed=1)
        )

        self.assertTrue(fixed_discovery_requires_technical_alert(diagnostics))
        self.assertTrue(guarded_technical_alert_required(diagnostics))

    def test_structural_pagination_failure_is_never_suppressed(self):
        diagnostics = _diagnostics(
            fixed=_fixed(
                unique=2953,
                expected=2954,
                end_reason=watcher.END_REPEATED_PAGE,
            )
        )

        self.assertTrue(fixed_discovery_requires_technical_alert(diagnostics))

    def test_incomplete_auction_discovery_still_alerts(self):
        diagnostics = _diagnostics(
            fixed=_fixed(status=watcher.COVERAGE_COMPLETE, unique=2954, expected=2954),
            auction_status=watcher.COVERAGE_INCOMPLETE,
        )

        self.assertTrue(guarded_technical_alert_required(diagnostics))

    def test_urgent_new_or_changed_backlog_still_alerts(self):
        fixed_complete = _fixed(
            status=watcher.COVERAGE_COMPLETE,
            unique=2954,
            expected=2954,
        )
        self.assertTrue(
            guarded_technical_alert_required(
                _diagnostics(fixed=fixed_complete, queue=_Queue(new_skipped=1))
            )
        )
        self.assertTrue(
            guarded_technical_alert_required(
                _diagnostics(fixed=fixed_complete, queue=_Queue(changed_skipped=1))
            )
        )


if __name__ == "__main__":
    unittest.main()
