from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_identity_recovery_batch as recovery


def paid_record(**updates):
    row = {
        "source": "cardova_public_past_auction",
        "source_native_record_id": "01CARDOVA",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "sale_evidence_ready": True,
        "currency": "JPY",
        "currency_proven": True,
        "final_bid_jpy": 100000,
        "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
        "certification_number": "12345678",
        "card_name": "Mario Pikachu",
        "set_name": "Pokemon TCG: Japanese XY Promo",
        "collector_number": "294/XY-P",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
    }
    row.update(updates)
    return row


def canonical(status="EXACT", **updates):
    values = {
        "status": status,
        "reason": "TCGDEX_TEST",
        "language_code": "ja",
        "card_id": "xy-p-294",
        "set_name": "XY Promos",
    }
    values.update(updates)
    return SimpleNamespace(**values)


class EmptyCatalog:
    result_requests = 0
    detail_requests = 0


class CardovaIdentityRecoveryBatchTests(unittest.TestCase):
    def test_database_guard_accepts_only_canonical_loopback_postgres(self):
        accepted = recovery.validate_local_database_url(
            "postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb"
        )
        self.assertEqual(accepted["database_scope"], "LOCAL_MAC_POSTGRES_READ_ONLY")
        for url in (
            "postgresql://user@example.com/robot_pokemon_kb",
            "postgresql://user@127.0.0.1/other",
            "sqlite:///robot_pokemon_kb",
            "",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    recovery.validate_local_database_url(url)

    def test_tcgdex_exact_microvariant_becomes_link_candidate_without_write(self):
        payload = recovery.recover_records(
            [paid_record()],
            resolver=lambda identity: (None, canonical()),
            microvariant_checker=lambda identity, card: (
                True,
                "EXACT",
                "unique detailed variant",
                {"finish": "holo"},
            ),
            official_catalog=EmptyCatalog(),
            stack_installer=lambda: None,
        )
        self.assertEqual(payload["tcgdex_macro_identity_exact_count"], 1)
        self.assertEqual(payload["tcgdex_exact_microvariant_count"], 1)
        self.assertEqual(payload["exact_identity_link_candidate_count"], 1)
        self.assertEqual(payload["official_jp_macro_identity_exact_count"], 0)
        self.assertEqual(payload["still_unresolved_count"], 0)
        self.assertTrue(payload["records"][0]["exact_identity_link_candidate"])

    def test_tcgdex_macro_exact_does_not_force_ambiguous_microvariant(self):
        payload = recovery.recover_records(
            [paid_record()],
            resolver=lambda identity: (None, canonical()),
            microvariant_checker=lambda identity, card: (
                False,
                "AMBIGUOUS",
                "two finishes remain",
                {},
            ),
            official_catalog=EmptyCatalog(),
            stack_installer=lambda: None,
        )
        self.assertEqual(payload["tcgdex_macro_identity_exact_count"], 1)
        self.assertEqual(payload["exact_identity_link_candidate_count"], 0)
        self.assertEqual(payload["still_unresolved_count"], 1)
        self.assertFalse(payload["records"][0]["microvariant_exact"])
        self.assertEqual(
            payload["blocked"],
            {"TCGDEX_MACRO_EXACT_MICROVARIANT_AMBIGUOUS:two finishes remain": 1},
        )

    def test_structural_jp_promo_can_use_existing_official_macro_fallback(self):
        original = recovery.official_probe.probe_record
        try:
            recovery.official_probe.probe_record = lambda record, catalog: (
                {
                    "source_native_record_id": record["source_native_record_id"],
                    "macro_identity_status": "EXACT",
                    "official_card_id": "32349",
                    "microvariant_exact": False,
                },
                "OFFICIAL_COORDINATE_EXACT_UNIQUE",
            )
            payload = recovery.recover_records(
                [paid_record()],
                resolver=lambda identity: (
                    None,
                    canonical("UNRESOLVED", reason="TCGDEX_NO_MATCH"),
                ),
                official_catalog=EmptyCatalog(),
                stack_installer=lambda: None,
            )
        finally:
            recovery.official_probe.probe_record = original

        self.assertEqual(payload["official_jp_fallback_candidate_count"], 1)
        self.assertEqual(payload["official_jp_macro_identity_exact_count"], 1)
        self.assertEqual(payload["macro_identity_exact_total"], 1)
        self.assertEqual(payload["exact_identity_link_candidate_count"], 0)
        row = payload["records"][0]
        self.assertEqual(row["recovery_source"], "POKEMON_JP_OFFICIAL")
        self.assertIn("TCGDEX_UNRESOLVED", row["tcgdex_prior_status"])
        self.assertFalse(row["exact_identity_link_candidate"])

    def test_nonpromo_tcgdex_failure_stays_fail_visible(self):
        payload = recovery.recover_records(
            [paid_record(collector_number="102/100")],
            resolver=lambda identity: (
                None,
                canonical("UNRESOLVED", reason="TCGDEX_NO_MATCH"),
            ),
            official_catalog=EmptyCatalog(),
            stack_installer=lambda: None,
        )
        self.assertEqual(payload["official_jp_fallback_candidate_count"], 0)
        self.assertEqual(payload["macro_identity_exact_total"], 0)
        self.assertEqual(
            payload["blocked"],
            {"TCGDEX_UNRESOLVED:TCGDEX_NO_MATCH": 1},
        )

    def test_read_path_is_explicit_postgres_read_only_and_has_no_commit(self):
        text = (LOCAL / "robot_kb_cardova_identity_recovery_batch.py").read_text(encoding="utf-8")
        self.assertIn('connection.execute("BEGIN READ ONLY")', text)
        self.assertIn('SHOW transaction_read_only', text)
        self.assertIn('read_only["transaction_read_only"]', text)
        self.assertNotIn('read_only[0]', text)
        self.assertIn('connection.execute("ROLLBACK")', text)
        self.assertNotIn('connection.execute("COMMIT")', text)

    def test_safety_contract_disables_all_mutating_or_economic_actions(self):
        summary = recovery.safe_summary()
        self.assertTrue(summary["database_read_only_transaction"])
        self.assertFalse(summary["new_identity_resolver_created"])
        for key in (
            "remote_cloud_access_allowed",
            "fuzzy_matching",
            "translation_assumed",
            "provider_variant_claim_as_exact_identity",
            "canonical_link_written",
            "robot_kb_write",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertIs(summary[key], False, key)


if __name__ == "__main__":
    unittest.main()
