from pathlib import Path
import unittest


class ProviderOutageSemanticsTests(unittest.TestCase):
    def test_identity_module_does_not_convert_provider_failures(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertNotIn("EXTERNAL_CLEAN_NO_MATCH", source)
        self.assertNotIn("EXTERNAL_PROVIDER_ERROR", source)


if __name__ == "__main__":
    unittest.main()
