from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import robot_kb.migrations as migrations
from robot_kb import (
    KnowledgeBase,
    KnowledgeBaseError,
    ObservationRelationshipType,
    ObservationType,
    ProvenanceError,
    ResolutionState,
    VariantError,
)


T0 = "2026-08-14T08:00:00+02:00"
T1 = "2026-08-14T09:00:00+02:00"
T2 = "2026-08-14T10:00:00+02:00"


def unique_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class FinalIntegrityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()

    def tearDown(self) -> None:
        self.kb.close()

    def source(self, code: str, role: str) -> str:
        return self.kb.create_source_system(code, code.upper(), role)

    def family(self, key: str = "base", number: str = "4/102"):
        set_id = self.kb.create_canonical_set(key, key.upper())
        family_id = self.kb.create_card_family(set_id, number, "Charizard")
        localized_id = self.kb.create_localized_card(
            family_id, "en", "Charizard", localized_set_name=key.upper()
        )
        return family_id, localized_id

    def card(self):
        family_id, localized_id = self.family()
        profile_id = self.kb.create_variant_profile(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWED",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_id)
        return self.kb.create_canonical_card(localized_id, profile_id)

    def sale(self, source_id: str, native_id: str, status: str, observed_at: str):
        return self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            source_id,
            native_id,
            observed_at=observed_at,
            fact={"transaction_status": status},
        )

    def raw_observation(
        self,
        source_id: str,
        observation_type: ObservationType,
        *,
        native_id: str,
        upstream_market_system_id=None,
        upstream_event_object_id=None,
    ) -> str:
        observation_id = unique_id("observation")
        self.kb.connection.execute(
            """
            INSERT INTO market_observation(
                id, observation_type, source_system_id,
                upstream_market_system_id, source_native_record_id,
                upstream_event_object_id, idempotency_key, content_sha256,
                event_time_precision, observed_at, ingested_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'UNKNOWN', ?, ?, ?)
            """,
            (
                observation_id,
                observation_type.value,
                source_id,
                upstream_market_system_id,
                native_id,
                upstream_event_object_id,
                unique_id("obskey"),
                uuid.uuid4().hex,
                T0,
                T0,
                T0,
            ),
        )
        return observation_id


