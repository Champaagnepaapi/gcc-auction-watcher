from pathlib import Path
import unittest


class NoBudgetChangeTests(unittest.TestCase):
    def test_identity_module_does_not_define_request_budgets(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("max_requests_per_run", source)
        self.assertNotIn("requestbudget", source)


if __name__ == "__main__":
    unittest.main()
