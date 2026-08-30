from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_psa_identity_probe as probe


class CardovaPsaIdentityProbeTests(unittest.TestCase):
    def record(self, **updates):
        value = {
            "source": "cardova_public_past_auction",
            "source_native_record_id": "01TEST",
            "source_url": "https://www.cardova.co.jp/en/auction/card/01TEST",
            "provider_sale_status": "PAID_COMPLETED",
            "provider_sale_status_proven": True,
            "sale_evidence_ready": True,
            "currency": "JPY",
            "currency_proven": True,
            "final_bid_jpy": 5000000,
            "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
            "certification_number": "153603277",
            "card_name": "Mario Pikachu",
            "set_name": "Pokemon TCG: Japanese XY Promo Mario Pikachu Special Box",
            "collector_number": "#294/XY-P",
            "language": "Japanese",
            "grader": "PSA",
            "grade": "10",
        }
        value.update(updates)
        return value

    def item(self, **updates):
        value = {
            "Cert Number": "153603277",
            "Item Grade": "GEM MT 10",
            "Year": "2016",
            "Brand/Title": "POKEMON JAPANESE XY PROMO",
            "Subject": "MARIO PIKACHU",
            "Card Number": "294/XY-P",
            "Category": "TCG Cards",
            "Variety/Pedigree": "SPECIAL BOX",
        }
        value.update(updates)
        return value

    def canonical(self, status="EXACT", **updates):
        value = {
            "status": status,
            "reason": "TCGDEX_TEST_EXACT" if status == "EXACT" else "no match",
            "language_code": "ja",
            "card_id": "XY-P-294",
            "set_id": "XY-P",
            "set_name": "XY Promos",
            "local_id": "294",
        }
        value.update(updates)
        return SimpleNamespace(**value)

    def test_extract_item_information(self):
        body = """
        Cert Verification
        Item Information
        Cert Number
        153603277
        Item Grade
        GEM MT 10
        Year
        2016
        Brand/Title
        POKEMON JAPANESE XY PROMO
        Subject
        MARIO PIKACHU
        Card Number
        294/XY-P
        Category
        TCG Cards
        Variety/Pedigree
        SPECIAL BOX
        Set Registry
        ignored
        """
        item = probe.extract_item_information(body)
        self.assertEqual(item["Cert Number"], "153603277")
        self.assertEqual(item["Brand/Title"], "POKEMON JAPANESE XY PROMO")
        self.assertEqual(item["Subject"], "MARIO PIKACHU")
        self.assertEqual(item["Card Number"], "294/XY-P")
        self.assertNotIn("Set Registry", item)

    def test_surface_gate_requires_exact_cert_grade_name_number(self):
        ok, reason = probe._cardova_psa_surface_gate(self.record(), self.item())
        self.assertTrue(ok)
        self.assertEqual(reason, "PSA_SURFACE_EXACT")

        cases = (
            (self.item(**{"Cert Number": "99999999"}), "PSA_CERT_CONFLICT"),
            (self.item(**{"Item Grade": "MINT 9"}), "PSA_GRADE_CONFLICT"),
            (self.item(**{"Subject": "LUIGI PIKACHU"}), "PSA_SUBJECT_CONFLICT"),
            (self.item(**{"Card Number": "293/XY-P"}), "PSA_CARD_NUMBER_CONFLICT"),
            (self.item(**{"Brand/Title": ""}), "PSA_BRAND_TITLE_MISSING"),
            (self.item(**{"Category": "BASEBALL CARDS"}), "PSA_CATEGORY_NOT_POKEMON_TCG"),
        )
        for item, expected in cases:
            with self.subTest(expected=expected):
                ok, reason = probe._cardova_psa_surface_gate(self.record(), item)
                self.assertFalse(ok)
                self.assertEqual(reason, expected)

    def test_resolve_item_reuses_psa_surface_then_requires_tcgdex_and_microvariant(self):
        seen = {}

        def resolver(identity):
            seen["identity"] = identity
            return None, self.canonical()

        def micro(identity, canonical):
            return True, "EXACT", "TEST_EXACT", {"finish": "holo"}

        row, reason = probe.resolve_item(
            self.record(), self.item(), resolver=resolver, microvariant_checker=micro
        )
        self.assertEqual(reason, "EXACT_PSA_TCGDEX_MICROVARIANT")
        self.assertIsNotNone(row)
        self.assertEqual(seen["identity"].name, "MARIO PIKACHU")
        self.assertEqual(seen["identity"].set_name, "POKEMON JAPANESE XY PROMO")
        self.assertEqual(seen["identity"].number, "294/XY-P")
        self.assertEqual(row["tcgdex_card_id"], "XY-P-294")
        self.assertTrue(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])
        self.assertFalse(row["payment_completed_at_proven"])

    def test_tcgdex_no_match_stays_blocked(self):
        row, reason = probe.resolve_item(
            self.record(),
            self.item(),
            resolver=lambda identity: (None, self.canonical(status="NO_MATCH")),
        )
        self.assertIsNone(row)
        self.assertTrue(reason.startswith("TCGDEX_NO_MATCH"))

    def test_microvariant_failure_never_becomes_ready(self):
        row, reason = probe.resolve_item(
            self.record(),
            self.item(),
            resolver=lambda identity: (None, self.canonical()),
            microvariant_checker=lambda identity, canonical: (
                False,
                "AMBIGUOUS",
                "multiple finishes",
                {},
            ),
        )
        self.assertIsNotNone(row)
        self.assertTrue(reason.startswith("MICROVARIANT_AMBIGUOUS"))
        self.assertFalse(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_run_records_opens_psa_circuit_on_403(self):
        original = probe.paid_identity.install_tcgdex_stack_once
        probe.paid_identity.install_tcgdex_stack_once = lambda: None
        try:
            payload = probe.run_records(
                [self.record(source_native_record_id="a"), self.record(source_native_record_id="b")],
                fetcher=lambda record: (None, "PSA_HTTP_403"),
                max_records=2,
            )
        finally:
            probe.paid_identity.install_tcgdex_stack_once = original
        self.assertTrue(payload["psa_circuit_open"])
        self.assertEqual(payload["blocked"].get("PSA_HTTP_403"), 1)
        self.assertEqual(payload["blocked"].get("PSA_CIRCUIT_OPEN"), 1)

    def test_safety_summary_is_strictly_read_only(self):
        summary = probe.safe_summary()
        for key in (
            "robot_kb_write",
            "sale_transaction_ready",
            "sale_transaction_stored",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
            "fuzzy_matching",
            "translation_assumed",
            "provider_alias_table_added",
        ):
            self.assertIs(summary[key], False, key)
        self.assertTrue(summary["psa_cert_exact_required"])
        self.assertTrue(summary["tcgdex_exact_required"])
        self.assertTrue(summary["microvariant_exact_required"])


if __name__ == "__main__":
    unittest.main()
