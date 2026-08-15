from __future__ import annotations

import unittest

import v4_focus_cert_router as focus
import v4_mislisted_slab_hunter as hunter


class FocusCertRouterTests(unittest.TestCase):
    def test_psa_item_grade_layout(self) -> None:
        text = """
        Certification Number
        131216316
        Item Grade
        GEM MT 10
        Card Number
        166
        """
        cert = focus.parse_psa_verified_text(text, "131216316")
        self.assertEqual(cert.status, "OK")
        self.assertEqual(cert.grade, 10.0)
        self.assertEqual(cert.grader, "PSA")

    def test_psa_wrong_cert_fails_closed(self) -> None:
        cert = focus.parse_psa_verified_text(
            "Certification Number\n999999999\nItem Grade\nGEM MT 10",
            "131216316",
        )
        self.assertEqual(cert.status, hunter.CERT_UNAVAILABLE)
        self.assertIsNone(cert.grade)

    def test_ccc_live_layout_uses_overall_before_subgrades(self) -> None:
        text = """
        Numéro de certification
        544340143
        Date de la certification
        Mar 2026
        Jeu
        9
        Note Centrage
        9.5
        Note Coins
        9
        Note Côtés
        9.5
        Note Surface
        8.5
        """
        cert = focus.parse_ccc_verified_text(text, "544340143")
        self.assertEqual(cert.status, "OK")
        self.assertEqual(cert.grade, 9.0)
        self.assertEqual(cert.grader, "CCC")

    def test_ccc_subgrades_alone_never_become_overall_grade(self) -> None:
        text = """
        Numéro de certification
        544340143
        Note Centrage
        9.5
        Note Coins
        9
        Note Côtés
        9.5
        Note Surface
        8.5
        """
        cert = focus.parse_ccc_verified_text(text, "544340143")
        self.assertNotEqual(cert.status, "OK")
        self.assertIsNone(cert.grade)


if __name__ == "__main__":
    unittest.main()
