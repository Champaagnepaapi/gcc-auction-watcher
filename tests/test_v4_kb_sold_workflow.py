from pathlib import Path
import unittest


class SoldWorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.hourly = Path(".github/workflows/robot-kb-cloud-shadow.yml").read_text(
            encoding="utf-8"
        )
        self.sold = Path(".github/workflows/robot-kb-sold-shadow.yml").read_text(
            encoding="utf-8"
        )

    def test_sold_is_split_to_independent_30_minute_lane(self):
        self.assertIn('cron: "17,47 * * * *"', self.sold)
        self.assertIn('cron: "32 * * * *"', self.hourly)
        self.assertIn("group: robot-kb-neon-shadow", self.sold)
        self.assertIn("group: robot-kb-neon-shadow", self.hourly)
        self.assertIn("cancel-in-progress: false", self.sold)
        self.assertIn("cancel-in-progress: false", self.hourly)
        self.assertIn("timeout-minutes: 45", self.sold)
        self.assertIn("timeout-minutes: 45", self.hourly)

    def test_hourly_lane_keeps_fixed_and_auction_without_sold_work(self):
        self.assertIn("Fetch 4-page fixed backup rotation batch", self.hourly)
        self.assertIn("--pages 4", self.hourly)
        self.assertIn("--live-gcc auction", self.hourly)
        self.assertNotIn("SOLD_STATE:", self.hourly)
        self.assertNotIn("v4_kb_sold_watermark.py", self.hourly)
        self.assertNotIn("--live-gcc sold", self.hourly)

    def test_sold_lane_wires_lossless_watermark_and_400_cap(self):
        self.assertIn("SOLD_STATE: v4_kb_sold_watermark_state.json", self.sold)
        self.assertIn("SOLD_BOOTSTRAP_SINCE: \"2026-08-15T03:00:00Z\"", self.sold)
        self.assertIn("v4_kb_sold_watermark.py rotate", self.sold)
        self.assertIn("--max-records 400", self.sold)
        self.assertIn('--gcc-fixture "../$SOLD_FIXTURE"', self.sold)
        self.assertIn("v4_kb_sold_watermark.py commit", self.sold)
        self.assertIn("v4-kb-sold-watermark-${{ github.run_id }}", self.sold)

        fetch = self.sold.index("Fetch lossless SOLD catch-up slice")
        ingest = self.sold.index("Ingest proven SOLD fixture")
        sold_commit = self.sold.index("Commit SOLD watermark/backlog only after successful ingest")
        sold_save = self.sold.index("Save durable SOLD watermark/backlog state")
        self.assertLess(fetch, ingest)
        self.assertLess(ingest, sold_commit)
        self.assertLess(sold_commit, sold_save)

    def test_validated_sidecar_pin_and_small_live_sold_overlap_are_preserved(self):
        self.assertIn("1d06fe33b6fc640657255e15a8d17251aa02b6ce", self.sold)
        self.assertIn("Fresh SOLD overlap safety-net", self.sold)
        self.assertIn("--live-gcc sold", self.sold)
        self.assertIn("--max-records 20", self.sold)


if __name__ == "__main__":
    unittest.main()
