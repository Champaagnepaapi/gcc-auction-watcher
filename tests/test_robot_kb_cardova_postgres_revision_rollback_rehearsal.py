from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_postgres_revision_rollback_rehearsal.py")

if P3_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("cardova_postgres_revision_rollback_rehearsal", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    sys.modules[SPEC.name] = MOD
    SPEC.loader.exec_module(MOD)
else:
    MOD = None


@unittest.skipUnless(P3_AVAILABLE, "pinned Robot KB P3 runtime is required")
class CardovaPostgresRevisionRollbackRehearsalTests(unittest.TestCase):
    def test_safety_contract_has_no_commit_mode(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["outer_transaction_required"])
        self.assertFalse(summary["commit_path_exposed"])
        self.assertTrue(summary["migration_3_applied_transactionally_only"])
        self.assertTrue(summary["append_only_revision_promotion"])
        self.assertFalse(summary["sealed_original_updated"])
        self.assertTrue(summary["rollback_verification_required"])
        for key in (
            "local_postgres_durable_write",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)

    def test_source_exposes_no_commit_or_auto_migration_path(self):
        source = PATH.read_text(encoding="utf-8")
        self.assertNotIn('connection.execute("COMMIT")', source)
        self.assertNotIn("apply_postgres_migrations", source)
        self.assertNotIn("KnowledgeBase.open(database_url", source)
        self.assertIn('connection.execute("ROLLBACK")', source)

    def test_advisory_lock_fits_signed_postgres_bigint(self):
        self.assertGreater(MOD.LOCK_KEY, 0)
        self.assertLessEqual(MOD.LOCK_KEY, 9_223_372_036_854_775_807)

    def test_rehearsal_is_pinned_to_validated_p3_207(self):
        self.assertEqual(
            MOD.EXPECTED_P3_RUNTIME,
            "38288a950db8285bcbf279d91354f8a1ad3a8c2f",
        )
        self.assertEqual(MOD.MIGRATION_VERSION, 3)
        self.assertEqual(MOD.MIGRATION_FILENAME, "0003_print_run_rarity_symbol.sql")


if __name__ == "__main__":
    unittest.main()
