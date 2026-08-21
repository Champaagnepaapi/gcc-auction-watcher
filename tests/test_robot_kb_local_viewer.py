from pathlib import Path
import unittest


class RobotKbLocalViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path("mac/robot-kb-local")
        cls.opener = (root / "Ouvrir Robot KB.command").read_text(encoding="utf-8")
        cls.viewer = (root / "robot_kb_viewer.py").read_text(encoding="utf-8")
        cls.readme = (root / "README.md").read_text(encoding="utf-8")

    def test_opener_uses_verified_local_runtime_and_keychain_without_printing_secret(self):
        self.assertIn('MIGRATION_MARKER="$DATA_ROOT/MIGRATION_VERIFIED"', self.opener)
        self.assertIn('PYTHON="$DATA_ROOT/venv/bin/python"', self.opener)
        self.assertIn('KEYCHAIN_SERVICE="RobotPokemonKB.local-postgres"', self.opener)
        self.assertIn("security find-generic-password", self.opener)
        self.assertIn('export ROBOT_KB_VIEWER_PASSWORD="$PASSWORD"', self.opener)
        self.assertIn("unset PASSWORD", self.opener)
        self.assertIn("unset ROBOT_KB_VIEWER_PASSWORD", self.opener)
        self.assertNotIn('echo "$PASSWORD"', self.opener)
        self.assertNotIn("ROBOT_KB_VIEWER_PASSWORD=", self.opener.split("export ROBOT_KB_VIEWER_PASSWORD", 1)[0])

    def test_viewer_is_loopback_only_and_enforces_read_only_postgres_session(self):
        self.assertIn('HOST = "127.0.0.1"', self.viewer)
        self.assertIn('DB_HOST = "127.0.0.1"', self.viewer)
        self.assertNotIn("0.0.0.0", self.viewer)
        self.assertIn("default_transaction_read_only=on", self.viewer)
        self.assertIn("statement_timeout=5000", self.viewer)
        self.assertIn('cur.execute("SHOW transaction_read_only")', self.viewer)
        self.assertIn('application_name="RobotKBViewer"', self.viewer)

    def test_viewer_has_no_write_http_surface_and_masks_raw_payload_bytes(self):
        self.assertIn("def do_GET(self)", self.viewer)
        self.assertNotIn("def do_POST", self.viewer)
        self.assertNotIn("def do_PUT", self.viewer)
        self.assertNotIn("def do_DELETE", self.viewer)
        self.assertNotIn(".commit()", self.viewer)
        self.assertIn('visible_columns = [name for name in columns if name != "payload_bytes"]', self.viewer)
        self.assertIn("les octets bruts ne sont jamais affichés", self.viewer)

    def test_viewer_exposes_card_search_sold_observations_and_table_browser(self):
        self.assertIn("def search_cards(", self.viewer)
        self.assertIn("def search_unresolved(", self.viewer)
        self.assertIn("def recent_sold(", self.viewer)
        self.assertIn("def observations(", self.viewer)
        self.assertIn("def table_list(", self.viewer)
        self.assertIn("def browse_table(", self.viewer)
        self.assertIn('href="/observations"', self.viewer)
        self.assertIn('href="/tables"', self.viewer)

    def test_local_readme_documents_one_click_read_only_viewer(self):
        self.assertIn("Ouvrir Robot KB.command", self.readme)
        self.assertIn("default_transaction_read_only=on", self.readme)
        self.assertIn("127.0.0.1", self.readme)
        self.assertIn("masque `source_payload.payload_bytes`", self.readme)


if __name__ == "__main__":
    unittest.main()
