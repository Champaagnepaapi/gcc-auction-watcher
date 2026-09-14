import unittest
import v4_tcgdex_coordinate_authoritative_name as target

class ImportTests(unittest.TestCase):
    def test_installer_exists(self):
        self.assertTrue(callable(target.install_v4_tcgdex_coordinate_authoritative_name))

if __name__ == "__main__":
    unittest.main()
