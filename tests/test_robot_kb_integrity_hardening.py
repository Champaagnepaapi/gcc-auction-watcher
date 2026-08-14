from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import robot_kb.migrations as migrations
from robot_kb import (
    ClaimRole,
    Directness,
    EvidenceMethod,
    FXNormalization,
    IdempotencyConflict,
    InclusionState,
    KnowledgeBase,
    KnowledgeBaseError,
    ObservationRelationshipType,
    ObservationType,
    OpportunityState,
    PriceComponent,
    PriceKnowledge,
    ProvenanceError,
    ResolutionState,
    SourceKind,
    VariantError,
    VariantValuationScenario,
    classify_opportunity,
)
from robot_kb.migrations import MigrationError


T0 = "2026-08-14T08:00:00+02:00"
T1 = "2026-08-14T09:00:00+02:00"
T2 = "2026-08-14T10:00:00+02:00"


def unique_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class IntegrityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()

    def tearDown(self) -> None:
        self.kb.close()

    def source(self, code: str = "gcc", role: str = "MARKET") -> str:
        return self.kb.create_source_system(code, code.upper(), role)

    def family(self):
        set_id = self.kb.create_canonical_set("pokemon-base-set", "Base Set")
        family_id = self.kb.create_card_family(set_id, "4/102", "Charizard")
        localized_id = self.kb.create_localized_card(
            family_id, "en", "Charizard", localized_set_name="Base Set"
        )
        return family_id, localized_id

    def card(self, assignments=None):
        family_id, localized_id = self.family()
        profile_id = self.kb.create_variant_profile(
            assignments
            or {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWED",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_id)
        card_id = self.kb.create_canonical_card(localized_id, profile_id)
        return card_id, profile_id

    def two_cards(self):
        card_a, profile_a = self.card(
            {
                "edition_stamp": "FIRST_EDITION",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        family_id, localized_id = self.family()
        profile_b = self.kb.create_variant_profile(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_b)
        card_b = self.kb.create_canonical_card(localized_id, profile_b)
        return card_a, profile_a, card_b, profile_b

    def sale(
        self,
        source_id: str,
        native_id: str,
        observed_at: str,
        *,
        canonical_card_id=None,
        revision_of_observation_id=None,
    ) -> str:
        return self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            source_id,
            native_id,
            observed_at=observed_at,
            event_at=observed_at,
            event_time_precision="EXACT",
            canonical_card_id=canonical_card_id,
            revision_of_observation_id=revision_of_observation_id,
            fact={
                "sale_occurred_at": observed_at,
                "transaction_status": "COMPLETED",
            },
            prices=[PriceComponent("TOTAL", 10_000, "EUR")],
        )

    def raw_observation(
        self,
        source_id: str,
        observation_type: ObservationType,
        *,
        native_id=None,
        revision_of_observation_id=None,
        upstream_market_system_id=None,
        upstream_event_object_id=None,
        canonical_card_id=None,
    ) -> str:
        observation_id = unique_id("observation")
        self.kb.connection.execute(
            """
            INSERT INTO market_observation(
                id, observation_type, source_system_id,
                upstream_market_system_id, source_native_record_id,
                upstream_event_object_id, canonical_card_id,
                idempotency_key, content_sha256, event_time_precision,
                observed_at, ingested_at, revision_of_observation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNKNOWN', ?, ?, ?, ?)
            """,
            (
                observation_id,
                observation_type.value,
                source_id,
                upstream_market_system_id,
                native_id or unique_id("native"),
                upstream_event_object_id,
                canonical_card_id,
                unique_id("obskey"),
                uuid.uuid4().hex,
                T0,
                T0,
                revision_of_observation_id,
                T0,
            ),
        )
        return observation_id

    def provenance_subject(self, suffix="one"):
        source_id = self.source("provider", "PROVIDER")
        record_id = self.kb.append_source_record(
            source_id,
            f"record-{suffix}",
            {"payload": suffix},
            retrieved_at=T0,
        )
        subject_id = self.kb.create_identity_subject(
            "PROVIDER_RESPONSE", source_record_id=record_id
        )
        return record_id, subject_id


class ProvenanceIntegrityTests(IntegrityTestCase):
    def test_unknown_null_evidence_cannot_fabricate_proven_value(self):
        record_id, subject_id = self.provenance_subject()
        claim_id = self.kb.append_field_claim(
            record_id,
            subject_id,
            "edition_stamp",
            None,
            source_kind=SourceKind.PROVIDER,
            evidence_method=EvidenceMethod.STRUCTURED_FIELD,
            directness=Directness.DIRECT_ASSERTION,
            resolution_state=ResolutionState.UNKNOWN,
        )

        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject_id,
                "edition_stamp",
                ResolutionState.PROVEN,
                value="NO_FIRST_EDITION_STAMP",
                based_on_claim_id=claim_id,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO field_resolution(
                    id, identity_subject_id, field_name, resolved_value_json,
                    resolution_state, based_on_claim_id, created_at
                ) VALUES (?, ?, 'edition_stamp', ?, 'PROVEN', ?, ?)
                """,
                (
                    unique_id("fres"),
                    subject_id,
                    json.dumps("NO_FIRST_EDITION_STAMP"),
                    claim_id,
                    T0,
                ),
            )

    def test_positive_resolution_requires_exact_matching_positive_evidence(self):
        record_id, subject_id = self.provenance_subject()
        claim_id = self.kb.append_field_claim(
            record_id,
            subject_id,
            "finish",
            "HOLO",
            source_kind=SourceKind.PROVIDER,
            evidence_method=EvidenceMethod.STRUCTURED_FIELD,
            directness=Directness.DIRECT_ASSERTION,
            resolution_state=ResolutionState.PROVEN,
        )
        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject_id,
                "finish",
                ResolutionState.PROVEN,
                value="NON_HOLO",
                based_on_claim_id=claim_id,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO field_resolution(
                    id, identity_subject_id, field_name, resolved_value_json,
                    resolution_state, based_on_claim_id, created_at
                ) VALUES (?, ?, 'finish', ?, 'PROVEN', ?, ?)
                """,
                (
                    unique_id("fres"),
                    subject_id,
                    json.dumps("NON_HOLO"),
                    claim_id,
                    T0,
                ),
            )

    def test_request_targets_and_conflicts_cannot_select_truth(self):
        record_id, subject_id = self.provenance_subject()
        target_id = self.kb.append_field_claim(
            record_id,
            subject_id,
            "promo_type",
            "NON_PROMO",
            source_kind=SourceKind.PROVIDER,
            evidence_method=EvidenceMethod.STRUCTURED_FIELD,
            directness=Directness.DIRECT_ASSERTION,
            resolution_state=ResolutionState.UNKNOWN,
            claim_role=ClaimRole.REQUEST_TARGET,
        )
        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject_id,
                "promo_type",
                ResolutionState.SUPPORTED,
                value="NON_PROMO",
                based_on_claim_id=target_id,
            )
        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject_id,
                "promo_type",
                ResolutionState.CONFLICT,
                value="NON_PROMO",
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO field_resolution(
                    id, identity_subject_id, field_name, resolved_value_json,
                    resolution_state, created_at
                ) VALUES (?, ?, 'promo_type', ?, 'CONFLICT', ?)
                """,
                (
                    unique_id("fres"),
                    subject_id,
                    json.dumps("NON_PROMO"),
                    T0,
                ),
            )

    def test_field_supersession_stays_in_subject_and_field_and_is_acyclic(self):
        _, subject_a = self.provenance_subject("a")
        _, subject_b = self.provenance_subject("b")
        first = self.kb.resolve_field(
            subject_a, "finish", ResolutionState.UNKNOWN
        )
        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject_a,
                "edition_stamp",
                ResolutionState.UNKNOWN,
                supersedes_resolution_id=first,
            )
        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject_b,
                "finish",
                ResolutionState.UNKNOWN,
                supersedes_resolution_id=first,
            )
        second = self.kb.resolve_field(
            subject_a,
            "finish",
            ResolutionState.UNKNOWN,
            supersedes_resolution_id=first,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "UPDATE field_resolution SET supersedes_resolution_id = ? WHERE id = ?",
                (second, first),
            )


class ObservationLifecycleTests(IntegrityTestCase):
    def test_incomplete_observation_cannot_seal_or_count_as_fact(self):
        source_id = self.source()
        draft = self.raw_observation(source_id, ObservationType.SALE_TRANSACTION)
        self.assertEqual(self.kb.observation_count(), 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                UPDATE market_observation
                SET lifecycle_state = 'SEALED', sealed_at = ? WHERE id = ?
                """,
                (T0, draft),
            )
        self.assertEqual(self.kb.fetch_observation(draft)["lifecycle_state"], "DRAFT")

    def test_subtype_price_and_fx_children_cannot_be_added_after_seal(self):
        source_id = self.source()
        observation = self.sale(source_id, "sealed-sale", T0)
        price_id = self.kb.price_components(observation)[0]["id"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO listing_snapshot(observation_id, snapshot_status)
                VALUES (?, 'ACTIVE')
                """,
                (observation,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO price_component(
                    id, observation_id, component_type, amount_minor, currency,
                    knowledge_state, inclusion_state, created_at
                ) VALUES (?, ?, 'SHIPPING', 100, 'EUR', 'KNOWN', 'EXCLUDED', ?)
                """,
                (unique_id("price"), observation, T1),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO fx_normalization(
                    id, observation_id, component_type, original_amount_minor,
                    original_currency, fx_rate_decimal, rate_source,
                    rate_effective_date, target_currency, target_amount_minor,
                    created_at, price_component_id
                ) VALUES (?, ?, 'TOTAL', 10000, 'EUR', '1.1', 'TEST',
                          '2026-08-14', 'USD', 11000, ?, ?)
                """,
                (unique_id("fxnorm"), observation, T1, price_id),
            )

    def test_repository_returns_only_complete_sealed_observations(self):
        source_id = self.source()
        observation = self.sale(source_id, "complete-sale", T0)
        row = self.kb.fetch_observation(observation)
        self.assertEqual(row["lifecycle_state"], "SEALED")
        self.assertIsNotNone(row["sealed_at"])
        self.assertEqual(self.kb.observation_count(), 1)


class RelationshipIntegrityTests(IntegrityTestCase):
    def test_revision_requires_compatible_event_and_consistent_projection(self):
        source_id = self.source()
        old = self.sale(source_id, "event-one", T0)
        with self.assertRaises(KnowledgeBaseError):
            self.sale(
                source_id,
                "unrelated-event",
                T1,
                revision_of_observation_id=old,
            )

        other = self.sale(source_id, "event-one", T1)
        draft = self.raw_observation(
            source_id,
            ObservationType.SALE_TRANSACTION,
            native_id="event-one",
            revision_of_observation_id=old,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO observation_relationship(
                    id, from_observation_id, to_observation_id,
                    relationship_type, created_at
                ) VALUES (?, ?, ?, 'REVISION_OF', ?)
                """,
                (unique_id("orel"), draft, other, T2),
            )

    def test_revision_cycles_and_multiple_targets_are_rejected(self):
        source_id = self.source()
        first = self.sale(source_id, "revision-chain", T0)
        second = self.sale(
            source_id,
            "revision-chain",
            T1,
            revision_of_observation_id=first,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO observation_relationship(
                    id, from_observation_id, to_observation_id,
                    relationship_type, created_at
                ) VALUES (?, ?, ?, 'REVISION_OF', ?)
                """,
                (unique_id("orel"), first, second, T2),
            )
        self.assertEqual(
            self.kb.fetch_observation(second)["revision_of_observation_id"], first
        )
        self.assertIsNotNone(self.kb.fetch_observation(first))

    def test_unrelated_events_cannot_cancel_or_void_each_other(self):
        source_id = self.source()
        first = self.sale(source_id, "event-a", T0)
        second = self.sale(source_id, "event-b", T1)
        for relationship in (
            ObservationRelationshipType.CANCELS,
            ObservationRelationshipType.VOIDS,
        ):
            with self.assertRaises(KnowledgeBaseError):
                self.kb.add_observation_relationship(first, second, relationship)

    def test_cancel_and_void_edges_cannot_form_cross_type_cycle(self):
        source_id = self.source()
        first = self.sale(source_id, "same-event", T0)
        second = self.sale(source_id, "same-event", T1)
        self.kb.add_observation_relationship(
            second, first, ObservationRelationshipType.CANCELS
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO observation_relationship(
                    id, from_observation_id, to_observation_id,
                    relationship_type, created_at
                ) VALUES (?, ?, ?, 'VOIDS', ?)
                """,
                (unique_id("orel"), first, second, T2),
            )


