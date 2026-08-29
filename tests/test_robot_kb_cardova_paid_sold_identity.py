import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_paid_sold_identity.py")
SPEC = importlib.util.spec_from_file_location("cardova_paid_identity", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def paid_record(**updates):
    row = {
        "source": "cardova_public_past_auction",
        "source_native_record_id": "01CARDOVA",
        "source_url": "https://www.cardova.co.jp/en/auction/card/01CARDOVA",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "sale_evidence_ready": True,
        "currency": "JPY",
        "currency_proven": True,
        "final_bid_jpy": 8500000,
        "auction_end_at_utc": "2025-12-14T13:01:00+00:00",
        "payment_completed_at": "",
        "payment_completed_at_proven": False,
        "grader": "PSA",
        "grade": "10",
        "certification_number": "42113707",
        "language": "Japanese",
        "card_name": "Gengar",
        "set_name": "Pokemon TCG: Japanese Masaki Promo",
        "collector_number": "#094",
        "identity_status": "PENDING_TCGDEX",
        "microvariant_status": "PENDING_TCGDEX",
        "sale_transaction_ready": False,
    }
    row.update(updates)
    return row


def canonical(status="EXACT", **updates):
    data = {
        "status": status,
        "reason": "TCGDEX_EXACT_TEST",
        "language_code": "ja",
        "card_id": "test-094",
        "name": "Gengar",
        "set_name": "Masaki Promo",
    }
    data.update(updates)
    return SimpleNamespace(**data)


class CardovaPaidSoldIdentityTests(unittest.TestCase):
    def test_stack_installs_each_existing_layer_once_per_process(self):
        names = (
            "install_v4_tcgdex_exact_coordinate_recovery",
            "install_v4_tcgdex_run1054_set_aliases",
            "install_v4_tcgdex_japanese_set_aliases",
            "install_v4_tcgdex_generalized_coordinate_recovery",
            "install_v4_tcgdex_two_of_three_backport",
            "install_v4_tcgdex_unique_coordinate_fallback",
            "install_v4_tcgdex_source_pinned_finish",
            "install_global_marketplace_tcgdex_source_alias_recovery",
        )
        originals = {name: getattr(MOD, name) for name in names}
        original_detailed = MOD.detailed_variants.install_v4_tcgdex_detailed_variants
        calls = {name: 0 for name in (*names, "detailed")}
        try:
            MOD._TCGDEX_STACK_INSTALLED = False
            for name in names:
                def fake(name=name):
                    calls[name] += 1
                setattr(MOD, name, fake)
            MOD.detailed_variants.install_v4_tcgdex_detailed_variants = lambda: calls.__setitem__("detailed", calls["detailed"] + 1)

            MOD.install_tcgdex_stack_once()
            MOD.install_tcgdex_stack_once()

            for name, count in calls.items():
                self.assertEqual(count, 1, name)
            self.assertTrue(MOD._TCGDEX_STACK_INSTALLED)
        finally:
            for name, value in originals.items():
                setattr(MOD, name, value)
            MOD.detailed_variants.install_v4_tcgdex_detailed_variants = original_detailed
            MOD._TCGDEX_STACK_INSTALLED = False

    def test_incomplete_identity_is_blocked_before_tcgdex(self):
        calls = []
        result = MOD.resolve_records(
            [paid_record(card_name="")],
            max_records=20,
            resolver=lambda identity: calls.append(identity),
            stack_installer=lambda: None,
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["exact_microvariant_count"], 0)
        self.assertEqual(result["blocked"], {"IDENTITY_INPUT_INCOMPLETE": 1})

    def test_non_exact_tcgdex_result_remains_blocked(self):
        result = MOD.resolve_records(
            [paid_record()],
            max_records=20,
            resolver=lambda identity: (None, canonical("AMBIGUOUS", reason="TEST_AMBIGUOUS")),
            stack_installer=lambda: None,
        )
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["exact_microvariant_count"], 0)
        self.assertEqual(result["blocked"], {"TCGDEX_AMBIGUOUS:TEST_AMBIGUOUS": 1})

    def test_exact_macro_with_ambiguous_microvariant_is_blocked(self):
        result = MOD.resolve_records(
            [paid_record()],
            max_records=20,
            resolver=lambda identity: (None, canonical()),
            microvariant_checker=lambda identity, card: (
                False,
                "AMBIGUOUS",
                "multiple material variants remain",
                {},
            ),
            stack_installer=lambda: None,
        )
        self.assertEqual(result["macro_identity_exact_count"], 1)
        self.assertEqual(result["exact_microvariant_count"], 0)
        self.assertEqual(
            result["blocked"],
            {"MICROVARIANT_AMBIGUOUS:multiple material variants remain": 1},
        )

    def test_exact_identity_and_microvariant_never_becomes_sale_transaction(self):
        result = MOD.resolve_records(
            [paid_record()],
            max_records=20,
            resolver=lambda identity: (None, canonical()),
            microvariant_checker=lambda identity, card: (
                True,
                "EXACT",
                "unique compatible detailed variant",
                {"finish": "holo"},
            ),
            stack_installer=lambda: None,
        )
        self.assertEqual(result["macro_identity_exact_count"], 1)
        self.assertEqual(result["exact_microvariant_count"], 1)
        row = result["records"][0]
        self.assertEqual(row["identity_status"], "EXACT")
        self.assertEqual(row["microvariant_status"], "EXACT")
        self.assertEqual(row["tcgdex_card_id"], "test-094")
        self.assertEqual(row["microvariant_dimensions"], {"finish": "holo"})
        self.assertTrue(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["payment_completed_at_proven"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_one_tcgdex_resolution_per_selected_record(self):
        calls = []
        records = [paid_record(source_native_record_id="A"), paid_record(source_native_record_id="B")]

        def resolver(identity):
            calls.append(identity)
            return None, canonical()

        result = MOD.resolve_records(
            records,
            max_records=20,
            resolver=resolver,
            microvariant_checker=lambda identity, card: (True, "EXACT", "ok", {}),
            stack_installer=lambda: None,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["exact_microvariant_count"], 2)

    def test_unproven_paid_or_currency_input_is_rejected(self):
        for updates, reason in (
            ({"provider_sale_status_proven": False}, "PAYMENT_SEMANTICS_UNPROVEN"),
            ({"currency_proven": False}, "CURRENCY_UNPROVEN"),
            ({"currency": "USD"}, "CURRENCY_NOT_JPY"),
            ({"sale_evidence_ready": False}, "SALE_EVIDENCE_NOT_READY"),
        ):
            with self.subTest(reason=reason):
                result = MOD.resolve_records(
                    [paid_record(**updates)],
                    max_records=20,
                    resolver=lambda identity: (None, canonical()),
                    stack_installer=lambda: None,
                )
                self.assertEqual(result["blocked"], {reason: 1})

    def test_safety_summary_locks_all_writes_and_transactions_off(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["identity_resolution_attempted"])
        self.assertFalse(summary["new_identity_resolver_created"])
        self.assertFalse(summary["payment_completed_at_proven"])
        self.assertFalse(summary["sale_transaction_ready"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["sale_transaction_stored"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["notification_sent"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_offer"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
