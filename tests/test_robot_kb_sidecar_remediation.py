from __future__ import annotations

from dataclasses import replace
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import robot_kb.migrations as migrations
from robot_kb import (
    InclusionState,
    KnowledgeBase,
    ObservationType,
    PriceKnowledge,
    ResolutionState,
    SourceKind,
)
from robot_kb.repository import IdempotencyConflict, PriceComponent
from robot_kb.sidecar import (
    CollectionResult,
    GCCMarketplaceCollector,
    IdentityClaim,
    RawSourceRecord,
    ShadowDiagnostics,
    ShadowKnowledgePersistence,
    ShadowSidecar,
)
from robot_kb.sidecar.__main__ import main as sidecar_main
from robot_kb.sidecar.normalizers import normalize_gcc, normalize_tcgdex


T0 = "2026-08-14T08:00:00Z"
T1 = "2026-08-14T09:00:00Z"
T2 = "2026-08-14T10:00:00Z"
T3 = "2026-08-14T11:00:00Z"


def gcc_payload(listing_id: str = "listing-1", **overrides: object) -> dict:
    payload = {
        "id": listing_id,
        "status": "ON_SALE",
        "sellingType": "FIXED_PRICE",
        "priceInCents": 3_000,
        "updatedAt": T0,
        "quantity": 1,
        "item": {
            "title": "Charizard 4/102",
            "collectible": {
                "type": "CARDS",
                "category": "Pokemon",
                "language": "English",
                "set": "Base Set",
                "reference": "4/102",
            },
        },
    }
    payload.update(overrides)
    return payload


def gcc_record(payload: dict, retrieved_at: str = T2) -> RawSourceRecord:
    return RawSourceRecord(
        source_code="gcc",
        source_name="GCC Marketplace",
        source_role="LISTING_PLATFORM",
        source_native_record_id=payload["id"],
        payload=payload,
        retrieved_at=retrieved_at,
        object_type="LISTING",
        external_native_id=payload["id"],
    )


def sold_payload(
    listing_id: str = "sale-1", price: int = 2_750, **overrides: object
) -> dict:
    payload = gcc_payload(
        listing_id,
        status="SOLD",
        updatedAt=T1,
        soldAt=T1,
        soldPriceInCents=price,
    )
    payload.update(overrides)
    return payload


def tcgdex_record(pricing: dict, retrieved_at: str = T2) -> RawSourceRecord:
    payload = {"id": "base1-4", "name": "Charizard", "pricing": pricing}
    return RawSourceRecord(
        source_code="tcgdex",
        source_name="TCGdex",
        source_role="PROVIDER",
        source_native_record_id="base1-4",
        payload=payload,
        retrieved_at=retrieved_at,
        object_type="CARD",
        external_native_id="base1-4",
    )


def table_counts(kb: KnowledgeBase) -> dict[str, int]:
    names = [
        row[0]
        for row in kb.connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]
    return {
        name: kb.connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name in names
    }


class SaleAndClassificationRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()
        self.persistence = ShadowKnowledgePersistence(self.kb, clock=lambda: T3)
        self.sidecar = ShadowSidecar(self.persistence)

    def tearDown(self) -> None:
        self.kb.close()

    def run_record(self, record: RawSourceRecord) -> None:
        self.sidecar.run_source("fixture", lambda: CollectionResult((record,)))

    def test_completed_sale_is_event_stable_across_retrieval_times(self):
        payload = sold_payload()
        self.run_record(gcc_record(payload, T2))
        self.run_record(gcc_record(payload, T3))

        self.assertEqual(self.kb.observation_count(), 1)
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT COUNT(*) FROM sale_transaction"
            ).fetchone()[0],
            1,
        )
        source_record = self.kb.connection.execute(
            "SELECT id FROM source_record"
        ).fetchone()
        self.assertEqual(
            len(self.kb.source_record_retrievals(source_record["id"])), 2
        )
        self.assertEqual(self.sidecar.diagnostics.duplicate_sale_replays, 1)
        self.assertEqual(self.sidecar.diagnostics.observations_replayed, 1)

    def test_changed_finalized_sale_fails_loudly_and_rolls_back_retrieval(self):
        first = sold_payload(price=2_750)
        self.run_record(gcc_record(first, T2))
        second = sold_payload(price=2_700)
        self.run_record(gcc_record(second, T3))

        self.assertEqual(self.sidecar.diagnostics.source_failures, 1)
        self.assertIn("IdempotencyConflict", self.sidecar.diagnostics.failure_messages[0])
        self.assertEqual(self.kb.observation_count(), 1)
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM source_record").fetchone()[0],
            1,
        )

    def test_sale_evidence_and_chronology_fail_closed(self):
        cases = {
            "future": sold_payload(soldAt="2099-01-01T00:00:00Z"),
            "ended_unsold": gcc_payload(status="ENDED_UNSOLD"),
            "ambiguous_completed": gcc_payload(
                status="COMPLETED",
                completedAt=T1,
                finalPriceInCents=2_700,
            ),
            "malformed_sale_time": sold_payload(soldAt="not-a-timestamp"),
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                batch = normalize_gcc(gcc_record(payload, T2))
                self.assertEqual(
                    batch.observations[0].observation_type,
                    ObservationType.LISTING_SNAPSHOT,
                )
                self.assertEqual(batch.sale_candidates_rejected, 1)

        genuine = normalize_gcc(gcc_record(sold_payload(), T2))
        self.assertEqual(
            genuine.observations[0].observation_type,
            ObservationType.SALE_TRANSACTION,
        )
        self.assertTrue(genuine.observations[0].genuine_sale_evidence)

    def test_sale_rejection_diagnostics_reflect_actual_records(self):
        self.run_record(gcc_record(sold_payload("future", soldAt="2099-01-01T00:00:00Z")))
        self.run_record(
            gcc_record(
                gcc_payload(
                    "ambiguous",
                    status="COMPLETED",
                    completedAt=T1,
                    finalPriceInCents=2_700,
                )
            )
        )
        self.assertEqual(self.sidecar.diagnostics.sale_candidates_rejected, 2)
        self.assertEqual(self.sidecar.diagnostics.ambiguous_sale_records, 1)
        self.assertNotIn("fabricated_sales", self.sidecar.diagnostics.as_dict())
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT COUNT(*) FROM sale_transaction"
            ).fetchone()[0],
            0,
        )

    def test_single_card_requires_positive_evidence(self):
        def titled(value: str) -> dict:
            return gcc_payload(
                item={**gcc_payload()["item"], "title": value}
            )

        cases = {
            "pick_one": titled("Pick one Pokemon card"),
            "choose_one": titled("Choose one"),
            "french_menu": titled("Choisissez une carte"),
            "english_or": titled("Charizard or Blastoise"),
            "french_or": titled("Dracaufeu ou Tortank"),
            "slash_alternative": titled("Charizard / Blastoise"),
            "ampersand_alternative": titled("Charizard & Blastoise"),
            "ten_times": titled("10x Charizard cards"),
            "two_times": titled("2x Charizard"),
            "english_number_word": titled("Two Charizard cards"),
            "french_number_word": titled("Deux cartes Dracaufeu"),
            "plural_cards": titled("Pokemon cards"),
            "plural_cartes": titled("Cartes Pokemon"),
            "complete_set": titled("Complete Base Set"),
            "sealed_box": gcc_payload(description="Sealed booster box"),
            "structured_bundle": gcc_payload(isBundle=True),
            "structured_sealed": gcc_payload(isSealed=True),
            "structured_sealed_type": gcc_payload(productType="SEALED_BOX"),
            "string_quantity": gcc_payload(quantity="2"),
            "multi_item_body": gcc_payload(
                description="Includes Charizard & Blastoise cards"
            ),
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                observation = normalize_gcc(gcc_record(payload)).observations[0]
                claims = {claim.field_name: claim.value for claim in observation.claims}
                self.assertFalse(observation.exact_identity_eligible)
                self.assertEqual(claims["item_scope"], "BUNDLE_OR_MULTI")
                self.assertIn("single_card_scope", observation.unresolved_dimensions)

        valid = normalize_gcc(gcc_record(gcc_payload())).observations[0]
        valid_claims = {claim.field_name: claim.value for claim in valid.claims}
        self.assertTrue(valid.exact_identity_eligible)
        self.assertEqual(valid_claims["item_scope"], "SINGLE_CARD")

    def test_authoritative_cardinality_is_required_and_normalized(self):
        for quantity in (1, "1", "01"):
            with self.subTest(quantity=quantity, expected="single"):
                observation = normalize_gcc(
                    gcc_record(gcc_payload(quantity=quantity))
                ).observations[0]
                claims = {claim.field_name: claim.value for claim in observation.claims}
                self.assertTrue(observation.exact_identity_eligible)
                self.assertEqual(claims["item_scope"], "SINGLE_CARD")

        for quantity in (2, "2", "02", "10", "10x", "x10", "two", "deux"):
            with self.subTest(quantity=quantity, expected="non-exact"):
                observation = normalize_gcc(
                    gcc_record(gcc_payload(quantity=quantity))
                ).observations[0]
                self.assertFalse(observation.exact_identity_eligible)
                self.assertIn("single_card_scope", observation.unresolved_dimensions)

        missing = gcc_payload()
        missing.pop("quantity")
        observation = normalize_gcc(gcc_record(missing)).observations[0]
        claims = {claim.field_name: claim.value for claim in observation.claims}
        self.assertFalse(observation.exact_identity_eligible)
        self.assertEqual(claims["item_scope"], "AMBIGUOUS_ITEM_SCOPE")
        self.assertIn("single_card_scope", observation.unresolved_dimensions)

        explicit_cardinality = gcc_payload()
        explicit_cardinality.pop("quantity")
        explicit_cardinality["cardCount"] = "01"
        observation = normalize_gcc(
            gcc_record(explicit_cardinality)
        ).observations[0]
        self.assertTrue(observation.exact_identity_eligible)

        missing_type = gcc_payload()
        missing_type["item"]["collectible"].pop("type")
        observation = normalize_gcc(gcc_record(missing_type)).observations[0]
        self.assertFalse(observation.exact_identity_eligible)

        conflicting_counts = gcc_payload(cardCount=2)
        observation = normalize_gcc(
            gcc_record(conflicting_counts)
        ).observations[0]
        self.assertFalse(observation.exact_identity_eligible)

    def test_ambiguous_listing_cannot_inherit_preproven_card_mapping(self):
        listing_id = "mapped-listing"
        self.run_record(gcc_record(gcc_payload(listing_id), T2))
        set_id = self.kb.create_canonical_set("base1", "Base Set")
        family_id = self.kb.create_card_family(set_id, "4/102", "Charizard")
        localized_id = self.kb.create_localized_card(family_id, "en", "Charizard")
        profile_id = self.kb.create_variant_profile({"finish": "HOLO"})
        self.kb.allow_variant_profile(family_id, profile_id)
        card_id = self.kb.create_canonical_card(localized_id, profile_id)
        identifier = self.kb.connection.execute(
            "SELECT id FROM external_identifier WHERE identifier_value = ?",
            (listing_id,),
        ).fetchone()
        self.kb.link_identifier(
            identifier["id"], ResolutionState.PROVEN, canonical_card_id=card_id
        )

        ambiguous = gcc_payload(
            listing_id,
            priceInCents=2_900,
            updatedAt=T1,
        )
        ambiguous.pop("quantity")
        self.run_record(gcc_record(ambiguous, T3))
        latest = self.kb.connection.execute(
            "SELECT canonical_card_id FROM market_observation ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        self.assertIsNone(latest["canonical_card_id"])

    def test_ambiguous_listing_is_retained_as_raw_unresolved_market_evidence(self):
        payload = gcc_payload("retained-ambiguous")
        payload.pop("quantity")
        self.run_record(gcc_record(payload, T2))

        observation = self.kb.connection.execute(
            "SELECT * FROM market_observation"
        ).fetchone()
        source_record = self.kb.connection.execute(
            "SELECT id FROM source_record WHERE source_native_record_id = ?",
            (payload["id"],),
        ).fetchone()
        resolution = self.kb.connection.execute(
            "SELECT resolution_state, canonical_card_id FROM identity_resolution"
        ).fetchone()
        item_scope = self.kb.connection.execute(
            "SELECT claimed_value_json FROM field_claim WHERE field_name = 'item_scope'"
        ).fetchone()

        self.assertEqual(observation["observation_type"], "LISTING_SNAPSHOT")
        self.assertIsNone(observation["canonical_card_id"])
        self.assertEqual(resolution["resolution_state"], "UNKNOWN")
        self.assertIsNone(resolution["canonical_card_id"])
        self.assertEqual(item_scope["claimed_value_json"], '"AMBIGUOUS_ITEM_SCOPE"')
        self.assertEqual(self.kb.raw_source_payload(source_record["id"]), payload)


class RawPayloadMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()
        self.source_id = self.kb.create_source_system(
            "raw-test", "Raw Test", "PROVIDER"
        )

    def tearDown(self) -> None:
        self.kb.close()

    def append(self, native_id: str, payload: object, retrieved_at: str = T0) -> str:
        return self.kb.append_source_record(
            self.source_id,
            native_id,
            payload,
            retrieved_at=retrieved_at,
        )

    def test_raw_json_is_exactly_reconstructable_and_content_addressed(self):
        payload = {"id": "one", "nested": {"z": 1, "a": [True, None, "é"]}}
        first = self.append("one", payload)
        second = self.append("two", payload, T1)

        self.assertEqual(self.kb.raw_source_payload(first), payload)
        self.assertEqual(self.kb.raw_source_payload(second), payload)
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM source_payload").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT COUNT(*) FROM source_record_payload"
            ).fetchone()[0],
            2,
        )

    def test_different_payload_for_same_listing_remains_distinct(self):
        first = self.append("listing", {"id": "listing", "price": 30}, T0)
        second = self.append("listing", {"id": "listing", "price": 29}, T1)
        self.assertNotEqual(first, second)
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM source_payload").fetchone()[0],
            2,
        )
        self.assertEqual(self.kb.raw_source_payload(first)["price"], 30)
        self.assertEqual(self.kb.raw_source_payload(second)["price"], 29)

    def test_payload_bytes_and_references_are_immutable(self):
        record_id = self.append("one", {"id": "one"})
        digest = self.kb.connection.execute(
            "SELECT payload_sha256 FROM source_record WHERE id = ?", (record_id,)
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "UPDATE source_payload SET payload_bytes = X'00' WHERE payload_sha256 = ?",
                (digest,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "DELETE FROM source_record_payload WHERE source_record_id = ?",
                (record_id,),
            )
        self.assertEqual(self.kb.raw_source_payload(record_id), {"id": "one"})

    def test_valid_0003_database_upgrades_forward_to_0004(self):
        self.kb.close()
        with tempfile.TemporaryDirectory(prefix="gcc-kb-v3-") as directory:
            root = Path(directory)
            v3 = root / "v3"
            v3.mkdir()
            for version in (1, 2, 3):
                source = sorted(migrations.MIGRATION_DIRECTORY.glob(f"{version:04d}_*.sql"))[0]
                shutil.copy2(source, v3 / source.name)
            connection = migrations.connect_database(root / "kb.sqlite3")
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", v3):
                    migrations.apply_migrations(connection)
                source_id = KnowledgeBase(connection).create_source_system(
                    "legacy", "Legacy", "PROVIDER"
                )
                connection.execute(
                    """
                    INSERT INTO source_record(
                        id, source_system_id, source_native_record_id,
                        payload_sha256, retrieved_at, created_at
                    ) VALUES ('srecord_legacy', ?, 'legacy-1', ?, ?, ?)
                    """,
                    (source_id, "0" * 64, T0, T0),
                )
                migrations.apply_migrations(connection)
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )],
                    [1, 2, 3, 4],
                )
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'source_payload'"
                    ).fetchone()
                )
            finally:
                connection.close()
        self.kb = KnowledgeBase.open()

    def test_corrupt_legacy_payload_hash_fails_0004_atomically(self):
        self.kb.close()
        with tempfile.TemporaryDirectory(prefix="gcc-kb-corrupt-v3-") as directory:
            root = Path(directory)
            v3 = root / "v3"
            v3.mkdir()
            for version in (1, 2, 3):
                source = sorted(migrations.MIGRATION_DIRECTORY.glob(f"{version:04d}_*.sql"))[0]
                shutil.copy2(source, v3 / source.name)
            connection = migrations.connect_database(root / "kb.sqlite3")
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", v3):
                    migrations.apply_migrations(connection)
                source_id = KnowledgeBase(connection).create_source_system(
                    "legacy", "Legacy", "PROVIDER"
                )
                connection.execute(
                    """
                    INSERT INTO source_record(
                        id, source_system_id, source_native_record_id,
                        payload_sha256, retrieved_at, created_at
                    ) VALUES ('srecord_corrupt', ?, 'legacy-1', 'bad', ?, ?)
                    """,
                    (source_id, T0, T0),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    migrations.apply_migrations(connection)
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )],
                    [1, 2, 3],
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'source_payload'"
                    ).fetchone()
                )
            finally:
                connection.close()
        self.kb = KnowledgeBase.open()


