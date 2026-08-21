from pathlib import Path
import unittest


class RobotKbLocalMacMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path("mac/robot-kb-local")
        cls.installer = (root / "Installer Robot KB Local.command").read_text(encoding="utf-8")
        cls.migration = (root / "Migrer Robot KB Neon vers Mac.command").read_text(encoding="utf-8")
        cls.runner = (root / "robot_kb_local_runner.sh").read_text(encoding="utf-8")
        cls.status = (root / "Etat Robot KB Local.command").read_text(encoding="utf-8")

    def test_reuses_validated_p3_runtime_and_loopback_postgres(self):
        pin = "1d06fe33b6fc640657255e15a8d17251aa02b6ce"
        self.assertIn(pin, self.installer)
        local_url = "postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb"
        self.assertIn(local_url, self.installer)
        self.assertIn(local_url, self.runner)
        self.assertIn('git -C "$REPO_ROOT" archive "$P3_SHA" robot_kb requirements-postgres.txt requirements.txt', self.installer)

    def test_existing_enterprisedb_postgres_is_reused_before_homebrew_fallback(self):
        self.assertIn('/Library/PostgreSQL/18/bin', self.installer)
        self.assertIn('/Library/PostgreSQL/17/bin', self.installer)
        self.assertIn('/Library/PostgreSQL/16/bin', self.installer)
        detection = self.installer.index('POSTGRES_BIN="$(find_postgres_bin || true)"')
        fallback = self.installer.index('brew install postgresql@16')
        self.assertLess(detection, fallback)
        self.assertIn('PostgreSQL existant détecté', self.installer)

    def test_local_database_password_is_generated_and_keychain_only(self):
        self.assertIn('KEYCHAIN_SERVICE="RobotPokemonKB.local-postgres"', self.installer)
        self.assertIn('openssl rand -hex 24', self.installer)
        self.assertIn('security add-generic-password', self.installer)
        self.assertIn('security find-generic-password', self.runner)
        self.assertNotIn('PGPASSWORD":', self.installer)
        launchagent_generation = self.installer.index('Generate LaunchAgents')
        launchagent_tail = self.installer[launchagent_generation:]
        self.assertNotIn('APP_PASSWORD', launchagent_tail)
        self.assertNotIn('PGPASSWORD', launchagent_tail.split('unset PGPASSWORD')[0])

    def test_admin_password_is_masked_and_never_persisted(self):
        self.assertIn('read -r -s ADMIN_PASSWORD', self.installer)
        self.assertIn('unset PGPASSWORD ADMIN_PASSWORD', self.installer)
        self.assertNotIn('echo "$ADMIN_PASSWORD"', self.installer)
        self.assertNotIn('security add-generic-password -U -a "$ADMIN_USER"', self.installer)

    def test_installation_refuses_unverified_nonempty_database(self):
        self.assertIn('MIGRATION_MARKER="$DATA_ROOT/MIGRATION_VERIFIED"', self.installer)
        self.assertIn('Une base locale non vide existe mais aucune migration Neon vérifiée', self.installer)
        self.assertIn('Migration Neon non vérifiée; activation locale refusée.', self.installer)
        marker_check = self.installer.index('if [ ! -f "$MIGRATION_MARKER" ] && [ "${local_table_count:-0}" -gt 0 ]')
        launchagent_generation = self.installer.index('Generate LaunchAgents')
        self.assertLess(marker_check, launchagent_generation)

    def test_neon_url_is_hidden_ephemeral_and_never_written(self):
        self.assertIn('read -r -s NEON_URL', self.migration)
        self.assertIn('unset NEON_URL', self.migration)
        self.assertNotIn('echo "$NEON_URL"', self.migration)
        self.assertNotIn('printf "$NEON_URL"', self.migration)
        self.assertNotIn('ROBOT_KB_DATABASE_URL="$NEON_URL" >', self.migration)

    def test_migration_requires_empty_local_db_dump_restore_and_fingerprint_verification(self):
        self.assertIn('local_table_count=', self.migration)
        self.assertIn('contient déjà des tables. Migration refusée', self.migration)
        self.assertIn('robot_kb.postgres_backup dump', self.migration)
        self.assertIn('restore_database', self.migration)
        self.assertIn('_database_fingerprints', self.migration)
        self.assertIn('if source != local:', self.migration)
        self.assertIn('MIGRATION_VERIFY_MISMATCH', self.migration)
        self.assertIn('MIGRATION_VERIFIED', self.migration)

    def test_local_schedules_preserve_collection_cadence_and_backup(self):
        self.assertIn('write("com.robotpokemon.kb.fixed", "fixed", {"Minute": 32})', self.installer)
        self.assertIn('write("com.robotpokemon.kb.sold", "sold", [{"Minute": 17}, {"Minute": 47}])', self.installer)
        self.assertIn('write("com.robotpokemon.kb.backup", "backup", {"Hour": 3, "Minute": 10})', self.installer)

    def test_local_runner_preserves_fixed_sold_and_backfill_contract(self):
        self.assertIn("--recent-records 100", self.runner)
        self.assertIn("--rotation-pages 2", self.runner)
        self.assertIn("--target-records 100", self.runner)
        self.assertIn("--live-gcc auction", self.runner)
        self.assertIn('v4_kb_sold_watermark.py" rotate', self.runner)
        self.assertIn("--max-scan-pages 200", self.runner)
        self.assertIn("--live-gcc sold", self.runner)
        self.assertIn("--max-records 20", self.runner)
        self.assertIn('v4_kb_sold_backfill.py" fetch', self.runner)
        self.assertIn("--max-page-probes 40", self.runner)
        self.assertIn("--max-scan-pages 20", self.runner)

    def test_cursor_commits_remain_after_successful_sidecar_ingest(self):
        fixed_ingest = self.runner.index('run_sidecar \\\n    --allow-live-read-only')
        fixed_commit = self.runner.index('v4_kb_fixed_hybrid.py" commit')
        self.assertLess(fixed_ingest, fixed_commit)
        sold_ingest = self.runner.index('run_sidecar --gcc-fixture "$sold_fixture"')
        sold_commit = self.runner.index('v4_kb_sold_watermark.py" commit')
        self.assertLess(sold_ingest, sold_commit)
        backfill_ingest = self.runner.index('run_sidecar --gcc-fixture "$backfill_fixture"')
        backfill_commit = self.runner.index('v4_kb_sold_backfill.py" commit')
        self.assertLess(backfill_ingest, backfill_commit)

    def test_backup_is_local_bounded_and_status_reports_migration(self):
        self.assertIn('robot_kb.postgres_backup dump', self.runner)
        self.assertIn('for path in files[7:]:', self.runner)
        self.assertIn('MIGRATION_VERIFIED', self.status)

    def test_cloud_collectors_remain_active_until_verified_cutover(self):
        cloud = Path('.github/workflows/robot-kb-cloud-shadow.yml').read_text(encoding='utf-8')
        sold = Path('.github/workflows/robot-kb-sold-shadow.yml').read_text(encoding='utf-8')
        ingest = Path('.github/workflows/v4-kb-shadow-ingest.yml').read_text(encoding='utf-8')
        self.assertIn('cron: "32 * * * *"', cloud)
        self.assertIn('cron: "17,47 * * * *"', sold)
        self.assertIn('workflow_run:', ingest)
        for text in (cloud, sold, ingest):
            self.assertIn('ROBOT_KB_DATABASE_URL', text)


if __name__ == "__main__":
    unittest.main()
