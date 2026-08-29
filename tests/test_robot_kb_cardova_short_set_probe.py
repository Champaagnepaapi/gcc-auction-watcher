import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_short_set_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_short_set_probe", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def paid_record(**updates):
    row = {
        "source": "cardova_public_past_auction",
        "source_native_record_id": "01CARDOVA",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "sale_evidence_ready": True,
        "currency": "JPY",
        "currency_proven": True,
        "final_bid_jpy": 5250000,
        "auction_end_at_utc": "2026-08-02T12:56:00+00:00",
        "grader": "PSA",
        "grade": "10",
        "certification_number": "153603277",
        "language": "Japanese",
        "card_name": "Mario Pikachu",
        "set_name": "Pokemon TCG: Japanese XY Promo Mario Pikachu Special Box",
        "provider_set_name_short": "Special Box",
        "collector_number": "#294/XY-P",
    }
    row.update(updates)
    return row


def exact_card():
    return SimpleNamespace(
        status="EXACT",
        reason="TCGDEX_EXACT_SET_LOCALID",
        language_code="ja",
        set_id="XY-P",
        card_id="XY-P-294",
        local_id="294",
    )


class CardovaShortSetProbeTests(unittest.TestCase):
    def test_missing_short_set_is_blocked(self):
        row, reason = MOD.probe_record(paid_record(provider_set_name_short=""))
        self.assertIsNone(row)
        self.assertEqual(reason, "SHORT_SET_MISSING")

    def test_exact_short_set_and_coordinate_can_recover_macro_identity(self):
        original_set = MOD._exact_set_id
        original_fetch = MOD.generalized._fetch_coordinate
        original_micro = MOD.paid_identity._microvariant_check
        try:
            MOD._exact_set_id = lambda language, short: ("XY-P", "EXACT_SHORT_SET")
            MOD.generalized._fetch_coordinate = lambda *args, **kwargs: exact_card()
            MOD.paid_identity._microvariant_check = lambda identity, card: (
                True,
                "EXACT",
                "unique compatible detailed variant",
                {"finish": "holo"},
            )
            row, reason = MOD.probe_record(paid_record())
        finally:
            MOD._exact_set_id = original_set
            MOD.generalized._fetch_coordinate = original_fetch
            MOD.paid_identity._microvariant_check = original_micro

        self.assertEqual(reason, "EXACT_SHORT_SET_COORDINATE")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["tcgdex_set_id"], "XY-P")
        self.assertEqual(row["tcgdex_card_id"], "XY-P-294")
        self.assertTrue(row["microvariant_exact"])
        self.assertTrue(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_absent_exact_short_set_remains_blocked(self):
        original = MOD._exact_set_id
        try:
            MOD._exact_set_id = lambda language, short: ("", "SHORT_SET_NOT_IN_TCGDEX")
            row, reason = MOD.probe_record(paid_record())
        finally:
            MOD._exact_set_id = original
        self.assertIsNone(row)
        self.assertEqual(reason, "SHORT_SET_NOT_IN_TCGDEX")

    def test_non_exact_coordinate_remains_blocked(self):
        original_set = MOD._exact_set_id
        original_fetch = MOD.generalized._fetch_coordinate
        try:
            MOD._exact_set_id = lambda language, short: ("XY-P", "EXACT_SHORT_SET")
            MOD.generalized._fetch_coordinate = lambda *args, **kwargs: SimpleNamespace(
                status="ERROR", reason="test failure"
            )
            row, reason = MOD.probe_record(paid_record())
        finally:
            MOD._exact_set_id = original_set
            MOD.generalized._fetch_coordinate = original_fetch
        self.assertIsNone(row)
        self.assertEqual(reason, "SHORT_SET_COORDINATE_ERROR:test failure")

    def test_safety_contract_disables_writes_and_transactions(self):
        summary = MOD.safe_summary()
        self.assertEqual(
            summary["retrieval_rule"],
            "EXACT_PROVIDER_SHORT_SET_NAME_PLUS_EXACT_LOCALID",
        )
        self.assertFalse(summary["fuzzy_matching"])
        self.assertFalse(summary["translation_assumed"])
        self.assertFalse(summary["provider_set_alias_table_used"])
        for key in (
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
