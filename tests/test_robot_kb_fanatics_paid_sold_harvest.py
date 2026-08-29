from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_fanatics_paid_sold_harvest.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_fanatics_paid_sold_harvest", MODULE_PATH)
assert SPEC and SPEC.loader
harvest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harvest
SPEC.loader.exec_module(harvest)


def live_shape(**overrides):
    row = {
        "auctionType": "PREMIER",
        "category": "Pokémon",
        "grade": 10.0,
        "gradingService": "PSA",
        "id": "PREMIER17603",
        "isComplete": True,
        "listingUuid": "995c1bb4-fe03-11f0-92aa-0af9eda8a431",
        "paymentStatus": "Paid",
        "purchasePrice": "528000.00",
        "serial": "05302786",
        "soldDate": "2026-02-19T22:01:40.000 PST",
        "title": "1999 Pokemon English Base Set Shadowless 1st Edition Holo Charizard #4 PSA 10 GEM MINT",
        "year": 1999,
    }
    row.update(overrides)
    return row


class ProviderSemanticsTests(unittest.TestCase):
    def test_unpaid_is_blocked_even_when_provider_marks_complete(self):
        row, reason = harvest.precheck_row(live_shape(paymentStatus="Unpaid", isComplete=True))
        self.assertIsNone(row)
        self.assertEqual(reason, "PAYMENT_NOT_PAID")

    def test_paid_complete_individual_psa_card_passes_precheck(self):
        row, reason = harvest.precheck_row(live_shape())
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(reason, "PAID_COMPLETE_INDIVIDUAL_CARD")
        self.assertEqual(row.purchase_price_minor, 52_800_000)
        self.assertEqual(row.payment_status, "PAID")
        self.assertEqual(row.grade, "10")
        self.assertEqual(row.serial, "05302786")
        self.assertEqual(row.sold_at_utc, "2026-02-20T06:01:40+00:00")

    def test_pdt_timestamp_is_converted_to_utc(self):
        self.assertEqual(
            harvest.parse_sold_at("2026-05-22T00:11:07.000 PDT"),
            "2026-05-22T07:11:07+00:00",
        )

    def test_sealed_or_wax_product_is_blocked_even_if_graded_fields_exist(self):
        raw = live_shape(
            title="1999 Pokemon English Base Set Booster Box Sealed PSA 10",
            category="Wax Collectible Card Games",
        )
        row, reason = harvest.precheck_row(raw)
        self.assertIsNone(row)
        self.assertEqual(reason, "NOT_SUPPORTED_INDIVIDUAL_PSA_CARD")

    def test_non_psa_and_unsupported_grade_are_blocked(self):
        row, reason = harvest.precheck_row(live_shape(gradingService="CGC"))
        self.assertIsNone(row)
        self.assertEqual(reason, "NOT_SUPPORTED_INDIVIDUAL_PSA_CARD")
        row, reason = harvest.precheck_row(live_shape(grade=7.0))
        self.assertIsNone(row)
        self.assertEqual(reason, "NOT_SUPPORTED_INDIVIDUAL_PSA_CARD")


class ExactIdentityTests(unittest.TestCase):
    def _paid_row(self):
        row, reason = harvest.precheck_row(live_shape())
        self.assertEqual(reason, "PAID_COMPLETE_INDIVIDUAL_CARD")
        assert row is not None
        return row

    @staticmethod
    def _resolution(*, grade="10", year=1999):
        identity = SimpleNamespace(
            name="Charizard",
            set_name="Base Set",
            number="4/102",
            language="en",
            grader="PSA",
            grade=grade,
            edition="First Edition",
            finish="Holo",
            variant="Shadowless",
        )
        coordinate = SimpleNamespace(year=year)
        return SimpleNamespace(
            status="EXACT",
            reason="FANATICS_TCGDEX_SET_EXACT",
            identity=identity,
            coordinate=coordinate,
        )

    def test_exact_paid_sale_still_blocks_robot_kb_write_until_currency_is_proven(self):
        row = self._paid_row()
        exact, reason = harvest.resolve_exact_sale(
            row,
            identity_resolver=lambda *_args, **_kwargs: self._resolution(),
            microvariant_checker=lambda _identity: (
                True,
                "EXACT",
                "unique compatible detailed variant",
                "base1-4",
            ),
        )
        self.assertEqual(reason, "EXACT_PAID_SALE_CURRENCY_UNPROVEN")
        self.assertIsNotNone(exact)
        assert exact is not None
        self.assertTrue(exact.paid_sale_status_proven)
        self.assertTrue(exact.provider_purchase_price_proven)
        self.assertEqual(exact.tcgdex_card_id, "base1-4")
        self.assertFalse(exact.currency_proven)
        self.assertEqual(exact.currency, "")
        self.assertFalse(exact.robot_kb_sale_ready)

    def test_provider_grade_conflict_blocks_exact_identity(self):
        exact, reason = harvest.resolve_exact_sale(
            self._paid_row(),
            identity_resolver=lambda *_args, **_kwargs: self._resolution(grade="9"),
            microvariant_checker=lambda _identity: (True, "EXACT", "ok", "base1-4"),
        )
        self.assertIsNone(exact)
        self.assertEqual(reason, "IDENTITY_GRADE_CONFLICT")

    def test_provider_year_conflict_blocks_exact_identity(self):
        exact, reason = harvest.resolve_exact_sale(
            self._paid_row(),
            identity_resolver=lambda *_args, **_kwargs: self._resolution(year=2000),
            microvariant_checker=lambda _identity: (True, "EXACT", "ok", "base1-4"),
        )
        self.assertIsNone(exact)
        self.assertEqual(reason, "IDENTITY_YEAR_CONFLICT")

    def test_microvariant_must_be_exact_not_merely_macro_identity(self):
        exact, reason = harvest.resolve_exact_sale(
            self._paid_row(),
            identity_resolver=lambda *_args, **_kwargs: self._resolution(),
            microvariant_checker=lambda _identity: (
                False,
                "AMBIGUOUS",
                "multiple material detailed variants remain",
                "base1-4",
            ),
        )
        self.assertIsNone(exact)
        self.assertIn("MICROVARIANT_AMBIGUOUS", reason)


class PublicApiContractTests(unittest.TestCase):
    def test_fetch_uses_observed_public_endpoint_without_auth(self):
        captured = {}

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"_embedded": {"SalesRecords": []}, "page": {"totalPages": 1}}

        def fake_get(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return Response()

        payload = harvest.fetch_page(
            query="Pokemon Japanese PSA 10",
            page=0,
            size=20,
            timeout_seconds=10,
            get=fake_get,
        )
        self.assertEqual(captured["url"], harvest.API_URL)
        self.assertEqual(captured["params"]["title"], "Pokemon Japanese PSA 10")
        self.assertEqual(captured["params"]["marketplaceSource"], "bo")
        self.assertEqual(captured["params"]["sort"], "purchasePrice,desc")
        headers = captured["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)
        self.assertEqual(harvest._embedded_rows(payload), [])

    def test_summary_is_read_only_and_currency_fail_closed(self):
        summary = harvest.safe_summary()
        self.assertTrue(summary["public_anonymous_api"])
        self.assertEqual(summary["payment_status_required"], "PAID")
        self.assertFalse(summary["currency_semantics_proven"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["sale_transaction_stored"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])

    def test_script_has_no_robot_kb_database_or_secret_dependency(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("ROBOT_KB_DATABASE_URL", text)
        self.assertNotIn("find-generic-password", text)
        self.assertNotIn("KnowledgeBase(", text)
        self.assertNotIn("Authorization\":", text)


if __name__ == "__main__":
    unittest.main()
