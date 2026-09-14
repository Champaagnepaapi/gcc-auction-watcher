from pathlib import Path
import unittest


class NoSecretTests(unittest.TestCase):
    def test_identity_module_contains_no_api_secret_storage(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        for token in ("api_key", "password", "cookie", "bearer "):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
