from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from robot_kb import (
    CandidateInput,
    ClaimRole,
    Directness,
    EvidenceMethod,
    FXNormalization,
    IdempotencyConflict,
    InclusionState,
    KnowledgeBase,
    ObservationType,
    OpportunityState,
    PriceComponent,
    PriceKnowledge,
    ProvenanceError,
    ResolutionState,
    SourceKind,
    VariantValuationScenario,
    classify_opportunity,
)


T0 = "2026-08-14T08:00:00+02:00"
T1 = "2026-08-14T09:00:00+02:00"
T2 = "2026-08-14T10:00:00+02:00"


class KnowledgeBaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()

    def tearDown(self) -> None:
        self.kb.close()

    def source(self, code: str = "gcc", role: str = "MARKET") -> str:
        return self.kb.create_source_system(code, code.upper(), role)

    def card_family(self):
        set_id = self.kb.create_canonical_set("pokemon-base-set", "Base Set")
        family_id = self.kb.create_card_family(set_id, "4/102", "Charizard")
        localized_id = self.kb.create_localized_card(
            family_id, "en", "Charizard", localized_set_name="Base Set"
        )
        return set_id, family_id, localized_id

    def card(self, assignments=None):
        _, family_id, localized_id = self.card_family()
        profile_id = self.kb.create_variant_profile(
            assignments
            or {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWED",
                "finish": "HOLO",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_id)
        return self.kb.create_canonical_card(localized_id, profile_id), profile_id

    def sale(
        self,
        source_id: str,
        native_id: str,
        observed_at: str,
        amount_minor: int,
        **kwargs,
    ) -> str:
        return self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            source_id,
            native_id,
            observed_at=observed_at,
            event_at=observed_at,
            event_time_precision="EXACT",
            fact={
                "sale_occurred_at": observed_at,
                "transaction_status": "COMPLETED",
            },
            prices=[
                PriceComponent(
                    "TOTAL",
                    amount_minor,
                    "EUR",
                    PriceKnowledge.KNOWN,
                    InclusionState.INCLUDED,
                )
            ],
            **kwargs,
        )


