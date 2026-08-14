from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_final_alert_notification as final_notify


class _OkResponse:
    def raise_for_status(self) -> None:
        return None


class FinalAlertIdentityTests(unittest.TestCase):
    def _lot(self, *, body: str) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/test-shaymin",
            title="Aucune note plus élevée #10/181",
            current_price=18.0,
            source_type="auction",
            end_text="4 min",
            minutes_to_end=4,
            body=body,
            grader="CCC",
            grade="9.5",
            card_set="Duo de Choc",
            card_number="10/181",
            language="French",
            year=2019,
        )

    def test_final_alert_prefers_personnage_over_bad_page_heading(self) -> None:
        lot = self._lot(
            body=(
                "Description\nArticle\nPersonnage\nShaymin\nFrench\n"
                "Catégorie\nPokemon\nLangue\nFrench\nSérie\nDuo de Choc\n"
                "Référence\n#10/181\nAnnée de fabrication\n2019\n"
            )
        )
        with patch.object(final_notify.watcher, "NTFY_TOPIC", "test-topic"), patch.object(
            final_notify.requests, "post", return_value=_OkResponse()
        ) as post:
            self.assertTrue(final_notify.send_identity_rich_final_notification(lot, 19.85))

        payload = post.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("Shaymin #10/181", payload)
        self.assertIn("Duo de Choc · 2019 · French", payload)
        self.assertIn("CCC 9.5", payload)
        self.assertIn("Prix actuel : 18.00 €", payload)
        self.assertIn("Prix max conseillé : 19.85 €", payload)
        self.assertNotIn("Aucune note plus élevée", payload)

    def test_bad_heading_without_explicit_name_falls_back_safely(self) -> None:
        lot = self._lot(body="Référence\n#10/181\nLangue\nFrench\n")
        lines = final_notify._identity_lines(lot)
        self.assertEqual(lines[0], "Carte GCC #10/181")
        self.assertNotIn("Aucune note plus élevée", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
