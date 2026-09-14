from pathlib import Path
import unittest


class NameFilteredRuntimeWiringTests(unittest.TestCase):
    def test_merged_260_recovery_is_installed_after_unique_coordinate(self) -> None:
        source = Path("run_watcher_multimarket.py").read_text(encoding="utf-8")
        unique = "install_v4_tcgdex_unique_coordinate_fallback()"
        filtered = "install_v4_tcgdex_name_filtered_coordinate_recovery()"
        self.assertIn(unique, source)
        self.assertIn(filtered, source)
        self.assertGreater(source.index(filtered), source.index(unique))


if __name__ == "__main__":
    unittest.main()
