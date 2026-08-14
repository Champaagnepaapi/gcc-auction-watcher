from __future__ import annotations

import unittest

from v5.source_scout_entrypoint import _candidate_indices, _finish_from_variants


class SourceScoutEntrypointTests(unittest.TestCase):
    def test_finish_requires_explicit_true(self) -> None:
        self.assertEqual(_finish_from_variants({"holo": True, "reverse": False}), "Holo")
        self.assertEqual(_finish_from_variants({"holo": False, "reverse": True}), "Reverse Holo")
        self.assertIsNone(_finish_from_variants({"holo": False, "reverse": False}))
        self.assertIsNone(_finish_from_variants({}))
        self.assertIsNone(_finish_from_variants(None))

    def test_candidate_indices_are_bounded_unique_and_deterministic(self) -> None:
        self.assertEqual(_candidate_indices(0), ())
        self.assertEqual(_candidate_indices(1), (0,))
        values = _candidate_indices(20)
        self.assertEqual(values, (0, 5, 10, 15, 19))
        self.assertEqual(len(values), len(set(values)))
        self.assertTrue(all(0 <= value < 20 for value in values))


if __name__ == "__main__":
    unittest.main()