class CancellationMeaningTests(FinalIntegrityTestCase):
    def test_completed_sale_cannot_cancel_or_void(self):
        source = self.source("market", "MARKET")
        target = self.sale(source, "event", "COMPLETED", T0)
        completed_action = self.sale(source, "event", "COMPLETED", T1)
        for relationship in (
            ObservationRelationshipType.CANCELS,
            ObservationRelationshipType.VOIDS,
        ):
            with self.subTest(relationship=relationship.value):
                with self.assertRaises(KnowledgeBaseError):
                    self.kb.add_observation_relationship(
                        completed_action, target, relationship
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    self.kb.connection.execute(
                        """
                        INSERT INTO observation_relationship(
                            id, from_observation_id, to_observation_id,
                            relationship_type, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            unique_id("orel"),
                            completed_action,
                            target,
                            relationship.value,
                            T2,
                        ),
                    )

    def test_valid_cancellation_and_void_actions_are_explicit(self):
        source = self.source("market", "MARKET")
        target = self.sale(source, "event", "COMPLETED", T0)
        cancelled = self.sale(source, "event", "CANCELLED", T1)
        voided = self.sale(source, "event", "VOIDED", T2)
        cancel_edge = self.kb.add_observation_relationship(
            cancelled, target, ObservationRelationshipType.CANCELS
        )
        void_edge = self.kb.add_observation_relationship(
            voided, target, ObservationRelationshipType.VOIDS
        )
        self.assertTrue(cancel_edge.startswith("orel_"))
        self.assertTrue(void_edge.startswith("orel_"))

    def test_one_action_cannot_both_cancel_and_void_same_target(self):
        source = self.source("market", "MARKET")
        target = self.sale(source, "event", "COMPLETED", T0)
        action = self.sale(source, "event", "CANCELLED", T1)
        self.kb.add_observation_relationship(
            action, target, ObservationRelationshipType.CANCELS
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO observation_relationship(
                    id, from_observation_id, to_observation_id,
                    relationship_type, created_at
                ) VALUES (?, ?, ?, 'VOIDS', ?)
                """,
                (unique_id("orel"), action, target, T2),
            )


class UpstreamRoleTests(FinalIntegrityTestCase):
    def test_external_upstream_fields_are_paired_and_market_scoped(self):
        provider = self.source("provider", "PROVIDER")
        market = self.source("market", "MARKET")
        with self.assertRaises(KnowledgeBaseError):
            self.kb.create_external_object(
                provider,
                "LISTING",
                "provider-1",
                upstream_market_system_id=market,
            )
        with self.assertRaises(KnowledgeBaseError):
            self.kb.create_external_object(
                provider,
                "LISTING",
                "provider-2",
                upstream_market_system_id=provider,
                upstream_native_id="market-2",
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO external_object(
                    id, source_system_id, object_type, source_native_id,
                    upstream_market_system_id, created_at
                ) VALUES (?, ?, 'LISTING', 'direct-1', ?, ?)
                """,
                (unique_id("extobj"), provider, market, T0),
            )
        valid = self.kb.create_external_object(
            provider,
            "LISTING",
            "provider-3",
            upstream_market_system_id=market,
            upstream_native_id="market-3",
        )
        self.assertTrue(valid.startswith("extobj_"))

    def test_observation_upstream_role_is_checked_without_event_object(self):
        provider = self.source("provider", "PROVIDER")
        with self.assertRaises(KnowledgeBaseError):
            self.kb.append_market_observation(
                ObservationType.PROVIDER_METRIC_OBSERVATION,
                provider,
                "metric-1",
                upstream_market_system_id=provider,
                observed_at=T0,
                fact={"metric_name": "MARKET"},
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw_observation(
                provider,
                ObservationType.PROVIDER_METRIC_OBSERVATION,
                native_id="metric-2",
                upstream_market_system_id=provider,
            )

    def test_event_object_must_match_declared_upstream_market(self):
        provider = self.source("provider", "PROVIDER")
        ebay = self.source("ebay", "MARKET")
        cardmarket = self.source("cardmarket", "MARKET")
        event = self.kb.create_external_object(ebay, "SALE_EVENT", "123")
        with self.assertRaises(KnowledgeBaseError):
            self.kb.append_market_observation(
                ObservationType.SALE_TRANSACTION,
                provider,
                "sale-1",
                upstream_market_system_id=cardmarket,
                upstream_event_object_id=event,
                observed_at=T0,
                fact={"transaction_status": "COMPLETED"},
            )


class ObservationIdentityTraceabilityTests(FinalIntegrityTestCase):
    def test_same_card_does_not_make_unrelated_subject_legitimate(self):
        card = self.card()
        provider = self.source("provider", "PROVIDER")
        record_a = self.kb.append_source_record(
            provider, "a", {"row": "a"}, retrieved_at=T0
        )
        record_b = self.kb.append_source_record(
            provider, "b", {"row": "b"}, retrieved_at=T0
        )
        observation = self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            provider,
            "sale-a",
            source_record_id=record_a,
            canonical_card_id=card,
            observed_at=T1,
            fact={"transaction_status": "COMPLETED"},
        )
        subject = self.kb.create_identity_subject(
            "PROVIDER_RESPONSE", source_record_id=record_b
        )
        resolution = self.kb.create_identity_resolution(
            subject, ResolutionState.PROVEN, canonical_card_id=card
        )
        with self.assertRaises(ProvenanceError):
            self.kb.link_observation_identity(
                observation,
                resolution,
                canonical_card_id=card,
                link_role="RESOLVED_AS",
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO observation_identity_link(
                    id, observation_id, identity_resolution_id,
                    canonical_card_id, link_role, created_at
                ) VALUES (?, ?, ?, ?, 'RESOLVED_AS', ?)
                """,
                (unique_id("oilink"), observation, resolution, card, T2),
            )

    def test_source_record_subject_allows_later_re_resolution(self):
        card = self.card()
        provider = self.source("provider", "PROVIDER")
        record = self.kb.append_source_record(
            provider, "row", {"row": 1}, retrieved_at=T0
        )
        observation = self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            provider,
            "sale-row",
            source_record_id=record,
            canonical_card_id=card,
            observed_at=T1,
            fact={"transaction_status": "COMPLETED"},
        )
        subject = self.kb.create_identity_subject(
            "PROVIDER_RESPONSE", source_record_id=record
        )
        first = self.kb.create_identity_resolution(
            subject, ResolutionState.SUPPORTED, canonical_card_id=card
        )
        second = self.kb.create_identity_resolution(
            subject,
            ResolutionState.PROVEN,
            canonical_card_id=card,
            supersedes_resolution_id=first,
        )
        links = {
            self.kb.link_observation_identity(
                observation,
                resolution,
                canonical_card_id=card,
                link_role="RESOLVED_AS",
            )
            for resolution in (first, second)
        }
        self.assertEqual(len(links), 2)

    def test_source_native_external_object_subject_is_legitimate(self):
        card = self.card()
        market = self.source("market", "MARKET")
        object_id = self.kb.create_external_object(market, "SALE_EVENT", "event-1")
        subject = self.kb.create_identity_subject(
            "SALE_EVENT", external_object_id=object_id
        )
        resolution = self.kb.create_identity_resolution(
            subject, ResolutionState.PROVEN, canonical_card_id=card
        )
        observation = self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            market,
            "event-1",
            canonical_card_id=card,
            observed_at=T0,
            fact={"transaction_status": "COMPLETED"},
        )
        link = self.kb.link_observation_identity(
            observation,
            resolution,
            canonical_card_id=card,
            link_role="RESOLVED_AS",
        )
        self.assertTrue(link.startswith("oilink_"))