class LineageAndIdentityTests(IntegrityTestCase):
    def test_marketplace_scoping_and_upstream_ownership_are_enforced(self):
        ebay = self.source("ebay", "MARKET")
        gcc = self.source("gcc", "MARKET")
        provider = self.source("poketrace", "PROVIDER")
        ebay_event = self.kb.create_external_object(ebay, "SALE_EVENT", "123")
        gcc_event = self.kb.create_external_object(gcc, "SALE_EVENT", "123")
        self.assertNotEqual(ebay_event, gcc_event)

        with self.assertRaises(KnowledgeBaseError):
            self.kb.append_market_observation(
                ObservationType.SALE_TRANSACTION,
                provider,
                "provider-row",
                observed_at=T0,
                fact={"transaction_status": "COMPLETED"},
                upstream_market_system_id=gcc,
                upstream_event_object_id=ebay_event,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw_observation(
                provider,
                ObservationType.SALE_TRANSACTION,
                upstream_market_system_id=gcc,
                upstream_event_object_id=ebay_event,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "UPDATE source_system SET system_role = 'PROVIDER' WHERE id = ?",
                (ebay,),
            )

    def test_two_provider_facts_share_one_upstream_event_without_collapsing(self):
        ebay = self.source("ebay", "MARKET")
        poketrace = self.source("poketrace", "PROVIDER")
        pricecharting = self.source("pricecharting", "PROVIDER")
        event = self.kb.create_external_object(ebay, "SALE_EVENT", "123")
        observations = {
            self.kb.append_market_observation(
                ObservationType.SALE_TRANSACTION,
                provider,
                native,
                observed_at=observed,
                fact={"transaction_status": "COMPLETED"},
                upstream_market_system_id=ebay,
                upstream_event_object_id=event,
            )
            for provider, native, observed in (
                (poketrace, "pt-1", T0),
                (pricecharting, "pc-1", T1),
            )
        }
        self.assertEqual(len(observations), 2)
        upstream = {
            row[0]
            for row in self.kb.connection.execute(
                "SELECT upstream_event_object_id FROM market_observation"
            )
        }
        self.assertEqual(upstream, {event})

    def test_source_record_retrieval_lineage_is_preserved_and_idempotent(self):
        provider = self.source("provider", "PROVIDER")
        object_a = self.kb.create_external_object(provider, "RESPONSE", "a")
        object_b = self.kb.create_external_object(provider, "RESPONSE", "b")
        payload = {"same": "bytes"}
        record = self.kb.append_source_record(
            provider,
            "native-1",
            payload,
            retrieved_at=T0,
            source_updated_at=T0,
            external_object_id=object_a,
        )
        replay = self.kb.append_source_record(
            provider,
            "native-1",
            payload,
            retrieved_at=T0,
            source_updated_at=T0,
            external_object_id=object_a,
        )
        later = self.kb.append_source_record(
            provider,
            "native-1",
            payload,
            retrieved_at=T1,
            source_updated_at=T1,
            external_object_id=object_b,
        )
        self.assertEqual({record, replay, later}, {record})
        retrievals = self.kb.source_record_retrievals(record)
        self.assertEqual(len(retrievals), 2)
        self.assertEqual(
            {row["external_object_id"] for row in retrievals}, {object_a, object_b}
        )

    def test_external_identifier_exact_mapping_cannot_contradict(self):
        card_a, _, card_b, _ = self.two_cards()
        catalog = self.source("catalog", "CATALOG")
        external_object = self.kb.create_external_object(
            catalog, "CATALOG_CARD", "same-id"
        )
        identifier = self.kb.add_external_identifier(
            external_object, "CATALOG_ID", "same-id"
        )
        self.kb.link_identifier(
            identifier, ResolutionState.PROVEN, canonical_card_id=card_a
        )
        with self.assertRaises(IdempotencyConflict):
            self.kb.link_identifier(
                identifier, ResolutionState.PROVEN, canonical_card_id=card_b
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO identifier_link(
                    id, external_identifier_id, canonical_card_id,
                    resolution_state, created_at
                ) VALUES (?, ?, ?, 'PROVEN', ?)
                """,
                (unique_id("idlink"), identifier, card_b, T0),
            )
        for state in (ResolutionState.UNKNOWN, ResolutionState.CONFLICT):
            with self.assertRaises(ProvenanceError):
                self.kb.link_identifier(identifier, state, canonical_card_id=card_a)
            with self.assertRaises(sqlite3.IntegrityError):
                self.kb.connection.execute(
                    """
                    INSERT INTO identifier_link(
                        id, external_identifier_id, canonical_card_id,
                        resolution_state, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        unique_id("idlink"),
                        identifier,
                        card_a,
                        state.value,
                        T0,
                    ),
                )

        supported = self.kb.link_identifier(
            identifier, ResolutionState.SUPPORTED, canonical_card_id=card_b
        )
        self.assertTrue(supported.startswith("idlink_"))

    def test_observation_identity_link_must_match_resolution_and_envelope(self):
        card_a, _, card_b, _ = self.two_cards()
        source_id = self.source()
        observation = self.sale(
            source_id, "identity-event", T0, canonical_card_id=card_a
        )
        subject = self.kb.create_identity_subject("LISTING")
        resolved_b = self.kb.create_identity_resolution(
            subject, ResolutionState.PROVEN, canonical_card_id=card_b
        )
        with self.assertRaises(ProvenanceError):
            self.kb.link_observation_identity(
                observation,
                resolved_b,
                canonical_card_id=card_b,
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
                (unique_id("oilink"), observation, resolved_b, card_b, T0),
            )
        unknown = self.kb.create_identity_resolution(subject, ResolutionState.UNKNOWN)
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO observation_identity_link(
                    id, observation_id, identity_resolution_id,
                    canonical_card_id, link_role, created_at
                ) VALUES (?, ?, ?, ?, 'RESOLVED_AS', ?)
                """,
                (unique_id("oilink"), observation, unknown, card_a, T0),
            )


class VariantIntegrityTests(IntegrityTestCase):
    def insert_card_direct(self, localized_id, profile_id, comparison_key):
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
                comparison_key,
                T0,
            ),
        )

    def test_unlocked_or_unallowed_profile_cannot_back_canonical_card(self):
        family_id, localized_id = self.family()
        profile_id = unique_id("vprofile")
        self.kb.connection.execute(
            """
            INSERT INTO variant_profile(
                id, fingerprint_sha256, label, created_at, locked_at
            ) VALUES (?, ?, NULL, ?, NULL)
            """,
            (profile_id, uuid.uuid4().hex, T0),
        )
        self.kb.allow_variant_profile(family_id, profile_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_card_direct(localized_id, profile_id, "arbitrary")

    def test_applicable_and_not_applicable_dimensions_are_enforced_in_sql(self):
        family_id, localized_id = self.family()
        incomplete = self.kb.create_variant_profile(
            {"shadow_treatment": "SHADOWLESS"}
        )
        self.kb.set_family_variant_applicability(
            family_id, "edition_stamp", "APPLICABLE"
        )
        self.kb.allow_variant_profile(family_id, incomplete)
        semantic = self.kb.connection.execute(
            "SELECT semantic_key FROM variant_profile WHERE id = ?", (incomplete,)
        ).fetchone()[0]
        with self.assertRaises(VariantError):
            self.kb.create_canonical_card(localized_id, incomplete)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_card_direct(
                localized_id, incomplete, f"cardcmp|{localized_id}|{semantic}"
            )

        other_set = self.kb.create_canonical_set("other-set", "Other Set")
        other_family = self.kb.create_card_family(other_set, "1/10", "Other")
        other_localized = self.kb.create_localized_card(other_family, "en", "Other")
        assigned = self.kb.create_variant_profile({"finish": "HOLO"})
        self.kb.set_family_variant_applicability(
            other_family, "finish", "NOT_APPLICABLE"
        )
        self.kb.allow_variant_profile(other_family, assigned)
        assigned_semantic = self.kb.connection.execute(
            "SELECT semantic_key FROM variant_profile WHERE id = ?", (assigned,)
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_card_direct(
                other_localized,
                assigned,
                f"cardcmp|{other_localized}|{assigned_semantic}",
            )

    def test_semantic_duplicate_profiles_cannot_bypass_identity(self):
        profile = self.kb.create_variant_profile(
            {
                "edition_stamp": "FIRST_EDITION",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        duplicate = unique_id("vprofile")
        self.kb.connection.execute(
            """
            INSERT INTO variant_profile(
                id, fingerprint_sha256, label, created_at, locked_at
            ) VALUES (?, ?, NULL, ?, NULL)
            """,
            (duplicate, "caller-controlled-fingerprint", T0),
        )
        assignments = self.kb.connection.execute(
            """
            SELECT dimension_id, value_id FROM variant_assignment
            WHERE profile_id = ? ORDER BY dimension_id
            """,
            (profile,),
        ).fetchall()
        for assignment in assignments:
            self.kb.connection.execute(
                """
                INSERT INTO variant_assignment(
                    profile_id, dimension_id, value_id, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (duplicate, assignment["dimension_id"], assignment["value_id"], T0),
            )
        semantic = self.kb.connection.execute(
            "SELECT semantic_key FROM variant_profile WHERE id = ?", (profile,)
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                UPDATE variant_profile SET semantic_key = ?, locked_at = ? WHERE id = ?
                """,
                (semantic, T1, duplicate),
            )

    def test_exact_comparison_key_is_deterministically_bound(self):
        family_id, localized_id = self.family()
        profile = self.kb.create_variant_profile({"finish": "HOLO"})
        self.kb.allow_variant_profile(family_id, profile)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_card_direct(localized_id, profile, "caller-key")
        card = self.kb.create_canonical_card(localized_id, profile)
        semantic = self.kb.connection.execute(
            "SELECT semantic_key FROM variant_profile WHERE id = ?", (profile,)
        ).fetchone()[0]
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT exact_comparison_key FROM canonical_card WHERE id = ?", (card,)
            ).fetchone()[0],
            f"cardcmp|{localized_id}|{semantic}",
        )

    def test_applicability_and_allow_list_cannot_invalidate_existing_card(self):
        card_id, profile_id = self.card({"finish": "HOLO"})
        family_id, _ = self.family()
        combination_id = self.kb.connection.execute(
            """
            SELECT id FROM allowed_variant_combination
            WHERE card_family_id = ? AND variant_profile_id = ?
            """,
            (family_id, profile_id),
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "DELETE FROM allowed_variant_combination WHERE id = ?",
                (combination_id,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.set_family_variant_applicability(
                family_id, "edition_stamp", "APPLICABLE"
            )
        self.assertIsNotNone(
            self.kb.connection.execute(
                "SELECT 1 FROM canonical_card WHERE id = ?", (card_id,)
            ).fetchone()
        )


class PriceFXAndCertificationTests(IntegrityTestCase):
    def test_price_state_matrix_is_enforced_in_python_and_sql(self):
        invalid = (
            (1_000, "EUR", PriceKnowledge.UNKNOWN, InclusionState.UNKNOWN),
            (1_000, None, PriceKnowledge.KNOWN, InclusionState.INCLUDED),
            (None, None, PriceKnowledge.NOT_APPLICABLE, InclusionState.INCLUDED),
        )
        for amount, currency, knowledge, inclusion in invalid:
            with self.subTest(knowledge=knowledge, inclusion=inclusion):
                with self.assertRaises(ValueError):
                    PriceComponent(
                        "ITEM_PRICE", amount, currency, knowledge, inclusion
                    )

        source_id = self.source()
        draft = self.raw_observation(source_id, ObservationType.SALE_TRANSACTION)
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO price_component(
                    id, observation_id, component_type, amount_minor, currency,
                    knowledge_state, inclusion_state, created_at
                ) VALUES (?, ?, 'ITEM_PRICE', NULL, NULL,
                          'NOT_APPLICABLE', 'INCLUDED', ?)
                """,
                (unique_id("price"), draft, T0),
            )

    def test_price_components_are_restricted_to_price_bearing_observations(self):
        source_id = self.source()
        draft = self.raw_observation(
            source_id, ObservationType.POPULATION_OBSERVATION
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO price_component(
                    id, observation_id, component_type, amount_minor, currency,
                    knowledge_state, inclusion_state, created_at
                ) VALUES (?, ?, 'TOTAL', 1000, 'EUR', 'KNOWN', 'INCLUDED', ?)
                """,
                (unique_id("price"), draft, T0),
            )

    def test_fx_must_match_exact_component_and_decimal_amount(self):
        with self.assertRaises(ValueError):
            FXNormalization(
                "TOTAL", 10_000, "USD", "0.91", "ECB", "2026-08-14", "EUR", 9_099
            )

        source_id = self.source()
        draft = self.raw_observation(source_id, ObservationType.SALE_TRANSACTION)
        hammer_id = unique_id("price")
        item_id = unique_id("price")
        for price_id, component in ((hammer_id, "HAMMER_PRICE"), (item_id, "ITEM_PRICE")):
            self.kb.connection.execute(
                """
                INSERT INTO price_component(
                    id, observation_id, component_type, amount_minor, currency,
                    knowledge_state, inclusion_state, created_at
                ) VALUES (?, ?, ?, 10000, 'USD', 'KNOWN', 'INCLUDED', ?)
                """,
                (price_id, draft, component, T0),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO fx_normalization(
                    id, observation_id, component_type, original_amount_minor,
                    original_currency, fx_rate_decimal, rate_source,
                    rate_effective_date, target_currency, target_amount_minor,
                    created_at, price_component_id
                ) VALUES (?, ?, 'HAMMER_PRICE', 10000, 'USD', '0.91', 'ECB',
                          '2026-08-14', 'EUR', 9100, ?, ?)
                """,
                (unique_id("fxnorm"), draft, T0, item_id),
            )

    def test_fx_rate_observation_lineage_must_match(self):
        fx_source = self.source("ecb", "PROVIDER")
        rate = self.kb.append_market_observation(
            ObservationType.FX_RATE_OBSERVATION,
            fx_source,
            "usd-eur",
            observed_at=T0,
            fact={
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate_decimal": "0.91",
                "effective_date": "2026-08-14",
                "rate_source": "ECB",
            },
        )
        with self.assertRaises(KnowledgeBaseError):
            self.kb.append_market_observation(
                ObservationType.SALE_TRANSACTION,
                self.source(),
                "fx-mismatch",
                observed_at=T1,
                fact={"transaction_status": "COMPLETED"},
                prices=[PriceComponent("TOTAL", 10_000, "USD")],
                fx_normalizations=[
                    FXNormalization(
                        "TOTAL",
                        10_000,
                        "USD",
                        "0.91",
                        "NOT_ECB",
                        "2026-08-14",
                        "EUR",
                        9_100,
                        rate_observation_id=rate,
                    )
                ],
            )

    def test_certification_identifier_is_unique_to_one_instance(self):
        card_a, _, card_b, _ = self.two_cards()
        psa = self.source("psa", "CATALOG")
        cert_object = self.kb.create_external_object(psa, "CERTIFICATE", "cert-123")
        cert_id = self.kb.add_external_identifier(cert_object, "PSA_CERT", "123")
        instance = self.kb.create_collectible_instance(
            card_a,
            grader="PSA",
            grade="9",
            certification_identifier_id=cert_id,
        )
        with self.assertRaises(IdempotencyConflict):
            self.kb.create_collectible_instance(
                card_b,
                grader="PSA",
                grade="10",
                certification_identifier_id=cert_id,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO collectible_instance(
                    id, canonical_card_id, grader, grade,
                    certification_identifier_id, created_at
                ) VALUES (?, ?, 'PSA', '10', ?, ?)
                """,
                (unique_id("instance"), card_b, cert_id, T0),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "UPDATE collectible_instance SET grade = '10' WHERE id = ?",
                (instance,),
            )


class ScenarioExactnessTests(unittest.TestCase):
    def scenario(self, profile, passes=True, confirmed=True):
        return VariantValuationScenario(profile, confirmed, passes)

    def test_invalid_exactness_shapes_are_rejected(self):
        with self.assertRaises(ValueError):
            classify_opportunity(
                [self.scenario("candidate")], exact_variant_profile_id="absent"
            )
        with self.assertRaises(ValueError):
            classify_opportunity(
                [self.scenario("a"), self.scenario("b")],
                exact_variant_profile_id="a",
            )
        with self.assertRaises(ValueError):
            classify_opportunity([self.scenario("unproven")])

    def test_valid_exact_robust_mixed_and_incomplete_states(self):
        exact = classify_opportunity(
            [self.scenario("exact")], exact_variant_profile_id="exact"
        )
        robust = classify_opportunity(
            [self.scenario("a"), self.scenario("b")]
        )
        mixed = classify_opportunity(
            [self.scenario("a"), self.scenario("b", False)]
        )
        incomplete = classify_opportunity(
            [self.scenario("a"), self.scenario("b", None, False)]
        )
        self.assertEqual(exact, OpportunityState.EXACT_VARIANT_OPPORTUNITY)
        self.assertEqual(robust, OpportunityState.ROBUST_VARIANT_OPPORTUNITY)
        self.assertEqual(
            mixed, OpportunityState.MICROVARIANT_DEPENDENT_OPPORTUNITY
        )
        self.assertEqual(
            incomplete, OpportunityState.SCENARIO_DATA_INCOMPLETE_REVIEW
        )


class MigrationAndConnectionTests(unittest.TestCase):
    def copy_migrations(self, destination: Path, versions=(1, 2)) -> None:
        destination.mkdir()
        for version in versions:
            source = migrations.MIGRATION_DIRECTORY / (
                "0001_initial.sql" if version == 1 else "0002_integrity_hardening.sql"
            )
            shutil.copy2(source, destination / source.name)

    def test_existing_0001_database_applies_0002_and_seals_complete_fact(self):
        with tempfile.TemporaryDirectory(prefix="gcc-kb-migration-") as directory:
            root = Path(directory)
            only_0001 = root / "only-0001"
            self.copy_migrations(only_0001, (1,))
            connection = migrations.connect_database(root / "existing.sqlite3")
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", only_0001):
                    migrations.apply_migrations(connection)
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )],
                    [1],
                )
                connection.execute(
                    """
                    INSERT INTO source_system(id, code, name, system_role, created_at)
                    VALUES ('source_legacy', 'legacy', 'Legacy', 'MARKET', ?)
                    """,
                    (T0,),
                )
                connection.execute(
                    """
                    INSERT INTO market_observation(
                        id, observation_type, source_system_id,
                        source_native_record_id, idempotency_key, content_sha256,
                        event_time_precision, observed_at, ingested_at, created_at
                    ) VALUES (
                        'observation_legacy', 'SALE_TRANSACTION', 'source_legacy',
                        'sale-1', 'obskey_legacy', 'hash', 'UNKNOWN', ?, ?, ?
                    )
                    """,
                    (T0, T0, T0),
                )
                connection.execute(
                    """
                    INSERT INTO sale_transaction(observation_id, transaction_status)
                    VALUES ('observation_legacy', 'COMPLETED')
                    """
                )
                migrations.apply_migrations(connection)
                row = connection.execute(
                    "SELECT lifecycle_state FROM market_observation"
                ).fetchone()
                self.assertEqual(row[0], "SEALED")
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )],
                    [1, 2],
                )
            finally:
                connection.close()

    def test_0002_refuses_legacy_fabricated_provenance(self):
        with tempfile.TemporaryDirectory(prefix="gcc-kb-legacy-exploit-") as directory:
            root = Path(directory)
            only_0001 = root / "only-0001"
            self.copy_migrations(only_0001, (1,))
            connection = migrations.connect_database(root / "exploited.sqlite3")
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", only_0001):
                    migrations.apply_migrations(connection)
                connection.execute(
                    """
                    INSERT INTO source_system(id, code, name, system_role, created_at)
                    VALUES ('source_legacy', 'legacy', 'Legacy', 'PROVIDER', ?)
                    """,
                    (T0,),
                )
                connection.execute(
                    """
                    INSERT INTO source_record(
                        id, source_system_id, source_native_record_id,
                        payload_sha256, retrieved_at, created_at
                    ) VALUES (
                        'srecord_legacy', 'source_legacy', 'record-1',
                        'payload', ?, ?
                    )
                    """,
                    (T0, T0),
                )
                connection.execute(
                    """
                    INSERT INTO identity_subject(
                        id, subject_type, source_record_id, created_at
                    ) VALUES (
                        'subject_legacy', 'PROVIDER_RESPONSE',
                        'srecord_legacy', ?
                    )
                    """,
                    (T0,),
                )
                connection.execute(
                    """
                    INSERT INTO field_claim(
                        id, source_record_id, identity_subject_id, field_name,
                        claimed_value_json, source_kind, evidence_method,
                        directness, resolution_state, claim_role, created_at
                    ) VALUES (
                        'claim_legacy', 'srecord_legacy', 'subject_legacy',
                        'edition_stamp', NULL, 'PROVIDER', 'STRUCTURED_FIELD',
                        'DIRECT_ASSERTION', 'UNKNOWN', 'EVIDENCE', ?
                    )
                    """,
                    (T0,),
                )
                connection.execute(
                    """
                    INSERT INTO field_resolution(
                        id, identity_subject_id, field_name, resolved_value_json,
                        resolution_state, based_on_claim_id, created_at
                    ) VALUES (
                        'fres_legacy', 'subject_legacy', 'edition_stamp',
                        ?, 'PROVEN', 'claim_legacy', ?
                    )
                    """,
                    (json.dumps("NO_FIRST_EDITION_STAMP"), T0),
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    migrations.apply_migrations(connection)
                versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migration ORDER BY version"
                    )
                ]
                self.assertEqual(versions, [1])
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(market_observation)"
                    )
                }
                self.assertNotIn("lifecycle_state", columns)
            finally:
                connection.close()

    def test_migration_checksum_and_duplicate_versions_fail_loudly(self):
        with tempfile.TemporaryDirectory(prefix="gcc-kb-checksum-") as directory:
            root = Path(directory)
            copied = root / "migrations"
            self.copy_migrations(copied)
            connection = migrations.connect_database(root / "checksum.sqlite3")
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", copied):
                    migrations.apply_migrations(connection)
                    path = copied / "0001_initial.sql"
                    path.write_text(
                        path.read_text(encoding="utf-8") + "\n-- tampered\n",
                        encoding="utf-8",
                    )
                    with self.assertRaises(MigrationError):
                        migrations.apply_migrations(connection)
            finally:
                connection.close()

            duplicate = root / "duplicates"
            self.copy_migrations(duplicate)
            shutil.copy2(
                duplicate / "0001_initial.sql", duplicate / "0001_duplicate.sql"
            )
            duplicate_connection = migrations.connect_database(
                root / "duplicate.sqlite3"
            )
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", duplicate):
                    with self.assertRaises(MigrationError):
                        migrations.apply_migrations(duplicate_connection)
            finally:
                duplicate_connection.close()

    def test_migration_ledger_rejects_mutation_and_orphan_versions(self):
        with KnowledgeBase.open() as kb:
            with self.assertRaises(sqlite3.IntegrityError):
                kb.connection.execute(
                    "UPDATE schema_migration SET filename = 'changed' WHERE version = 1"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                kb.connection.execute(
                    "DELETE FROM schema_migration WHERE version = 1"
                )

        with tempfile.TemporaryDirectory(prefix="gcc-kb-orphan-") as directory:
            root = Path(directory)
            only_0001 = root / "only-0001"
            self.copy_migrations(only_0001, (1,))
            connection = migrations.connect_database(root / "orphan.sqlite3")
            try:
                with mock.patch.object(migrations, "MIGRATION_DIRECTORY", only_0001):
                    migrations.apply_migrations(connection)
                connection.execute(
                    """
                    INSERT INTO schema_migration(
                        version, filename, checksum_sha256, applied_at
                    ) VALUES (9999, '9999_orphan.sql', 'fake', ?)
                    """,
                    (T0,),
                )
                with self.assertRaises(MigrationError):
                    migrations.apply_migrations(connection)
            finally:
                connection.close()

    def test_external_connection_always_enables_or_rejects_foreign_keys(self):
        connection = sqlite3.connect(":memory:", isolation_level=None)
        kb = KnowledgeBase(connection)
        try:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            kb.close()

        blocked = sqlite3.connect(":memory:", isolation_level=None)
        try:
            blocked.execute("BEGIN")
            with self.assertRaises(MigrationError):
                KnowledgeBase(blocked)
        finally:
            blocked.rollback()
            blocked.close()


if __name__ == "__main__":
    unittest.main()
