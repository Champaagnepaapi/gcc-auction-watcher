from pathlib import Path
import unittest


class SoldWorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.runner = Path("mac/robot-kb-local/robot_kb_local_runner.sh").read_text(
            encoding="utf-8"
        )
        self.installer = Path("mac/robot-kb-local/Installer Robot KB Local.command").read_text(
            encoding="utf-8"
        )
        self.cloud = Path(".github/workflows/robot-kb-cloud-shadow.yml").read_text(
            encoding="utf-8"
        )
        self.sold_cloud = Path(".github/workflows/robot-kb-sold-shadow.yml").read_text(
            encoding="utf-8"
        )
        self.v4_ingest = Path(".github/workflows/v4-kb-shadow-ingest.yml").read_text(
            encoding="utf-8"
        )

    def test_sold_is_split_to_independent_30_minute_local_lane(self):
        self.assertIn('write("com.robotpokemon.kb.fixed", "fixed", {"Minute": 32})', self.installer)
        self.assertIn(
            'write("com.robotpokemon.kb.sold", "sold", [{"Minute": 17}, {"Minute": 47}])',
            self.installer,
        )
        self.assertIn('write("com.robotpokemon.kb.backup", "backup", {"Hour": 3, "Minute": 10})', self.installer)
        self.assertIn('LOCK_DIR="$DATA_ROOT/locks/collector.lock"', self.runner)
        self.assertIn("acquire_lock", self.runner)

    def test_fixed_lane_keeps_hybrid_fixed_and_auction_without_sold_work(self):
        fixed_start = self.runner.index("run_fixed()")
        sold_start = self.runner.index("run_sold()")
        fixed = self.runner[fixed_start:sold_start]
        self.assertIn("--recent-records 100", fixed)
        self.assertIn("--rotation-pages 2", fixed)
        self.assertIn("--target-records 100", fixed)
        self.assertIn("v4_kb_fixed_hybrid.py\" fetch", fixed)
        self.assertIn("v4_kb_fixed_hybrid.py\" commit", fixed)
        self.assertIn("--live-gcc auction", fixed)
        self.assertNotIn("v4_kb_sold_watermark.py", fixed)
        self.assertNotIn("--live-gcc sold", fixed)

    def test_sold_lane_wires_lossless_watermark_and_400_cap(self):
        self.assertIn('sold_state="$STATE_DIR/v4_kb_sold_watermark_state.json"', self.runner)
        self.assertIn('bootstrap_since="2026-08-15T03:00:00Z"', self.runner)
        self.assertIn('v4_kb_sold_watermark.py" rotate', self.runner)
        self.assertIn("--max-records 400", self.runner)
        self.assertIn('run_sidecar --gcc-fixture "$sold_fixture" --observed-at "$observed_at"', self.runner)
        self.assertIn('v4_kb_sold_watermark.py" commit', self.runner)

        fetch = self.runner.index('v4_kb_sold_watermark.py" rotate')
        ingest = self.runner.index('run_sidecar --gcc-fixture "$sold_fixture"')
        sold_commit = self.runner.index('v4_kb_sold_watermark.py" commit')
        self.assertLess(fetch, ingest)
        self.assertLess(ingest, sold_commit)

    def test_historical_backfill_is_bounded_get_only_and_committed_after_ingest(self):
        self.assertIn('backfill_state="$STATE_DIR/v4_kb_sold_backfill_state.json"', self.runner)
        self.assertIn('v4_kb_sold_backfill.py" fetch', self.runner)
        self.assertIn('--bootstrap-before "$bootstrap_since"', self.runner)
        self.assertGreaterEqual(self.runner.count("--max-records 400"), 2)
        self.assertIn("--max-page-probes 40", self.runner)
        self.assertIn("--max-scan-pages 20", self.runner)
        self.assertIn('run_sidecar --gcc-fixture "$backfill_fixture"', self.runner)
        self.assertIn('v4_kb_sold_backfill.py" commit', self.runner)

        fetch = self.runner.index('v4_kb_sold_backfill.py" fetch')
        ingest = self.runner.index('run_sidecar --gcc-fixture "$backfill_fixture"')
        commit = self.runner.index('v4_kb_sold_backfill.py" commit')
        self.assertLess(fetch, ingest)
        self.assertLess(ingest, commit)

    def test_validated_sidecar_pin_and_small_live_sold_overlap_are_preserved(self):
        self.assertIn("1d06fe33b6fc640657255e15a8d17251aa02b6ce", self.installer)
        self.assertIn("--live-gcc sold", self.runner)
        self.assertIn("--max-records 20", self.runner)
        self.assertIn("same read-only overlap safety-net", self.runner)

    def test_cloud_neon_writers_are_retired_without_creating_parallel_collectors(self):
        for text in (self.cloud, self.sold_cloud, self.v4_ingest):
            self.assertNotIn("ROBOT_KB_DATABASE_URL: ${{ secrets", text)
        self.assertNotIn("schedule:", self.sold_cloud)
        self.assertNotIn("workflow_run:", self.v4_ingest)
        self.assertIn("local Mac PostgreSQL", self.sold_cloud)
        self.assertIn("local Mac PostgreSQL", self.v4_ingest)


if __name__ == "__main__":
    unittest.main()