class VariantClosureTests(FinalIntegrityTestCase):
    def insert_card_direct(self, localized_id: str, profile_id: str) -> None:
        semantic_key = self.kb.connection.execute(
            "SELECT semantic_key FROM variant_profile WHERE id = ?", (profile_id,)
        ).fetchone()[0]
        self.kb.connection.execute(
            """
            INSERT INTO canonical_card(
                id, localized_card_id, variant_profile_id,
                exact_comparison_key, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                unique_id("card"),
                localized_id,
                profile_id,
                f"cardcmp|{localized_id}|{semantic_key}",
                T0,
            ),
        )

    def test_unknown_applicability_blocks_exact_canonical_card(self):
        family, localized = self.family()
        profile = self.kb.create_variant_profile({"finish": "HOLO"})
        self.kb.set_family_variant_applicability(family, "finish", "UNKNOWN")
        self.kb.allow_variant_profile(family, profile)
        with self.assertRaises(VariantError):
            self.kb.create_canonical_card(localized, profile)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_card_direct(localized, profile)

    def test_all_registered_applicability_closed_allows_exact_card(self):
        family, localized = self.family()
        profile = self.kb.create_variant_profile(
            {"edition_stamp": "FIRST_EDITION"}
        )
        self.kb.set_family_variant_applicability(
            family, "edition_stamp", "APPLICABLE"
        )
        self.kb.set_family_variant_applicability(
            family, "promo_type", "NOT_APPLICABLE"
        )
        self.kb.allow_variant_profile(family, profile)
        card = self.kb.create_canonical_card(localized, profile)
        self.assertTrue(card.startswith("card_"))

    def test_applicable_unknown_value_cannot_masquerade_as_exact(self):
        family, localized = self.family()
        profile = self.kb.create_variant_profile({"finish": "UNKNOWN"})
        self.kb.set_family_variant_applicability(family, "finish", "APPLICABLE")
        self.kb.allow_variant_profile(family, profile)
        with self.assertRaises(VariantError):
            self.kb.create_canonical_card(localized, profile)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_card_direct(localized, profile)


class ExactFXTests(FinalIntegrityTestCase):
    def draft_with_price(self, amount: int = 1):
        source = self.source("market", "MARKET")
        observation = self.raw_observation(
            source,
            ObservationType.SALE_TRANSACTION,
            native_id="fx-sale",
        )
        price = unique_id("price")
        self.kb.connection.execute(
            """
            INSERT INTO price_component(
                id, observation_id, component_type, amount_minor, currency,
                knowledge_state, inclusion_state, created_at
            ) VALUES (?, ?, 'TOTAL', ?, 'USD', 'KNOWN', 'INCLUDED', ?)
            """,
            (price, observation, amount, T0),
        )
        return observation, price

    def insert_normalization(
        self,
        observation: str,
        price: str,
        *,
        amount: int,
        rate: str,
        numerator: int,
        denominator: int,
        target: int,
    ) -> None:
        self.kb.connection.execute(
            """
            INSERT INTO fx_normalization(
                id, observation_id, component_type, original_amount_minor,
                original_currency, fx_rate_decimal, rate_source,
                rate_effective_date, target_currency, target_amount_minor,
                created_at, price_component_id, rate_numerator, rate_denominator
            ) VALUES (?, ?, 'TOTAL', ?, 'USD', ?, 'TEST', '2026-08-14',
                      'EUR', ?, ?, ?, ?, ?)
            """,
            (
                unique_id("fxnorm"),
                observation,
                amount,
                rate,
                target,
                T0,
                price,
                numerator,
                denominator,
            ),
        )

    def test_direct_sql_rejects_malformed_zero_and_negative_rates(self):
        observation, price = self.draft_with_price()
        for rate, numerator, denominator in (
            ("abc", 1, 1),
            ("0", 0, 1),
            ("-1", -1, 1),
        ):
            with self.subTest(rate=rate):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert_normalization(
                        observation,
                        price,
                        amount=1,
                        rate=rate,
                        numerator=numerator,
                        denominator=denominator,
                        target=1,
                    )

        fx_source = self.source("fx-provider", "PROVIDER")
        rate_observation = self.raw_observation(
            fx_source,
            ObservationType.FX_RATE_OBSERVATION,
            native_id="bad-rate",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO fx_rate_observation(
                    observation_id, base_currency, quote_currency,
                    rate_decimal, effective_date, rate_source,
                    rate_numerator, rate_denominator
                ) VALUES (?, 'USD', 'EUR', 'abc', '2026-08-14', 'TEST', 1, 1)
                """,
                (rate_observation,),
            )

    def test_direct_sql_enforces_exact_target_and_round_half_up(self):
        observation, price = self.draft_with_price()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_normalization(
                observation,
                price,
                amount=1,
                rate="0.5",
                numerator=5,
                denominator=10,
                target=0,
            )
        self.insert_normalization(
            observation,
            price,
            amount=1,
            rate="0.5",
            numerator=5,
            denominator=10,
            target=1,
        )
        row = self.kb.connection.execute(
            "SELECT * FROM fx_normalization WHERE observation_id = ?",
            (observation,),
        ).fetchone()
        self.assertEqual(row["target_amount_minor"], 1)
        self.assertEqual((row["rate_numerator"], row["rate_denominator"]), (5, 10))

    def test_direct_sql_rejects_product_outside_exact_integer_range(self):
        observation, price = self.draft_with_price(amount=10)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_normalization(
                observation,
                price,
                amount=10,
                rate="999999999999999999",
                numerator=999999999999999999,
                denominator=1,
                target=0,
            )

    def test_repository_fx_rate_fact_persists_exact_rational(self):
        source = self.source("ecb", "PROVIDER")
        observation = self.kb.append_market_observation(
            ObservationType.FX_RATE_OBSERVATION,
            source,
            "usd-eur",
            observed_at=T0,
            fact={
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate_decimal": "9.10E-1",
                "effective_date": "2026-08-14",
                "rate_source": "ECB",
            },
        )
        row = self.kb.connection.execute(
            "SELECT * FROM fx_rate_observation WHERE observation_id = ?",
            (observation,),
        ).fetchone()
        self.assertEqual(row["rate_decimal"], "0.910")
        self.assertEqual(
            (row["rate_numerator"], row["rate_denominator"]), (910, 1000)
        )


