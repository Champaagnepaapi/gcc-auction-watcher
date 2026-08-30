from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import unittest


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_sale_transaction_ingest.py")
DRY_PATH = Path("mac/robot-kb-local/robot_kb_cardova_sale_transaction_dry_run.py")

if P3_AVAILABLE:
    from robot_kb.repository import KnowledgeBase, KnowledgeBaseError

    DRY_SPEC = importlib.util.spec_from_file_location("cardova_sale_transaction_dry_run", DRY_PATH)
    DRY = importlib.util.module_from_spec(DRY_SPEC)
    assert DRY_SPEC.loader is not None
    DRY_SPEC.loader.exec_module(DRY)

    SPEC = importlib.util.spec_from_file_location("cardova_sale_transaction_ingest", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(MOD)
else:
    KnowledgeBase = None
    KnowledgeBaseError = None
    DRY = None
    MOD = None


def paid_record(native: str = "01TESTCARDOVAPAIDSALE", bid: int = 123456) -> dict:
    return {
        "source": "cardova_public_past_auction",
        "source_native_record_id": native,
        "source_url": f"https://www.cardova.co.jp/en/auction/card/{native}",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "bid_payment_status": 5,
        "finished": 1,
        "canceled_at": None,
        "re_listed": 0,
        "re_listing_count": 0,
        "final_bid_jpy": bid,
        "currency": "JPY",
        "currency_proven": True,
        "price_component": "PROVIDER_FINAL_WINNING_BID",
        "all_in_price_proven": False,
        "auction_end_at_raw": "2026-08-29T21:00:00+09:00",
        "auction_end_at_utc": "2026-08-29T12:00:00+00:00",
        "payment_completed_at": "",
        "payment_completed_at_proven": False,
        "grader": "PSA",
        "grade": "10",
        "certification_number": "123456789",
        "language": "Japanese",
        "card_name": "Pikachu",
        "set_name": "Pokemon TCG: Japanese XY Promo",
        "collector_number": "#279/XY-P",
        "provider_set_name_short": "20th Anniversary Festa",
        "provider_series": "Pokemon TCG: Japanese XY Promo",
        "provider_title": "Pikachu 279/XY-P PSA 10",
        "provider_item_name": "Pikachu",
        "provider_card_ulid": "CARD01",
        "sale_evidence_ready": True,
        "sale_transaction_ready": False,
    }


@unittest.skipUnless(P3_AVAILABLE, "pinned Robot KB P3 runtime is not present in this V4-only test lane")
class CardovaSaleTransactionIngestTests(unittest.TestCase):
    def test_database_guard_accepts_only_loopback_canonical_database(self):
        for url in (
            "postgresql://localhost/robot_pokemon_kb",
            "postgresql://127.0.0.1:5432/robot_pokemon_kb",
            "postgresql://[::1]/robot_pokemon_kb",
        ):
            result = MOD.validate_local_database_url(url)
            self.assertEqual(result["database_scope"], "LOCAL_MAC_POSTGRES_ONLY")
            self.assertEqual(result["database_name"], "robot_pokemon_kb")

        for url in (
            "postgresql://example.com/robot_pokemon_kb",
            "postgresql://localhost/other_db",
            "sqlite:///robot_pokemon_kb",
        ):
            with self.assertRaises(ValueError):
                MOD.validate_local_database_url(url)

    def test_memory_core_ingests_unresolved_sale_and_replays(self):
        built, reason = DRY.build_p3_sale(paid_record(), observed_at="2026-08-30T08:00:00+00:00")
        self.assertEqual(reason, "P3_SALE_READY_UNRESOLVED_IDENTITY")
        assert built is not None
        with KnowledgeBase.open(":memory:") as kb:
            first = MOD.ingest_prepared_batch(kb, [built])
            second = MOD.ingest_prepared_batch(kb, [built])
        self.assertEqual(first["sale_transactions_stored"], 1)
        self.assertEqual(first["exact_identities_linked"], 0)
        self.assertEqual(first["selected_after"]["canonical_card_links"], 0)
        self.assertEqual(first["selected_after"]["hammer_price_jpy_rows"], 1)
        self.assertEqual(second["sale_transactions_stored"], 0)
        self.assertEqual(second["duplicate_sale_replays"], 1)

    def test_existing_cardova_source_metadata_is_reused_without_mutation(self):
        built, reason = DRY.build_p3_sale(
            paid_record(), observed_at="2026-08-30T08:00:00+00:00"
        )
        self.assertEqual(reason, "P3_SALE_READY_UNRESOLVED_IDENTITY")
        assert built is not None
        with KnowledgeBase.open(":memory:") as kb:
            kb.create_source_system("cardova", "CARDOVA Historical", "MARKET")
            result = MOD.ingest_prepared_batch(kb, [built])
            row = kb.connection.execute(
                "SELECT name, system_role FROM source_system WHERE code='cardova'"
            ).fetchone()
        self.assertTrue(result["source_system_reused"])
        self.assertFalse(result["source_system_mutated"])
        self.assertEqual(row["name"], "CARDOVA Historical")
        self.assertEqual(row["system_role"], "MARKET")
        self.assertEqual(result["sale_transactions_stored"], 1)
        self.assertEqual(result["selected_after"]["canonical_card_links"], 0)

    def test_batch_rolls_back_if_second_sale_fails_persistence(self):
        first, _ = DRY.build_p3_sale(
            paid_record(native="01TESTCARDOVAONE", bid=123456),
            observed_at="2026-08-30T08:00:00+00:00",
        )
        second, _ = DRY.build_p3_sale(
            paid_record(native="01TESTCARDOVATWO", bid=654321),
            observed_at="2026-08-30T08:00:00+00:00",
        )
        assert first is not None and second is not None
        second_raw, second_observation = second
        bad_second = (
            second_raw,
            replace(
                second_observation,
                fact={
                    **second_observation.fact,
                    "sale_occurred_at": "2026-08-29T11:59:00+00:00",
                },
            ),
        )
        with KnowledgeBase.open(":memory:") as kb:
            with self.assertRaises(KnowledgeBaseError):
                MOD.ingest_prepared_batch(kb, [first, bad_second])
            count = kb.connection.execute(
                "SELECT COUNT(*) AS n FROM market_observation WHERE observation_type='SALE_TRANSACTION'"
            ).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_summary_never_claims_identity_v4_or_commerce(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["durable_robot_kb_write"])
        self.assertTrue(summary["local_postgres_only"])
        self.assertFalse(summary["remote_cloud_write_allowed"])
        self.assertFalse(summary["canonical_identity_claimed"])
        self.assertFalse(summary["commercial_microvariant_claimed"])
        self.assertFalse(summary["source_system_mutated"])
        for key in (
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