class CanonicalIdentityTests(KnowledgeBaseTestCase):
    def test_canonical_ids_are_internal_and_external_ids_are_aliases(self):
        card_id, _ = self.card()
        tcgdex = self.source("tcgdex", "CATALOG")
        external_object = self.kb.create_external_object(
            tcgdex, "CATALOG_CARD", "base1-4"
        )
        external_id = self.kb.add_external_identifier(
            external_object, "TCGDEX_CARD_ID", "base1-4"
        )
        self.kb.link_identifier(
            external_id, ResolutionState.PROVEN, canonical_card_id=card_id
        )

        self.assertTrue(card_id.startswith("card_"))
        self.assertNotEqual(card_id, "base1-4")
        row = self.kb.connection.execute(
            "SELECT identifier_value FROM external_identifier WHERE id = ?",
            (external_id,),
        ).fetchone()
        self.assertEqual(row["identifier_value"], "base1-4")

    def test_unresolved_observation_preserves_candidates_and_conflicts(self):
        card_a, _ = self.card(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        _, family_id, localized_id = self.card_family()
        profile_b = self.kb.create_variant_profile(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWED",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_b)
        card_b = self.kb.create_canonical_card(localized_id, profile_b)
        source_id = self.source()
        source_record = self.kb.append_source_record(
            source_id, "listing-123", {"title": "Charizard Base Set"}, retrieved_at=T0
        )
        subject = self.kb.create_identity_subject(
            "LISTING", source_record_id=source_record
        )
        resolution = self.kb.create_identity_resolution(
            subject,
            ResolutionState.CONFLICT,
            candidates=[
                CandidateInput(card_a, 0, evidence_summary="shadow unclear"),
                CandidateInput(card_b, 1, evidence_summary="shadow unclear"),
            ],
            unresolved_dimensions=["shadow_treatment"],
            conflicts=["structured finish conflicts with title"],
        )
        observation = self.kb.append_market_observation(
            ObservationType.LISTING_SNAPSHOT,
            source_id,
            "listing-123",
            observed_at=T0,
            fact={"snapshot_status": "ACTIVE"},
            source_record_id=source_record,
            canonical_card_id=None,
        )
        self.kb.link_observation_identity(observation, resolution)

        self.assertIsNone(self.kb.fetch_observation(observation)["canonical_card_id"])
        candidates = self.kb.connection.execute(
            "SELECT canonical_card_id FROM identity_candidate WHERE identity_resolution_id = ?",
            (resolution,),
        ).fetchall()
        self.assertEqual({row[0] for row in candidates}, {card_a, card_b})
        resolution_row = self.kb.connection.execute(
            "SELECT * FROM identity_resolution WHERE id = ?", (resolution,)
        ).fetchone()
        self.assertEqual(
            json.loads(resolution_row["unresolved_dimensions_json"]),
            ["shadow_treatment"],
        )
        self.assertEqual(len(json.loads(resolution_row["conflicts_json"])), 1)


class ProvenanceTests(KnowledgeBaseTestCase):
    def provenance_subject(self):
        source_id = self.source("poketrace", "PROVIDER")
        source_record = self.kb.append_source_record(
            source_id, "request-1", {"requested_edition": "FIRST_EDITION"}, retrieved_at=T0
        )
        subject = self.kb.create_identity_subject(
            "PROVIDER_RESPONSE", source_record_id=source_record
        )
        return source_record, subject

    def test_requested_value_cannot_become_provenance_proof(self):
        source_record, subject = self.provenance_subject()
        target_claim = self.kb.append_field_claim(
            source_record,
            subject,
            "edition_stamp",
            "FIRST_EDITION",
            source_kind=SourceKind.PROVIDER,
            evidence_method=EvidenceMethod.STRUCTURED_FIELD,
            directness=Directness.DIRECT_ASSERTION,
            resolution_state=ResolutionState.UNKNOWN,
            claim_role=ClaimRole.REQUEST_TARGET,
        )
        with self.assertRaises(ProvenanceError):
            self.kb.resolve_field(
                subject,
                "edition_stamp",
                ResolutionState.PROVEN,
                value="FIRST_EDITION",
                based_on_claim_id=target_claim,
            )
        result = self.kb.latest_field_resolution(subject, "edition_stamp")
        self.assertEqual(result.resolution_state, ResolutionState.UNKNOWN)
        self.assertIsNone(result.value)

    def test_provider_silence_does_not_create_unlimited_or_other_default(self):
        _, subject = self.provenance_subject()
        edition = self.kb.latest_field_resolution(subject, "edition_stamp")
        promo = self.kb.latest_field_resolution(subject, "promo_type")
        finish = self.kb.latest_field_resolution(subject, "finish")
        self.assertEqual(edition.resolution_state, ResolutionState.UNKNOWN)
        self.assertEqual(promo.resolution_state, ResolutionState.UNKNOWN)
        self.assertEqual(finish.resolution_state, ResolutionState.UNKNOWN)
        self.assertNotEqual(edition.value, "NO_FIRST_EDITION_STAMP")
        self.assertNotEqual(promo.value, "NON_PROMO")

    def test_field_claim_preserves_orthogonal_provenance_axes(self):
        source_record, subject = self.provenance_subject()
        claim_id = self.kb.append_field_claim(
            source_record,
            subject,
            "finish",
            "HOLO",
            source_kind=SourceKind.PROVIDER,
            evidence_method=EvidenceMethod.STRUCTURED_FIELD,
            directness=Directness.DIRECT_ASSERTION,
            resolution_state=ResolutionState.PROVEN,
        )
        self.kb.resolve_field(
            subject,
            "finish",
            ResolutionState.PROVEN,
            value="HOLO",
            based_on_claim_id=claim_id,
        )
        row = self.kb.connection.execute(
            "SELECT * FROM field_claim WHERE id = ?", (claim_id,)
        ).fetchone()
        self.assertEqual(row["source_kind"], "PROVIDER")
        self.assertEqual(row["evidence_method"], "STRUCTURED_FIELD")
        self.assertEqual(row["directness"], "DIRECT_ASSERTION")
        self.assertEqual(row["resolution_state"], "PROVEN")


class GenericVariantTests(KnowledgeBaseTestCase):
    def test_distinct_commercial_profiles_cannot_silently_collapse(self):
        first = self.kb.create_variant_profile(
            {"edition_stamp": "FIRST_EDITION", "shadow_treatment": "SHADOWLESS"}
        )
        no_stamp = self.kb.create_variant_profile(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        same_first = self.kb.create_variant_profile(
            {"shadow_treatment": "SHADOWLESS", "edition_stamp": "FIRST_EDITION"}
        )
        self.assertNotEqual(first, no_stamp)
        self.assertEqual(first, same_first)

    def test_base_set_orthogonal_profiles_remain_distinct(self):
        profiles = {
            self.kb.create_variant_profile(
                {
                    "edition_stamp": "FIRST_EDITION",
                    "shadow_treatment": "SHADOWLESS",
                }
            ),
            self.kb.create_variant_profile(
                {
                    "edition_stamp": "NO_FIRST_EDITION_STAMP",
                    "shadow_treatment": "SHADOWLESS",
                }
            ),
            self.kb.create_variant_profile(
                {
                    "edition_stamp": "NO_FIRST_EDITION_STAMP",
                    "shadow_treatment": "SHADOWED",
                }
            ),
        }
        self.assertEqual(len(profiles), 3)
        edition_codes = {
            row[0]
            for row in self.kb.connection.execute(
                """
                SELECT code FROM variant_value
                WHERE dimension_id = 'vdim_edition_stamp'
                """
            )
        }
        self.assertNotIn("UNLIMITED", edition_codes)

    def test_incompatible_variants_never_share_exact_comparison_domain(self):
        card_a, _ = self.card(
            {
                "edition_stamp": "FIRST_EDITION",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        _, family_id, localized_id = self.card_family()
        profile_b = self.kb.create_variant_profile(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWLESS",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_b)
        card_b = self.kb.create_canonical_card(localized_id, profile_b)
        self.assertNotEqual(
            self.kb.comparison_domain_key(card_a),
            self.kb.comparison_domain_key(card_b),
        )
        self.assertNotEqual(
            self.kb.comparison_domain_key(card_a, grader="PSA", grade="9"),
            self.kb.comparison_domain_key(card_a, grader="BGS", grade="9"),
        )


class MarketLedgerTests(KnowledgeBaseTestCase):
    def test_later_price_preserves_earlier_market_history(self):
        source_id = self.source()
        earlier = self.sale(source_id, "sale-1", T0, 10_000)
        later = self.sale(source_id, "sale-1", T1, 12_500)
        self.assertNotEqual(earlier, later)
        self.assertEqual(self.kb.observation_count(), 2)
        amounts = {
            row[0]
            for row in self.kb.connection.execute(
                "SELECT amount_minor FROM price_component ORDER BY amount_minor"
            )
        }
        self.assertEqual(amounts, {10_000, 12_500})

    def test_revision_keeps_previous_observation_queryable(self):
        source_id = self.source()
        previous = self.sale(source_id, "sale-correction", T0, 10_000)
        correction = self.sale(
            source_id,
            "sale-correction",
            T1,
            9_000,
            revision_of_observation_id=previous,
        )
        self.assertEqual(
            self.kb.fetch_observation(correction)["revision_of_observation_id"],
            previous,
        )
        self.assertEqual(
            self.kb.price_components(previous)[0]["amount_minor"], 10_000
        )
        relation = self.kb.connection.execute(
            """
            SELECT relationship_type FROM observation_relationship
            WHERE from_observation_id = ? AND to_observation_id = ?
            """,
            (correction, previous),
        ).fetchone()
        self.assertEqual(relation["relationship_type"], "REVISION_OF")

    def test_two_providers_can_reference_one_upstream_market_event(self):
        ebay = self.source("ebay", "MARKET")
        poketrace = self.source("poketrace", "PROVIDER")
        pricecharting = self.source("pricecharting", "PROVIDER")
        upstream_event = self.kb.create_external_object(
            ebay, "SALE_EVENT", "item-123-sale"
        )
        first = self.sale(
            poketrace,
            "pt-record-1",
            T0,
            10_000,
            upstream_market_system_id=ebay,
            upstream_event_object_id=upstream_event,
        )
        second = self.sale(
            pricecharting,
            "pc-record-7",
            T1,
            10_000,
            upstream_market_system_id=ebay,
            upstream_event_object_id=upstream_event,
        )
        rows = self.kb.connection.execute(
            """
            SELECT source_system_id, upstream_market_system_id,
                   upstream_event_object_id
            FROM market_observation WHERE id IN (?, ?)
            """,
            (first, second),
        ).fetchall()
        self.assertEqual({row["source_system_id"] for row in rows}, {poketrace, pricecharting})
        self.assertEqual({row["upstream_market_system_id"] for row in rows}, {ebay})
        self.assertEqual({row["upstream_event_object_id"] for row in rows}, {upstream_event})

    def test_provider_aggregate_is_not_an_individual_sale(self):
        provider = self.source("cardmarket", "PROVIDER")
        metric = self.kb.append_market_observation(
            ObservationType.PROVIDER_METRIC_OBSERVATION,
            provider,
            "trend-1",
            observed_at=T0,
            fact={
                "metric_name": "TREND_PRICE_30D",
                "metric_value_minor": 10_000,
                "currency": "EUR",
                "sample_size": 20,
            },
        )
        sale = self.sale(provider, "sale-1", T1, 10_000)
        self.assertEqual(
            self.kb.fetch_observation(metric)["observation_type"],
            "PROVIDER_METRIC_OBSERVATION",
        )
        self.assertEqual(
            self.kb.fetch_observation(sale)["observation_type"], "SALE_TRANSACTION"
        )
        self.assertIsNotNone(
            self.kb.connection.execute(
                "SELECT 1 FROM provider_metric_observation WHERE observation_id = ?",
                (metric,),
            ).fetchone()
        )
        self.assertIsNone(
            self.kb.connection.execute(
                "SELECT 1 FROM sale_transaction WHERE observation_id = ?", (metric,)
            ).fetchone()
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                """
                INSERT INTO sale_transaction(observation_id, transaction_status)
                VALUES (?, 'UNKNOWN')
                """,
                (metric,),
            )

    def test_price_components_and_fx_lineage_preserve_original_amounts(self):
        fx_source = self.source("ecb", "PROVIDER")
        fx_rate = self.kb.append_market_observation(
            ObservationType.FX_RATE_OBSERVATION,
            fx_source,
            "eur-usd-2026-08-14",
            observed_at=T0,
            fact={
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate_decimal": "0.91",
                "effective_date": "2026-08-14",
                "rate_source": "ECB",
            },
        )
        sale_source = self.source()
        sale = self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            sale_source,
            "sale-usd",
            observed_at=T1,
            fact={"transaction_status": "COMPLETED"},
            prices=[
                PriceComponent("HAMMER_PRICE", 10_000, "USD"),
                PriceComponent(
                    "SHIPPING",
                    None,
                    None,
                    PriceKnowledge.UNKNOWN,
                    InclusionState.UNKNOWN,
                ),
            ],
            fx_normalizations=[
                FXNormalization(
                    "HAMMER_PRICE",
                    10_000,
                    "USD",
                    "0.91",
                    "ECB",
                    "2026-08-14",
                    "EUR",
                    9_100,
                    rate_observation_id=fx_rate,
                )
            ],
        )
        components = {row["component_type"]: row for row in self.kb.price_components(sale)}
        self.assertEqual(components["HAMMER_PRICE"]["amount_minor"], 10_000)
        self.assertEqual(components["HAMMER_PRICE"]["currency"], "USD")
        self.assertEqual(components["SHIPPING"]["knowledge_state"], "UNKNOWN")
        normalized = self.kb.connection.execute(
            "SELECT * FROM fx_normalization WHERE observation_id = ?", (sale,)
        ).fetchone()
        self.assertEqual(normalized["rate_observation_id"], fx_rate)
        self.assertEqual(normalized["target_amount_minor"], 9_100)

    def test_retrieval_time_is_not_fabricated_as_sale_time(self):
        source_id = self.source()
        observation = self.kb.append_market_observation(
            ObservationType.SALE_TRANSACTION,
            source_id,
            "unknown-sale-time",
            observed_at=T2,
            event_at=None,
            event_time_precision="UNKNOWN",
            fact={"transaction_status": "UNKNOWN", "sale_occurred_at": None},
        )
        envelope = self.kb.fetch_observation(observation)
        detail = self.kb.connection.execute(
            "SELECT * FROM sale_transaction WHERE observation_id = ?", (observation,)
        ).fetchone()
        self.assertEqual(envelope["observed_at"], T2)
        self.assertIsNone(envelope["event_at"])
        self.assertIsNone(detail["sale_occurred_at"])

    def test_idempotent_replay_and_conflicting_reuse_are_deterministic(self):
        source_id = self.source()
        first = self.sale(source_id, "sale-idempotent", T0, 10_000)
        replay = self.sale(source_id, "sale-idempotent", T0, 10_000)
        self.assertEqual(first, replay)
        self.assertEqual(self.kb.observation_count(), 1)
        with self.assertRaises(IdempotencyConflict):
            self.sale(source_id, "sale-idempotent", T0, 12_000)
        self.assertEqual(self.kb.observation_count(), 1)

        components = [
            PriceComponent("ITEM_PRICE", 9_000, "EUR"),
            PriceComponent("SHIPPING", 1_000, "EUR"),
        ]
        multi = self.kb.append_market_observation(
            ObservationType.LISTING_SNAPSHOT,
            source_id,
            "multi-component",
            observed_at=T1,
            fact={"snapshot_status": "ACTIVE"},
            prices=components,
        )
        reordered_replay = self.kb.append_market_observation(
            ObservationType.LISTING_SNAPSHOT,
            source_id,
            "multi-component",
            observed_at=T1,
            fact={"snapshot_status": "ACTIVE"},
            prices=list(reversed(components)),
        )
        self.assertEqual(multi, reordered_replay)
        self.assertEqual(self.kb.observation_count(), 2)

    def test_append_only_sql_guards_block_update_and_delete(self):
        source_id = self.source()
        observation = self.sale(source_id, "sale-immutable", T0, 10_000)
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "UPDATE market_observation SET observed_at = ? WHERE id = ?",
                (T1, observation),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.connection.execute(
                "DELETE FROM price_component WHERE observation_id = ?", (observation,)
            )
        self.assertEqual(self.kb.price_components(observation)[0]["amount_minor"], 10_000)


class ScenarioContractTests(unittest.TestCase):
    def scenario(self, profile: str, passes, confirmed: bool = True):
        return VariantValuationScenario(profile, confirmed, passes)

    def test_all_plausible_variants_pass_is_robust(self):
        state = classify_opportunity(
            [self.scenario("first", True), self.scenario("no-stamp", True)]
        )
        self.assertEqual(state, OpportunityState.ROBUST_VARIANT_OPPORTUNITY)

    def test_only_some_variants_pass_is_microvariant_dependent(self):
        state = classify_opportunity(
            [self.scenario("first", True), self.scenario("no-stamp", False)]
        )
        self.assertEqual(
            state, OpportunityState.MICROVARIANT_DEPENDENT_OPPORTUNITY
        )

    def test_one_variant_missing_market_is_incomplete_review(self):
        state = classify_opportunity(
            [self.scenario("first", False), self.scenario("no-stamp", None, False)]
        )
        self.assertEqual(state, OpportunityState.SCENARIO_DATA_INCOMPLETE_REVIEW)

    def test_all_fully_valued_and_none_pass_is_no_opportunity(self):
        state = classify_opportunity(
            [self.scenario("first", False), self.scenario("no-stamp", False)]
        )
        self.assertEqual(state, OpportunityState.NO_OPPORTUNITY)

    def test_explicit_identity_contradiction_has_precedence(self):
        state = classify_opportunity(
            [self.scenario("first", True)], identity_conflict=True
        )
        self.assertEqual(state, OpportunityState.IDENTITY_CONFLICT)

    def test_exact_unbounded_and_unconfirmed_states_remain_explicit(self):
        exact = classify_opportunity(
            [self.scenario("first", True)], exact_variant_profile_id="first"
        )
        unbounded = classify_opportunity([], identity_bounded=False)
        unconfirmed = classify_opportunity(
            [
                self.scenario("first", None, False),
                self.scenario("no-stamp", None, False),
            ]
        )
        self.assertEqual(exact, OpportunityState.EXACT_VARIANT_OPPORTUNITY)
        self.assertEqual(unbounded, OpportunityState.IDENTITY_UNBOUNDED)
        self.assertEqual(unconfirmed, OpportunityState.MARKET_UNCONFIRMED)


class GradedInstanceTests(KnowledgeBaseTestCase):
    def test_grader_and_grade_stay_outside_commercial_print_identity(self):
        card_id, _ = self.card()
        psa = self.kb.create_collectible_instance(card_id, grader="PSA", grade="9")
        bgs = self.kb.create_collectible_instance(card_id, grader="BGS", grade="9")
        self.assertNotEqual(psa, bgs)
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT canonical_card_id FROM collectible_instance WHERE id = ?", (psa,)
            ).fetchone()[0],
            card_id,
        )
        canonical_columns = {
            row["name"]
            for row in self.kb.connection.execute("PRAGMA table_info(canonical_card)")
        }
        self.assertNotIn("grader", canonical_columns)
        self.assertNotIn("grade", canonical_columns)


class MigrationTests(unittest.TestCase):
    def test_sqlite_migration_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="gcc-kb-test-") as directory:
            path = Path(directory) / "knowledge.sqlite3"
            with KnowledgeBase.open(path) as first:
                self.assertEqual(first.schema_versions(), [1, 2])
                dimension_count = first.connection.execute(
                    "SELECT COUNT(*) FROM variant_dimension"
                ).fetchone()[0]
            with KnowledgeBase.open(path) as second:
                self.assertEqual(second.schema_versions(), [1, 2])
                self.assertEqual(
                    second.connection.execute(
                        "SELECT COUNT(*) FROM variant_dimension"
                    ).fetchone()[0],
                    dimension_count,
                )
                self.assertEqual(
                    second.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
                )


if __name__ == "__main__":
    unittest.main()
