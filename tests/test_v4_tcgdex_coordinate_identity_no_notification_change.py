from pathlib import Path
import unittest


class NoNotificationChangeTests(unittest.TestCase):
    def test_identity_module_does_not_send_notifications(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("ntfy", source)
        self.assertNotIn("notify(", source)


if __name__ == "__main__":
    unittest.main()
