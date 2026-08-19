import unittest

from v4_global_rejection_diagnostics import (
    MAX_EXAMPLES_PER_REASON,
    ReasonTracker,
    reason_bucket,
    recommended_action,
    summarize_reason_buckets,
)


class GlobalRejectionDiagnosticsTests(unittest.TestCase):
    def test_identity_proof_reasons_stay_distinct_from_retrieval_gaps(self):
        self.assertEqual(reason_bucket("search_no_candidates"), "RETRIEVAL_GAP")
        self.assertEqual(reason_bucket("collector_number_unproven"), "METADATA_OR_IDENTITY_PROOF_GAP")
        self.assertEqual(reason_bucket("language_unproven"), "METADATA_OR_IDENTITY_PROOF_GAP")
        self.assertEqual(reason_bucket("sensitive_variant_unproven:master_ball"), "METADATA_OR_IDENTITY_PROOF_GAP")

    def test_non_actionable_and_technical_reasons_are_not_clean_no_match(self):
        self.assertEqual(reason_bucket("ongoing_auction"), "TRUE_INCOMPATIBLE_OR_NON_ACTIONABLE")
        self.assertEqual(reason_bucket("unavailable_or_sold"), "TRUE_INCOMPATIBLE_OR_NON_ACTIONABLE")
        self.assertEqual(reason_bucket("page_error"), "TECHNICAL_ERROR")

    def test_tracker_keeps_counts_and_bounded_public_examples(self):
        tracker = ReasonTracker("magi")
        label = "Pikachu | Test Set | 1/100 | Japanese | PSA 10"
        tracker.add_search(label, 4)
        for index in range(10):
            tracker.reject(
                label,
                "collector_number_unproven",
                title=f"candidate {index}",
                url=f"https://example.test/{index}",
            )
        exported = tracker.export()
        self.assertEqual(exported["candidates"], 4)
        self.assertEqual(exported["reject_reasons"]["collector_number_unproven"], 10)
        self.assertEqual(len(exported["examples"]["collector_number_unproven"]), MAX_EXAMPLES_PER_REASON)

    def test_zero_search_candidates_is_explicit(self):
        tracker = ReasonTracker("fanatics")
        tracker.add_search("seed", 0)
        exported = tracker.export()
        self.assertEqual(exported["reject_reasons"]["search_no_candidates"], 1)
        self.assertEqual(exported["reason_buckets"]["RETRIEVAL_GAP"], 1)

    def test_reason_bucket_summary_preserves_volume(self):
        summary = summarize_reason_buckets(
            {
                "search_no_candidates": 2,
                "language_unproven": 3,
                "page_error": 1,
                "ongoing_auction": 4,
            }
        )
        self.assertEqual(summary["RETRIEVAL_GAP"], 2)
        self.assertEqual(summary["METADATA_OR_IDENTITY_PROOF_GAP"], 3)
        self.assertEqual(summary["TECHNICAL_ERROR"], 1)
        self.assertEqual(summary["TRUE_INCOMPATIBLE_OR_NON_ACTIONABLE"], 4)

    def test_recommended_actions_never_suggest_relaxing_identity(self):
        action = recommended_action("search_no_candidates")
        self.assertIn("without relaxing", action)
        action = recommended_action("language_unproven")
        self.assertIn("do not infer", action)


if __name__ == "__main__":
    unittest.main()
