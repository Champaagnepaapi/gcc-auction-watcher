from pathlib import Path
import unittest


class SoldWorkflowWiringTests(unittest.TestCase):
    def test_cloud_shadow_wires_lossless_sold_state_and_fixture(self):
        content = Path(".github/workflows/robot-kb-cloud-shadow.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("timeout-minutes: 45", content)
        self.assertIn("SOLD_STATE: v4_kb_sold_watermark_state.json", content)
        self.assertIn("SOLD_BOOTSTRAP_SINCE: \"2026-08-15T03:00:00Z\"", content)
        self.assertIn("v4_kb_sold_watermark.py rotate", content)
        self.assertIn("--max-records 400", content)
        self.assertIn('--gcc-fixture "../$SOLD_FIXTURE"', content)
        self.assertIn("v4_kb_sold_watermark.py commit", content)
        self.assertIn("v4-kb-sold-watermark-${{ github.run_id }}", content)

        ingest = content.index("Ingest fixed + SOLD fixtures and live auction")
        sold_commit = content.index("Commit SOLD watermark/backlog only after successful ingest")
        sold_save = content.index("Save durable SOLD watermark/backlog state")
        self.assertLess(ingest, sold_commit)
        self.assertLess(sold_commit, sold_save)

    def test_validated_sidecar_pin_and_small_live_sold_overlap_are_preserved(self):
        content = Path(".github/workflows/robot-kb-cloud-shadow.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("1d06fe33b6fc640657255e15a8d17251aa02b6ce", content)
        self.assertIn("--live-gcc auction", content)
        self.assertIn("Fresh SOLD overlap safety-net", content)
        self.assertIn("--live-gcc sold", content)
        self.assertIn("--max-records 20", content)


if __name__ == "__main__":
    unittest.main()
