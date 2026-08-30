from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_variant_surface_probe as probe


def base_row(**updates):
    row = {
        "ulid": "01ABC",
        "listing_type": 1,
        "bid_price": 123456,
        "finished": 1,
        "end_date": "2026-08-01T21:00:00+09:00",
        "bid_payment_status": 5,
        "seller_payment_status": None,
        "canceled_at": None,
        "re_listed": 0,
        "re_listing_count": 0,
        "authentication_company_code": "P",
        "grade": "10.0",
        "language": "Japanese",
        "player": "Mario Pikachu",
        "variety": "Pokemon TCG: Japanese XY Promo Mario Pikachu Special Box",
        "variety_short": "XY-P Promo",
        "card_number": "#294/XY-P",
        "certificate_number": "123456789",
        "attribute": "Holo",
        "attribute2": "Promo",
        "attribute3": "",
    }
    row.update(updates)
    return row


class CardovaVariantSurfaceProbeTests(unittest.TestCase):
    def test_paid_row_preserves_structured_surfaces_without_promoting_them(self):
        row, reason = probe._project_paid_row(base_row())
        self.assertEqual(reason, "PAID_ROW_SURFACES_CAPTURED")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["provider_attribute"], "Holo")
        self.assertEqual(row["provider_attribute2"], "Promo")
        self.assertEqual(row["provider_attribute3"], "")
        self.assertTrue(row["japanese_structured_promo_candidate"])
        self.assertEqual(row["microvariant_status"], "UNPROVEN")
        self.assertFalse(row["sale_transaction_ready"])

    def test_non_paid_row_is_rejected_by_existing_payment_gate(self):
        row, reason = probe._project_paid_row(base_row(bid_payment_status=4))
        self.assertIsNone(row)
        self.assertEqual(reason, "PAYMENT_PENDING")

    def test_numeric_denominator_is_not_marked_as_structured_promo(self):
        row, reason = probe._project_paid_row(
            base_row(card_number="102/100", variety="Pokemon TCG: Japanese Set")
        )
        self.assertEqual(reason, "PAID_ROW_SURFACES_CAPTURED")
        assert row is not None
        self.assertFalse(row["japanese_structured_promo_candidate"])

    def test_summary_counts_nonempty_surfaces_without_interpreting_them(self):
        payload = probe.summarize_rows(
            [
                base_row(),
                base_row(
                    ulid="01DEF",
                    certificate_number="987654321",
                    card_number="145/BW-P",
                    attribute="",
                    attribute2="",
                    attribute3="Something",
                ),
            ],
            max_records=2,
        )
        self.assertEqual(payload["selected_paid_records"], 2)
        self.assertEqual(payload["japanese_structured_promo_candidate_count"], 2)
        self.assertEqual(
            payload["nonempty_surface_counts"],
            {"provider_attribute": 1, "provider_attribute2": 1, "provider_attribute3": 1},
        )

    def test_run_temporarily_extends_closed_projection_and_restores_it(self):
        original = probe.closed_probe.PUBLIC_FIELDS
        seen = {}

        def fake_run(_url, *, wait_ms):
            seen["wait_ms"] = wait_ms
            seen["fields"] = probe.closed_probe.PUBLIC_FIELDS
            return {
                "page_http_status": 200,
                "captured_api_http_status": 200,
                "target_api_responses_captured": 1,
                "rows": [base_row()],
            }

        real = probe.closed_probe.run_probe
        probe.closed_probe.run_probe = fake_run
        try:
            payload = probe.run("https://www.cardova.co.jp/en/auction/close", wait_ms=5000, max_records=1)
        finally:
            probe.closed_probe.run_probe = real

        self.assertEqual(seen["wait_ms"], 5000)
        self.assertTrue(probe.EXTRA_PUBLIC_FIELDS.issubset(seen["fields"]))
        self.assertIs(probe.closed_probe.PUBLIC_FIELDS, original)
        self.assertEqual(payload["selected_paid_records"], 1)

    def test_safety_summary_never_promotes_provider_surfaces(self):
        summary = probe.safe_summary()
        self.assertEqual(summary["extra_public_fields"], ["attribute", "attribute2", "attribute3"])
        for key in (
            "provider_fields_are_identity_proof",
            "fuzzy_matching",
            "translation_assumed",
            "microvariant_inferred",
            "robot_kb_write",
            "sale_transaction_stored",
            "sale_transaction_ready",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)


if __name__ == "__main__":
    unittest.main()
