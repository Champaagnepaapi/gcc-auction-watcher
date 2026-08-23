from __future__ import annotations

import unittest
from unittest import mock

import v4_global_marketplace_magi_recovery_budget as budget
import v4_global_marketplace_magi_unique_full_number as unique_full
from v4_global_marketplace_scan import ScanStatus


class FakeRecoveryResolver:
    instances = []

    def __init__(self, *, max_requests):
        self.max_requests = max_requests
        self.requests_used = 7
        self.closed = False
        type(self).instances.append(self)

    def close(self):
        self.closed = True


class MagiRecoveryBudgetTests(unittest.TestCase):
    def tearDown(self):
        budget._ACTIVE_RECOVERY_RESOLVER = None
        FakeRecoveryResolver.instances.clear()

    def test_scan_scopes_separate_recovery_resolver_and_reports_usage(self):
        seen = []

        def original_scan(*_args, **_kwargs):
            seen.append(budget.active_recovery_resolver(None))
            return [], ScanStatus("magi", "OK", candidates=96, exact=9, detail="native", complete=True)

        with mock.patch.object(budget, "_ORIGINAL_SCAN", original_scan), mock.patch.object(
            budget, "CachedRecoveryResolver", FakeRecoveryResolver
        ):
            rows, status = budget._scan_with_recovery_budget(object(), (), observed_at=object())

        self.assertEqual(rows, [])
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], FakeRecoveryResolver.instances[0])
        self.assertEqual(FakeRecoveryResolver.instances[0].max_requests, budget._MAX_RECOVERY_REQUESTS)
        self.assertTrue(FakeRecoveryResolver.instances[0].closed)
        self.assertIsNone(budget._ACTIVE_RECOVERY_RESOLVER)
        self.assertIn("tcgdex_recovery_requests=7", status.detail)

    def test_unique_full_number_wrapper_prefers_active_recovery_resolver(self):
        main_resolver = object()
        recovery_resolver = object()
        expected = object()

        with mock.patch.object(unique_full, "_ORIGINAL_RESOLVER", lambda ask, **kwargs: "original"), mock.patch.object(
            budget, "_ACTIVE_RECOVERY_RESOLVER", recovery_resolver
        ), mock.patch.object(
            unique_full,
            "recover_unique_full_number_resolution",
            return_value=expected,
        ) as recover:
            result = unique_full._resolve_with_unique_full_number("ask", resolver=main_resolver)

        self.assertIs(result, expected)
        self.assertIs(recover.call_args.kwargs["resolver"], recovery_resolver)

    def test_direct_calls_keep_existing_resolver_for_unit_scope(self):
        fallback = object()
        self.assertIs(budget.active_recovery_resolver(fallback), fallback)


if __name__ == "__main__":
    unittest.main()