class FinalMigrationTests(unittest.TestCase):
    def copy_migrations(self, destination: Path, versions) -> None:
        destination.mkdir()
        names = {
            1: "0001_initial.sql",
            2: "0002_integrity_hardening.sql",
            3: "0003_final_integrity_closure.sql",
        }
        for version in versions:
            shutil.copy2(
                migrations.MIGRATION_DIRECTORY / names[version],
                destination / names[version],
            )

    def schema_two_fx_rate(self, root: Path, rate_decimal: str):
        only_two = root / "only-two"
        self.copy_migrations(only_two, (1, 2))
        connection = migrations.connect_database(root / "legacy.sqlite3")
        with mock.patch.object(migrations, "MIGRATION_DIRECTORY", only_two):
            migrations.apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO source_system(id, code, name, system_role, created_at)
            VALUES ('source_ecb', 'ecb', 'ECB', 'PROVIDER', ?)
            """,
            (T0,),
        )
        connection.execute(
            """
            INSERT INTO market_observation(
                id, observation_type, source_system_id, source_native_record_id,
                idempotency_key, content_sha256, event_time_precision,
                observed_at, ingested_at, created_at
            ) VALUES ('observation_rate', 'FX_RATE_OBSERVATION', 'source_ecb',
                      'usd-eur', 'obskey_rate', 'hash', 'UNKNOWN', ?, ?, ?)
            """,
            (T0, T0, T0),
        )
        connection.execute(
            """
            INSERT INTO fx_rate_observation(
                observation_id, base_currency, quote_currency,
                rate_decimal, effective_date, rate_source
            ) VALUES ('observation_rate', 'USD', 'EUR', ?, '2026-08-14', 'ECB')
            """,
            (rate_decimal,),
        )
        connection.execute(
            """
            UPDATE market_observation
            SET lifecycle_state = 'SEALED', sealed_at = ?
            WHERE id = 'observation_rate'
            """,
            (T1,),
        )
        connection.execute(
            """
            INSERT INTO market_observation(
                id, observation_type, source_system_id, source_native_record_id,
                idempotency_key, content_sha256, event_time_precision,
                observed_at, ingested_at, created_at
            ) VALUES ('observation_sale', 'SALE_TRANSACTION', 'source_ecb',
                      'sale', 'obskey_sale', 'sale-hash', 'UNKNOWN', ?, ?, ?)
            """,
            (T0, T0, T0),
        )
        connection.execute(
            """
            INSERT INTO sale_transaction(observation_id, transaction_status)
            VALUES ('observation_sale', 'COMPLETED')
            """
        )
        connection.execute(
            """
            INSERT INTO price_component(
                id, observation_id, component_type, amount_minor, currency,
                knowledge_state, inclusion_state, created_at
            ) VALUES ('price_legacy', 'observation_sale', 'TOTAL', 1, 'USD',
                      'KNOWN', 'INCLUDED', ?)
            """,
            (T0,),
        )
        connection.execute(
            """
            INSERT INTO fx_normalization(
                id, observation_id, component_type, original_amount_minor,
                original_currency, fx_rate_decimal, rate_observation_id,
                rate_source, rate_effective_date, target_currency,
                target_amount_minor, created_at, price_component_id
            ) VALUES ('fxnorm_legacy', 'observation_sale', 'TOTAL', 1, 'USD', ?,
                      'observation_rate', 'ECB', '2026-08-14', 'EUR', 1, ?,
                      'price_legacy')
            """,
            (rate_decimal, T0),
        )
        connection.execute(
            """
            UPDATE market_observation
            SET lifecycle_state = 'SEALED', sealed_at = ?
            WHERE id = 'observation_sale'
            """,
            (T1,),
        )
        return connection

    def test_existing_valid_0002_database_upgrades_to_0003(self):
        with tempfile.TemporaryDirectory(prefix="gcc-kb-valid-v2-") as directory:
            connection = self.schema_two_fx_rate(Path(directory), "0.500")
            try:
                migrations.apply_migrations(connection)
                row = connection.execute(
                    "SELECT rate_numerator, rate_denominator FROM fx_rate_observation"
                ).fetchone()
                self.assertEqual(tuple(row), (500, 1000))
                normalization = connection.execute(
                    "SELECT rate_numerator, rate_denominator FROM fx_normalization"
                ).fetchone()
                self.assertEqual(tuple(normalization), (500, 1000))
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )],
                    [1, 2, 3],
                )
            finally:
                connection.close()

    def test_corrupt_0002_fx_rate_fails_0003_atomically(self):
        with tempfile.TemporaryDirectory(prefix="gcc-kb-corrupt-v2-") as directory:
            connection = self.schema_two_fx_rate(Path(directory), "abc")
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    migrations.apply_migrations(connection)
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )],
                    [1, 2],
                )
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(fx_rate_observation)"
                    )
                }
                self.assertNotIn("rate_numerator", columns)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
