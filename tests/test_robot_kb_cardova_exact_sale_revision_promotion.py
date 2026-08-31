from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_exact_sale_revision_promotion.py")

if P3_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("cardova_exact_sale_revision_promotion", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    sys.modules[SPEC.name] = MOD
    SPEC.loader.exec_module(MOD)

    from robot_kb.repository import KnowledgeBase
    from robot_kb.sidecar.models import ShadowDiagnostics
    from robot_kb.sidecar.persistence import ShadowKnowledgePersistence
else:
    MOD = None


SOURCE_ID = "01TESTCARDOVAREVISION000000001"
OBSERVED_AT = "2026-08-31T12:00:00+00:00"
REVISION_AT = "2026-08-31T13:00:00+00:00"


def sale_row(**overrides):
    row = {
        "source": "cardova_public_past_auction",
        "source_native_record_id": SOURCE_ID,
        "source_url": f"https://www.cardova.co.jp/en/auction/card/{SOURCE_ID}",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "final_bid_jpy": 123456,
        "currency": "JPY",
        "currency_proven": True,
        "auction_end_at_utc": "2026-08-29T12:00:00+00:00",
        "certification_number": "159075586",
        "grader": "PSA",
        "grade": "9",
        "language": "Japanese",
        "card_name": "Testmon",
        "set_name": "Pokemon TCG: Japanese Basic",
        "collector_number": "1",
        "sale_evidence_ready": True,
        "sale_transaction_ready": False,
    }
    row.update(overrides)
    return row


def identity_row(**overrides):
    row = {
        "source_native_record_id": SOURCE_ID,
        "card_name_provider_claim": "Testmon",
        "collector_number_provider_claim": "1",
        "provider_set_label": "Pokemon TCG: Japanese Basic",
        "grader": "PSA",
        "grade": "9",
        "language": "Japanese",
        "tcgdex_card_id": "PMCG1-001",
        "tcgdex_set_id": "PMCG1",
        "tcgdex_local_id": "001",
        "finish_exact": True,
        "finish": "holo",
        "pinned_source_variant_exact": True,
        "pinned_source_variant_dimensions": {"finish": "holo"},
        "pinned_source_variant_opaque": [],
        "printing_exact": False,
        "printing": "",
        "printing_applicability_exact": True,
        "printing_applicability_reason": "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL",
        "edition_exact": False,
        "edition": "",
        "edition_applicability_exact": True,
        "edition_applicability_reason": "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT",
        "special_finish_exact": False,
        "special_finish": "",
        "special_finish_applicability_exact": True,
        "special_finish_applicability_reason": "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT",
        "remaining_unproven_axes": [],
        "macro_identity_exact": True,
        "microvariant_exact": True,
        "exact_identity_link_candidate": True,
        "canonical_link_written": False,
    }
    row.update(overrides)
    return row


@unittest.skipUnless(P3_AVAILABLE, "pinned Robot KB P3 runtime is required")
class CardovaExactSaleRevisionPromotionTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase.open(":memory:")
        self.sale = sale_row()
        built, reason = MOD.print_run.base.sale_dry.build_p3_sale(
            self.sale,
            observed_at=OBSERVED_AT,
        )
        self.assertEqual(reason, "P3_SALE_READY_UNRESOLVED_IDENTITY")
        self.assertIsNotNone(built)
        raw, observation = built
        diag = ShadowDiagnostics()
        ShadowKnowledgePersistence(self.kb).ingest(raw, (observation,), diag)
        self.assertEqual(diag.sale_transactions_stored, 1)
        self.assertEqual(diag.unresolved_identities_retained, 1)
        self.original = self.kb.connection.execute(
            """
            SELECT observation.*
            FROM market_observation AS observation
            JOIN source_system AS source ON source.id = observation.source_system_id
            WHERE source.code = 'cardova'
              AND observation.source_native_record_id = ?
              AND observation.observation_type = 'SALE_TRANSACTION'
              AND observation.lifecycle_state = 'SEALED'
            """,
            (SOURCE_ID,),
        ).fetchone()
        self.assertIsNotNone(self.original)

    def tearDown(self):
        self.kb.close()

    def test_promotion_keeps_original_immutable_and_creates_exact_revision(self):
        result = MOD.promote_existing_sale(
            self.kb,
            identity_row(),
            self.sale,
            revision_observed_at=REVISION_AT,
        )
        self.assertFalse(result.replayed)
        self.assertEqual(result.original_observation_id, self.original["id"])
        self.assertNotEqual(result.revision_observation_id, self.original["id"])

        original = self.kb.fetch_observation(self.original["id"])
        revision = self.kb.fetch_observation(result.revision_observation_id)
        self.assertEqual(original["lifecycle_state"], "SEALED")
        self.assertIsNone(original["canonical_card_id"])
        self.assertEqual(revision["lifecycle_state"], "SEALED")
        self.assertEqual(revision["canonical_card_id"], result.canonical_card_id)
        self.assertEqual(revision["revision_of_observation_id"], original["id"])
        self.assertEqual(revision["event_at"], original["event_at"])
        self.assertEqual(revision["observed_at"], REVISION_AT)

        relationship = self.kb.connection.execute(
            """
            SELECT relationship_type
            FROM observation_relationship
            WHERE from_observation_id = ? AND to_observation_id = ?
            """,
            (result.revision_observation_id, original["id"]),
        ).fetchone()
        self.assertEqual(relationship["relationship_type"], "REVISION_OF")

        old_fact = MOD._sale_fact(self.kb, original["id"])
        new_fact = MOD._sale_fact(self.kb, result.revision_observation_id)
        self.assertEqual(old_fact, new_fact)
        old_prices = MOD._price_components(self.kb, original["id"])
        new_prices = MOD._price_components(self.kb, result.revision_observation_id)
        self.assertEqual(old_prices, new_prices)
        self.assertEqual(len(new_prices), 1)
        self.assertEqual(new_prices[0].component_type, "HAMMER_PRICE")
        self.assertEqual(new_prices[0].amount_minor, 123456)
        self.assertEqual(new_prices[0].currency, "JPY")

        resolution = self.kb.connection.execute(
            """
            SELECT resolution_state, canonical_card_id, supersedes_resolution_id
            FROM identity_resolution WHERE id = ?
            """,
            (result.proven_resolution_id,),
        ).fetchone()
        self.assertEqual(resolution["resolution_state"], "PROVEN")
        self.assertEqual(resolution["canonical_card_id"], result.canonical_card_id)
        self.assertIsNotNone(resolution["supersedes_resolution_id"])

        link = self.kb.connection.execute(
            """
            SELECT canonical_card_id, link_role
            FROM observation_identity_link
            WHERE observation_id = ? AND identity_resolution_id = ?
            """,
            (result.revision_observation_id, result.proven_resolution_id),
        ).fetchone()
        self.assertEqual(link["link_role"], "RESOLVED_AS")
        self.assertEqual(link["canonical_card_id"], result.canonical_card_id)

        self.assertEqual(
            MOD.leaf_sale_state(self.kb, SOURCE_ID),
            {"unresolved": 0, "exact": 1, "total": 1},
        )
        physical = self.kb.connection.execute(
            """
            SELECT COUNT(*) AS n FROM market_observation
            WHERE source_native_record_id = ?
              AND observation_type = 'SALE_TRANSACTION'
              AND lifecycle_state = 'SEALED'
            """,
            (SOURCE_ID,),
        ).fetchone()["n"]
        self.assertEqual(physical, 2)

    def test_replay_returns_same_exact_revision_without_duplication(self):
        first = MOD.promote_existing_sale(
            self.kb,
            identity_row(),
            self.sale,
            revision_observed_at=REVISION_AT,
        )
        before_observations = self.kb.connection.execute(
            "SELECT COUNT(*) AS n FROM market_observation"
        ).fetchone()["n"]
        before_resolutions = self.kb.connection.execute(
            "SELECT COUNT(*) AS n FROM identity_resolution"
        ).fetchone()["n"]

        second = MOD.promote_existing_sale(
            self.kb,
            identity_row(),
            self.sale,
            revision_observed_at="2026-08-31T14:00:00+00:00",
        )
        self.assertTrue(second.replayed)
        self.assertEqual(second.revision_observation_id, first.revision_observation_id)
        self.assertEqual(second.canonical_card_id, first.canonical_card_id)
        self.assertEqual(second.proven_resolution_id, first.proven_resolution_id)
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM market_observation").fetchone()["n"],
            before_observations,
        )
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM identity_resolution").fetchone()["n"],
            before_resolutions,
        )
        self.assertEqual(
            MOD.leaf_sale_state(self.kb, SOURCE_ID),
            {"unresolved": 0, "exact": 1, "total": 1},
        )

    def test_economic_conflict_fails_closed_without_canonical_side_effects(self):
        conflicting = sale_row(final_bid_jpy=999999)
        before_cards = self.kb.connection.execute(
            "SELECT COUNT(*) AS n FROM canonical_card"
        ).fetchone()["n"]
        before_links = self.kb.connection.execute(
            "SELECT COUNT(*) AS n FROM identifier_link"
        ).fetchone()["n"]
        with self.assertRaises(MOD.RevisionPromotionError):
            MOD.promote_existing_sale(
                self.kb,
                identity_row(),
                conflicting,
                revision_observed_at=REVISION_AT,
            )
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM canonical_card").fetchone()["n"],
            before_cards,
        )
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM identifier_link").fetchone()["n"],
            before_links,
        )
        self.assertEqual(
            MOD.leaf_sale_state(self.kb, SOURCE_ID),
            {"unresolved": 1, "exact": 0, "total": 1},
        )

    def test_safety_contract(self):
        summary = MOD.safe_summary()
        self.assertFalse(summary["sealed_original_updated"])
        self.assertEqual(summary["revision_relationship"], "REVISION_OF")
        self.assertFalse(summary["economic_fact_changed"])
        self.assertEqual(summary["exact_identity_resolution"], "PROVEN")
        self.assertTrue(summary["promotion_atomic"])
        self.assertTrue(summary["replay_idempotent"])
        for key in (
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
            "v4_economic_use",
        ):
            self.assertFalse(summary[key], key)


if __name__ == "__main__":
    unittest.main()
