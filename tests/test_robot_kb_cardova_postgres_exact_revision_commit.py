from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_postgres_exact_revision_commit.py")

if P3_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("cardova_postgres_exact_revision_commit", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(MOD)
else:
    MOD = None


@unittest.skipUnless(P3_AVAILABLE, "pinned Robot KB P3 runtime is required")
class CardovaPostgresExactRevisionCommitGuardTests(unittest.TestCase):
    def test_requires_both_commit_flag_and_exact_confirmation(self):
        with self.assertRaises(MOD.DurableCommitError):
            MOD.require_operator_authorization(commit=False, confirmation=MOD.CONFIRMATION_PHRASE)
        with self.assertRaises(MOD.DurableCommitError):
            MOD.require_operator_authorization(commit=True, confirmation="YES")
        MOD.require_operator_authorization(
            commit=True,
            confirmation=MOD.CONFIRMATION_PHRASE,
        )

    def test_unauthorized_run_fails_before_backup_or_database_access(self):
        with mock.patch.object(MOD, "create_and_validate_fresh_backup") as backup, mock.patch.object(
            MOD, "connect_postgres"
        ) as connect:
            with self.assertRaises(MOD.DurableCommitError):
                MOD.run_durable_commit(
                    "postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb",
                    commit=False,
                    confirmation=MOD.CONFIRMATION_PHRASE,
                )
            backup.assert_not_called()
            connect.assert_not_called()

    def test_backup_archive_must_be_nontrivial_and_pg_restore_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "robot-kb-test.dump"
            path.write_bytes(b"x" * (MOD.MIN_BACKUP_BYTES + 1))
            completed = mock.Mock(returncode=0)
            with mock.patch.object(MOD.shutil, "which", return_value="/usr/bin/pg_restore"), mock.patch.object(
                MOD.subprocess, "run", return_value=completed
            ) as run:
                result = MOD.validate_backup_archive(path)
            self.assertEqual(result["backup_path"], str(path.resolve()))
            self.assertGreater(result["backup_bytes"], MOD.MIN_BACKUP_BYTES)
            self.assertEqual(len(result["backup_sha256"]), 64)
            self.assertTrue(result["backup_archive_readable"])
            run.assert_called_once()
            self.assertIn("--list", run.call_args.args[0])

    def test_unreadable_backup_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "robot-kb-test.dump"
            path.write_bytes(b"x" * (MOD.MIN_BACKUP_BYTES + 1))
            with mock.patch.object(MOD.shutil, "which", return_value="/usr/bin/pg_restore"), mock.patch.object(
                MOD.subprocess, "run", return_value=mock.Mock(returncode=1)
            ):
                with self.assertRaises(MOD.DurableCommitError):
                    MOD.validate_backup_archive(path)

    def test_safe_summary_keeps_commerce_and_v4_disabled(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["explicit_commit_required"])
        self.assertTrue(summary["exact_confirmation_required"])
        self.assertTrue(summary["fresh_backup_required"])
        self.assertTrue(summary["backup_archive_validation_required"])
        self.assertTrue(summary["single_transaction"])
        self.assertTrue(summary["post_commit_verification_required"])
        self.assertFalse(summary["auto_restore"])
        for key in (
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)


if __name__ == "__main__":
    unittest.main()
