import unittest

import v4_global_marketplace_magi_native_budget as target
import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as resolver


class MagiNativeBudgetTests(unittest.TestCase):
    def test_budget_matches_existing_resolver_baseline_and_stays_bounded(self):
        self.assertEqual(target.MAGI_NATIVE_TCGDEX_REQUEST_BUDGET, 60)
        self.assertEqual(resolver.TCGdexJapaneseProofResolver().max_requests, 60)
        self.assertLessEqual(target.MAGI_NATIVE_TCGDEX_REQUEST_BUDGET, 60)

    def test_installer_changes_only_native_request_ceiling(self):
        old_budget = native._MAX_TCGDEX_JA_REQUESTS
        old_installed = target._INSTALLED
        target._INSTALLED = False
        try:
            native._MAX_TCGDEX_JA_REQUESTS = 40
            target.install_global_marketplace_magi_native_budget()
            self.assertEqual(native._MAX_TCGDEX_JA_REQUESTS, 60)
        finally:
            native._MAX_TCGDEX_JA_REQUESTS = old_budget
            target._INSTALLED = old_installed


if __name__ == "__main__":
    unittest.main()
