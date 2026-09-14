from pathlib import Path
import unittest


class NoGradeChangeTests(unittest.TestCase):
    def test_identity_module_does_not_touch_grader_or_grade(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertNotIn("PSA_", source)
        self.assertNotIn("target_grade", source)


if __name__ == "__main__":
    unittest.main()