class AtomicIngestTests(unittest.TestCase):
    class FailingPersistence(ShadowKnowledgePersistence):
        def __init__(self, *args, fail_at: str, **kwargs):
            super().__init__(*args, **kwargs)
            self.fail_at = fail_at

        def _checkpoint(self, name, observation):
            if name == self.fail_at:
                raise RuntimeError(f"injected failure: {name}")

    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()
        self.diagnostics = ShadowDiagnostics()

    def tearDown(self) -> None:
        self.kb.close()

    def observation(self, listing_id: str = "atomic"):
        record = gcc_record(gcc_payload(listing_id))
        return record, normalize_gcc(record).observations[0]

    def assert_atomic_failure(self, persistence, record, observation):
        before = table_counts(self.kb)
        with self.assertRaises(Exception):
            persistence.ingest(record, (observation,), self.diagnostics)
        self.assertEqual(table_counts(self.kb), before)
        self.assertEqual(self.diagnostics.observations_accepted, 0)

    def test_failure_after_observation_seal_rolls_back_whole_unit(self):
        record, observation = self.observation("after-seal")
        persistence = self.FailingPersistence(
            self.kb, fail_at="after_observation_seal", clock=lambda: T3
        )
        self.assert_atomic_failure(persistence, record, observation)

    def test_failure_before_identity_link_preserves_previous_commit(self):
        good_record, good_observation = self.observation("good")
        ShadowKnowledgePersistence(self.kb, clock=lambda: T3).ingest(
            good_record, (good_observation,), self.diagnostics
        )
        baseline = table_counts(self.kb)
        bad_record, bad_observation = self.observation("before-link")
        persistence = self.FailingPersistence(
            self.kb, fail_at="before_identity_link", clock=lambda: T3
        )
        with self.assertRaises(RuntimeError):
            persistence.ingest(bad_record, (bad_observation,), self.diagnostics)
        self.assertEqual(table_counts(self.kb), baseline)
        self.assertEqual(self.kb.observation_count(), 1)

    def test_malformed_timestamp_rolls_back_whole_unit(self):
        record, observation = self.observation("bad-time")
        self.assert_atomic_failure(
            ShadowKnowledgePersistence(self.kb),
            record,
            replace(observation, observed_at="not-a-timestamp"),
        )

    def test_malformed_money_rolls_back_whole_unit(self):
        record, observation = self.observation("bad-money")
        malformed = object.__new__(PriceComponent)
        object.__setattr__(malformed, "component_type", "ITEM_PRICE")
        object.__setattr__(malformed, "amount_minor", 10**100)
        object.__setattr__(malformed, "currency", "EUR")
        object.__setattr__(malformed, "knowledge_state", PriceKnowledge.KNOWN)
        object.__setattr__(malformed, "inclusion_state", InclusionState.UNKNOWN)
        self.assert_atomic_failure(
            ShadowKnowledgePersistence(self.kb),
            record,
            replace(observation, prices=(malformed,)),
        )

    def test_malformed_identity_claim_rolls_back_whole_unit(self):
        record, observation = self.observation("bad-claim")
        invalid_claim = IdentityClaim("unserializable", {"set-value"}, SourceKind.LISTING)
        self.assert_atomic_failure(
            ShadowKnowledgePersistence(self.kb),
            record,
            replace(observation, claims=observation.claims + (invalid_claim,)),
        )


