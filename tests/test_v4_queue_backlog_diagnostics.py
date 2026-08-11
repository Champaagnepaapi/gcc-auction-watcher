import unittest

import run_watcher_safe
import watcher


class FixedQueueBacklogDiagnosticTests(unittest.TestCase):
    def test_stale_backlog_is_counted_without_downgrading_coverage(self):
        queue = watcher.FixedEconomicQueueDiagnostics(processing_budget=120)
        queue.initialized = True

        for index in range(227):
            queue.register(f"stale-{index}", watcher.QUEUE_P3_STALE)
        for index in range(120):
            queue.record_processed(f"stale-{index}")

        self.assertEqual(queue.coverage_backlog, 0)
        self.assertEqual(queue.queued_backlog, 107)
        self.assertEqual(queue.status, watcher.COVERAGE_COMPLETE)

        run_watcher_safe.install_fixed_queue_backlog_diagnostics()

        self.assertEqual(queue.estimated_backlog_runs, 1)
        summary = watcher.format_fixed_economic_queue(queue)
        self.assertIn("stale backlog: 107", summary)
        self.assertIn("estimated backlog runs remaining: 1", summary)
        self.assertIn("economic coverage: COMPLETE", summary)

    def test_backlog_run_estimate_uses_total_queue_and_budget(self):
        queue = watcher.FixedEconomicQueueDiagnostics(processing_budget=120)
        queue.initialized = True

        for index in range(241):
            queue.register(f"stale-{index}", watcher.QUEUE_P3_STALE)

        run_watcher_safe.install_fixed_queue_backlog_diagnostics()

        self.assertEqual(queue.queued_backlog, 241)
        self.assertEqual(queue.estimated_backlog_runs, 3)


if __name__ == "__main__":
    unittest.main()
