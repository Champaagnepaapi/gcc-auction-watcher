import unittest
from types import SimpleNamespace

from v4_ppt_shadow_grader_guard import (
    SUPPORTED_PPT_GRADERS,
    guarded_fetch_snapshot,
    is_supported_ppt_grader,
    prioritize_shadow_candidates,
)


class PptShadowGraderGuardTests(unittest.TestCase):
    def test_supported_grader_contract(self):
        self.assertEqual(SUPPORTED_PPT_GRADERS, ("PSA", "BGS", "CGC", "SGC"))
        for grader in SUPPORTED_PPT_GRADERS:
            self.assertTrue(is_supported_ppt_grader(grader))
        for grader in ("PCA", "CCC", "ACE", "TAG", ""):
            self.assertFalse(is_supported_ppt_grader(grader))

    def test_unsupported_grader_never_calls_provider(self):
        calls = []

        def original(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("provider must not be called")

        result = guarded_fetch_snapshot(
            original,
            object(),
            "PCA",
            "9.5",
            "secret-not-used",
            object(),
            object(),
            10.0,
        )
        self.assertEqual(calls, [])
        self.assertEqual(result[0], "UNSUPPORTED_GRADER")
        self.assertEqual(result[3], "PPT_GRADER_UNSUPPORTED:PCA")

    def test_supported_candidates_are_shadow_prioritized_only(self):
        def candidate(grader, label):
            return SimpleNamespace(lot=SimpleNamespace(grader=grader), label=label)

        rows = [
            candidate("PCA", "pca"),
            candidate("SGC", "sgc"),
            candidate("CGC", "cgc"),
            candidate("PSA", "psa"),
            candidate("BGS", "bgs"),
            candidate("CCC", "ccc"),
        ]
        ordered = prioritize_shadow_candidates(rows)
        self.assertEqual(
            [row.label for row in ordered],
            ["psa", "bgs", "cgc", "sgc", "pca", "ccc"],
        )
        self.assertEqual([row.label for row in rows], ["pca", "sgc", "cgc", "psa", "bgs", "ccc"])


if __name__ == "__main__":
    unittest.main()