class MetricCurrencyAndCollectorTests(unittest.TestCase):
    def test_tcgdex_aliases_deduplicate_or_reject_per_semantic_metric(self):
        cases = (
            ("low", "lowPrice", 10, 10, "TCGPLAYER_LOW:GENERIC", True),
            ("low", "lowPrice", 10, 11, "TCGPLAYER_LOW:GENERIC", False),
            ("market", "marketPrice", 12, 12, "TCGPLAYER_MARKET:GENERIC", True),
            ("market", "marketPrice", 12, 13, "TCGPLAYER_MARKET:GENERIC", False),
        )
        for left, right, left_value, right_value, metric, persists in cases:
            with self.subTest(left=left, conflict=not persists):
                batch = normalize_tcgdex(
                    tcgdex_record(
                        {
                            "tcgplayer": {
                                "unit": "USD",
                                left: left_value,
                                right: right_value,
                            }
                        }
                    )
                )
                names = [item.fact["metric_name"] for item in batch.observations]
                self.assertEqual(names.count(metric), int(persists))
                self.assertEqual(batch.metric_alias_conflicts, int(not persists))

    def test_tcgdex_alias_conflict_preserves_other_metrics_and_segments(self):
        batch = normalize_tcgdex(
            tcgdex_record(
                {
                    "tcgplayer": {
                        "unit": "USD",
                        "holofoil": {
                            "low": 10,
                            "lowPrice": 11,
                            "marketPrice": 12,
                        },
                        "reverseHolofoil": {
                            "low": 8,
                            "lowPrice": 8,
                        },
                    }
                }
            )
        )
        names = {item.fact["metric_name"] for item in batch.observations}
        self.assertNotIn("TCGPLAYER_LOW:HOLOFOIL", names)
        self.assertIn("TCGPLAYER_MARKET:HOLOFOIL", names)
        self.assertIn("TCGPLAYER_LOW:REVERSEHOLOFOIL", names)
        self.assertEqual(batch.metric_alias_conflicts, 1)
        self.assertTrue(
            all(
                item.observation_type == ObservationType.PROVIDER_METRIC_OBSERVATION
                for item in batch.observations
            )
        )

    def test_currency_is_normalized_only_within_supported_contract(self):
        for raw, expected, rejected in (
            (" eur ", "EUR", 0),
            ("CHF", "CHF", 0),
            ("BAD", None, 1),
            ("EURO", None, 1),
            ("US$", None, 1),
        ):
            with self.subTest(currency=raw):
                payload = gcc_payload(currency=raw)
                batch = normalize_gcc(gcc_record(payload))
                prices = batch.observations[0].prices
                self.assertEqual(prices[0].currency if prices else None, expected)
                self.assertEqual(batch.monetary_facts_rejected, rejected)
        inferred = normalize_gcc(gcc_record(gcc_payload())).observations[0].prices[0]
        self.assertEqual(inferred.currency, "EUR")
        conflicting_gcc = normalize_gcc(
            gcc_record(gcc_payload(currency="EUR", currencyCode="BAD"))
        )
        self.assertEqual(conflicting_gcc.observations[0].prices, ())
        self.assertEqual(conflicting_gcc.monetary_facts_rejected, 1)

        tcgdex_missing = normalize_tcgdex(
            tcgdex_record({"cardmarket": {"low": 10}, "tcgplayer": {"low": 11}})
        )
        self.assertEqual(
            {item.fact["currency"] for item in tcgdex_missing.observations},
            {"EUR", "USD"},
        )
        tcgdex_invalid = normalize_tcgdex(
            tcgdex_record(
                {"tcgplayer": {"unit": "USD", "currency": "BAD", "low": 10}}
            )
        )
        self.assertEqual(tcgdex_invalid.observations, ())
        self.assertEqual(tcgdex_invalid.monetary_facts_rejected, 1)

    class FakeClock:
        def __init__(self):
            self.now = 0.0
            self.sleeps: list[float] = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    class FakeResponse:
        def __init__(self, payload, status_code=200, headers=None):
            self.payload = payload
            self.status_code = status_code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

        def json(self):
            return self.payload

    def test_gcc_crawl_is_paced_and_batch_bounded(self):
        clock = self.FakeClock()
        pages = [
            self.FakeResponse(
                {
                    "info": {"currentPage": 1, "nextPage": 2},
                    "results": [gcc_payload("one"), gcc_payload("two")],
                }
            ),
            self.FakeResponse(
                {
                    "info": {"currentPage": 2, "nextPage": None},
                    "results": [gcc_payload("three")],
                }
            ),
        ]
        collector = GCCMarketplaceCollector(
            http_get=lambda *args, **kwargs: pages.pop(0),
            sleeper=clock.sleep,
            monotonic=clock.monotonic,
            min_request_interval_seconds=0.25,
        )
        result = collector.collect("fixed", max_records=3)
        self.assertEqual(len(result.records), 3)
        self.assertFalse(result.crawl_truncated)
        self.assertTrue(any(delay >= 0.25 for delay in clock.sleeps))

        calls = []
        bounded = GCCMarketplaceCollector(
            http_get=lambda *args, **kwargs: (
                calls.append(1)
                or self.FakeResponse(
                    {
                        "info": {"currentPage": 1, "nextPage": 2},
                        "results": [
                            gcc_payload("one"),
                            gcc_payload("two"),
                            gcc_payload("three"),
                        ],
                    }
                )
            ),
            sleeper=lambda _seconds: None,
        )
        truncated = bounded.collect("fixed", max_records=2)
        self.assertEqual(len(truncated.records), 2)
        self.assertTrue(truncated.crawl_truncated)
        self.assertEqual(len(calls), 1)

    def test_gcc_retries_429_once_and_respects_retry_after(self):
        clock = self.FakeClock()
        responses = [
            self.FakeResponse({}, 429, {"Retry-After": "1"}),
            self.FakeResponse(
                {"info": {"currentPage": 1, "nextPage": None}, "results": []}
            ),
        ]
        collector = GCCMarketplaceCollector(
            http_get=lambda *args, **kwargs: responses.pop(0),
            sleeper=clock.sleep,
            monotonic=clock.monotonic,
            min_request_interval_seconds=0.25,
            max_retries=1,
        )
        result = collector.collect("fixed")
        self.assertEqual(result.records, ())
        self.assertIn(1.0, clock.sleeps)
        self.assertEqual(len(responses), 0)

    def test_truncated_crawl_is_reported_by_sidecar_diagnostics(self):
        with KnowledgeBase.open() as kb:
            sidecar = ShadowSidecar(ShadowKnowledgePersistence(kb))
            sidecar.run_source(
                "bounded", lambda: CollectionResult((), crawl_truncated=True)
            )
            self.assertEqual(sidecar.diagnostics.crawl_batches_truncated, 1)

    def test_gcc_limits_and_cli_reject_pathological_values(self):
        collector = GCCMarketplaceCollector(
            http_get=lambda *args, **kwargs: self.fail("network must not be called")
        )
        for keyword, value in (
            ("page_size", 0),
            ("page_size", -1),
            ("max_pages", 10**30),
            ("max_records", 10**30),
        ):
            with self.subTest(keyword=keyword, value=value):
                with self.assertRaises(ValueError):
                    collector.collect("fixed", **{keyword: value})
        for option, value in (
            ("--page-size", "0"),
            ("--max-pages", "-1"),
            ("--max-records", str(10**30)),
        ):
            with self.subTest(option=option):
                with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                    sidecar_main(["--gcc-fixture", "unused.json", option, value])


if __name__ == "__main__":
    unittest.main()
