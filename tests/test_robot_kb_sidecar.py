from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from robot_kb import KnowledgeBase, ObservationType, ResolutionState
from robot_kb.sidecar import (
    CollectionResult,
    GCCMarketplaceCollector,
    RawSourceRecord,
    ShadowKnowledgePersistence,
    ShadowSidecar,
    TCGdexCollector,
)


T0 = "2026-08-13T07:00:00Z"
T1 = "2026-08-14T08:00:00Z"
T2 = "2026-08-14T08:00:01Z"
T3 = "2026-08-14T09:00:00Z"


def gcc_record(payload: dict, observed_at: str = T1) -> RawSourceRecord:
    return RawSourceRecord(
        source_code="gcc",
        source_name="GCC Marketplace",
        source_role="LISTING_PLATFORM",
        source_native_record_id=payload["id"],
        payload=payload,
        retrieved_at=observed_at,
        object_type="LISTING",
        external_native_id=payload["id"],
    )


def gcc_payload(
    listing_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    price: int = 3000,
    mode: str = "FIXED_PRICE",
    status: str = "ON_SALE",
    title: str = "Charizard 4/102",
) -> dict:
    return {
        "id": listing_id,
        "status": status,
        "sellingType": mode,
        "priceInCents": price,
        "updatedAt": T0,
        "quantity": 1,
        "item": {
            "title": title,
            "gradingCompany": "PSA",
            "grade": "9",
            "collectible": {
                "category": "Pokemon",
                "language": "English",
                "set": "Base Set",
                "reference": "4/102",
                "type": "CARDS",
            },
        },
    }


def tcgdex_record(payload: dict, observed_at: str = T1) -> RawSourceRecord:
    return RawSourceRecord(
        source_code="tcgdex",
        source_name="TCGdex",
        source_role="PROVIDER",
        source_native_record_id=payload["id"],
        payload=payload,
        retrieved_at=observed_at,
        object_type="CARD",
        external_native_id=payload["id"],
    )


class SidecarTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()
        self.persistence = ShadowKnowledgePersistence(self.kb, clock=lambda: T2)
        self.sidecar = ShadowSidecar(self.persistence)

    def tearDown(self) -> None:
        self.kb.close()

    def ingest(self, record: RawSourceRecord, name: str = "fixture"):
        self.sidecar.run_source(name, lambda: CollectionResult((record,)))
        self.assertEqual(self.sidecar.diagnostics.source_failures, 0)
        return self.sidecar.diagnostics

    def canonical_card(self) -> str:
        set_id = self.kb.create_canonical_set("base1", "Base Set")
        family_id = self.kb.create_card_family(set_id, "4/102", "Charizard")
        localized_id = self.kb.create_localized_card(
            family_id, "en", "Charizard", localized_set_name="Base Set"
        )
        profile_id = self.kb.create_variant_profile(
            {
                "edition_stamp": "NO_FIRST_EDITION_STAMP",
                "shadow_treatment": "SHADOWED",
                "finish": "HOLO",
            }
        )
        self.kb.allow_variant_profile(family_id, profile_id)
        return self.kb.create_canonical_card(localized_id, profile_id)


class GCCShadowTests(SidecarTestCase):
    def test_active_fixed_price_listing_is_an_unresolved_snapshot(self):
        self.ingest(gcc_record(gcc_payload()))
        row = self.kb.connection.execute(
            """
            SELECT o.*, snapshot.snapshot_status
            FROM market_observation AS o
            JOIN listing_snapshot AS snapshot ON snapshot.observation_id = o.id
            """
        ).fetchone()
        self.assertEqual(row["observation_type"], "LISTING_SNAPSHOT")
        self.assertEqual(row["snapshot_status"], "ON_SALE:FIXED_PRICE")
        self.assertEqual(row["observed_at"], T1)
        self.assertEqual(row["source_updated_at"], T0)
        self.assertIsNone(row["canonical_card_id"])
        prices = self.kb.price_components(row["id"])
        self.assertEqual(
            [(price["component_type"], price["amount_minor"], price["currency"])
             for price in prices],
            [("ITEM_PRICE", 3000, "EUR")],
        )
        self.assertEqual(self.sidecar.diagnostics.unresolved_identities_retained, 1)
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM sale_transaction").fetchone()[0],
            0,
        )

    def test_active_auction_keeps_end_and_bid_evidence_without_a_sale(self):
        payload = gcc_payload(mode="AUCTION")
        payload.update({"endTime": T3, "bidsNumber": 7, "sellerId": "seller-7"})
        self.ingest(gcc_record(payload))
        snapshot = self.kb.connection.execute(
            "SELECT snapshot_status FROM listing_snapshot"
        ).fetchone()
        self.assertEqual(snapshot["snapshot_status"], "ON_SALE:AUCTION")
        claims = {
            row["field_name"]: row["claimed_value_json"]
            for row in self.kb.connection.execute("SELECT * FROM field_claim")
        }
        self.assertEqual(claims["auction_end_at"], f'"{T3}"')
        self.assertEqual(claims["bid_count"], "7")
        self.assertEqual(claims["seller_identifier"], '"seller-7"')
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM sale_transaction").fetchone()[0],
            0,
        )

    def test_price_change_and_later_same_payload_preserve_history(self):
        first = gcc_payload(price=3000)
        second = gcc_payload(price=2500)
        self.ingest(gcc_record(first, T1))
        self.ingest(gcc_record(second, T3))
        amounts = [
            row["amount_minor"]
            for row in self.kb.connection.execute(
                "SELECT amount_minor FROM price_component ORDER BY created_at, id"
            )
        ]
        self.assertEqual(amounts, [3000, 2500])
        self.assertEqual(self.kb.observation_count(), 2)

        self.ingest(gcc_record(second, "2026-08-14T10:00:00Z"))
        self.assertEqual(self.kb.observation_count(), 3)
        source_record = self.kb.connection.execute(
            """
            SELECT id FROM source_record WHERE source_native_record_id = ?
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (second["id"],),
        ).fetchone()
        self.assertEqual(len(self.kb.source_record_retrievals(source_record["id"])), 2)

    def test_exact_same_replay_is_deterministically_idempotent(self):
        record = gcc_record(gcc_payload())
        self.ingest(record)
        first_id = self.kb.connection.execute(
            "SELECT id FROM market_observation"
        ).fetchone()[0]
        self.ingest(record)
        self.assertEqual(self.kb.observation_count(), 1)
        self.assertEqual(self.sidecar.diagnostics.observations_accepted, 1)
        self.assertEqual(self.sidecar.diagnostics.observations_replayed, 1)
        self.assertEqual(
            self.kb.connection.execute("SELECT id FROM market_observation").fetchone()[0],
            first_id,
        )
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM field_claim").fetchone()[0],
            11,
        )

    def test_unresolved_identity_retains_evidence_without_provider_defaults(self):
        payload = gcc_payload()
        collectible = payload["item"]["collectible"]
        collectible.pop("language")
        collectible.pop("set")
        collectible.pop("reference")
        self.ingest(gcc_record(payload))
        fields = {
            row[0]
            for row in self.kb.connection.execute(
                "SELECT field_name FROM field_claim"
            )
        }
        self.assertFalse(
            fields
            & {
                "language",
                "set",
                "collector_number",
                "edition",
                "finish",
                "print_variant",
                "stamp",
                "shadow_treatment",
            }
        )
        resolution = self.kb.connection.execute(
            "SELECT * FROM identity_resolution"
        ).fetchone()
        self.assertEqual(resolution["resolution_state"], ResolutionState.UNKNOWN.value)
        self.assertIsNone(resolution["canonical_card_id"])
        self.assertIn("edition", resolution["unresolved_dimensions_json"])
        self.assertIn("finish", resolution["unresolved_dimensions_json"])

    def test_only_explicit_completed_sale_evidence_creates_a_transaction(self):
        active = gcc_payload()
        self.ingest(gcc_record(active, T1))

        incomplete = gcc_payload(status="SOLD", price=2500)
        incomplete["endTime"] = T3
        self.ingest(gcc_record(incomplete, T3))
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM sale_transaction").fetchone()[0],
            0,
        )

        completed = gcc_payload(status="SOLD", price=2500)
        completed.update({"soldPriceInCents": 2400, "soldAt": T3})
        self.ingest(gcc_record(completed, "2026-08-14T10:00:00Z"))
        sale = self.kb.connection.execute(
            """
            SELECT o.event_at, sale.transaction_status, price.amount_minor
            FROM market_observation AS o
            JOIN sale_transaction AS sale ON sale.observation_id = o.id
            JOIN price_component AS price ON price.observation_id = o.id
            """
        ).fetchone()
        self.assertEqual(sale["event_at"], T3)
        self.assertEqual(sale["transaction_status"], "COMPLETED")
        self.assertEqual(sale["amount_minor"], 2400)
        self.assertEqual(self.sidecar.diagnostics.fabricated_sales, 0)

    def test_bundle_sale_cannot_masquerade_as_an_exact_single_card(self):
        listing_id = "22222222-2222-2222-2222-222222222222"
        active = gcc_payload(listing_id, title="Lot 2x Charizard", price=5000)
        active["quantity"] = 2
        self.ingest(gcc_record(active, T1))

        card_id = self.canonical_card()
        identifier = self.kb.connection.execute(
            """
            SELECT identifier.id
            FROM external_identifier AS identifier
            WHERE namespace = 'GCC_LISTING_ID' AND identifier_value = ?
            """,
            (listing_id,),
        ).fetchone()
        self.kb.link_identifier(
            identifier["id"], ResolutionState.PROVEN, canonical_card_id=card_id
        )

        sold = gcc_payload(
            listing_id,
            title="Lot 2x Charizard",
            price=5000,
            status="SOLD",
        )
        sold.update({"quantity": 2, "soldPriceInCents": 4800, "soldAt": T3})
        self.ingest(gcc_record(sold, T3))
        sale = self.kb.connection.execute(
            """
            SELECT o.canonical_card_id
            FROM market_observation AS o
            JOIN sale_transaction AS sale ON sale.observation_id = o.id
            """
        ).fetchone()
        self.assertIsNone(sale["canonical_card_id"])
        resolution = self.kb.connection.execute(
            """
            SELECT resolution_state, canonical_card_id
            FROM identity_resolution ORDER BY created_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
        self.assertEqual(resolution["resolution_state"], "UNKNOWN")
        self.assertIsNone(resolution["canonical_card_id"])

    def test_preproven_listing_identifier_can_link_a_later_exact_snapshot(self):
        record = gcc_record(gcc_payload(), T1)
        self.ingest(record)
        card_id = self.canonical_card()
        identifier = self.kb.connection.execute(
            "SELECT id FROM external_identifier WHERE namespace = 'GCC_LISTING_ID'"
        ).fetchone()
        self.kb.link_identifier(
            identifier["id"], ResolutionState.PROVEN, canonical_card_id=card_id
        )
        changed = gcc_payload(price=2500)
        self.ingest(gcc_record(changed, T3))
        latest = self.kb.connection.execute(
            "SELECT canonical_card_id FROM market_observation ORDER BY observed_at DESC"
        ).fetchone()
        self.assertEqual(latest["canonical_card_id"], card_id)
        self.assertEqual(self.sidecar.diagnostics.exact_identities_linked, 1)


class TCGdexMetricTests(SidecarTestCase):
    def pricing_payload(self) -> dict:
        return {
            "id": "base1-4",
            "name": "Charizard",
            "localId": "4",
            "set": {"id": "base1", "name": "Base Set"},
            "pricing": {
                "cardmarket": {
                    "unit": "EUR",
                    "updated": T0,
                    "avg": 100.01,
                    "low": 80,
                    "trend": 99.5,
                    "avg1": 98,
                    "avg7": 96,
                    "avg30": 93,
                    "avg7-holo": 101,
                },
                "tcgplayer": {
                    "unit": "USD",
                    "updatedAt": T0,
                    "holofoil": {
                        "lowPrice": 90,
                        "midPrice": 100,
                        "highPrice": 120,
                        "marketPrice": 105,
                        "directLowPrice": 95,
                    },
                    "reverseHolofoil": {
                        "lowPrice": 70,
                        "marketPrice": 85,
                    },
                },
            },
            "variants": {"holo": True, "reverse": True},
            "variants_detailed": {"unstable": "must not be read"},
        }

    def test_all_embedded_metrics_are_distinct_provider_observations(self):
        self.ingest(tcgdex_record(self.pricing_payload()))
        rows = self.kb.connection.execute(
            """
            SELECT o.observation_type, source.code AS source_code,
                   upstream.code AS upstream_code, metric.metric_name,
                   metric.metric_value_minor, metric.currency
            FROM market_observation AS o
            JOIN source_system AS source ON source.id = o.source_system_id
            JOIN source_system AS upstream ON upstream.id = o.upstream_market_system_id
            JOIN provider_metric_observation AS metric ON metric.observation_id = o.id
            ORDER BY metric.metric_name
            """
        ).fetchall()
        self.assertEqual(len(rows), 14)
        self.assertEqual(len({row["metric_name"] for row in rows}), 14)
        self.assertEqual({row["source_code"] for row in rows}, {"tcgdex"})
        self.assertEqual(
            {row["upstream_code"] for row in rows}, {"cardmarket", "tcgplayer"}
        )
        self.assertEqual(
            {row["observation_type"] for row in rows},
            {ObservationType.PROVIDER_METRIC_OBSERVATION.value},
        )
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) FROM sale_transaction").fetchone()[0],
            0,
        )
        self.assertEqual(self.sidecar.diagnostics.provider_metrics_stored, 14)
        self.assertEqual(self.sidecar.diagnostics.fabricated_sales, 0)

    def test_provider_observed_and_ingested_times_and_windows_stay_separate(self):
        self.ingest(tcgdex_record(self.pricing_payload()))
        row = self.kb.connection.execute(
            """
            SELECT o.observed_at, o.ingested_at, o.source_updated_at,
                   metric.window_started_at, metric.window_ended_at
            FROM market_observation AS o
            JOIN provider_metric_observation AS metric ON metric.observation_id = o.id
            WHERE metric.metric_name = 'CARDMARKET_AVG_7D:GENERIC'
            """
        ).fetchone()
        self.assertEqual(row["observed_at"], T1)
        self.assertEqual(row["ingested_at"], T2)
        self.assertEqual(row["source_updated_at"], T0)
        updated = datetime.fromisoformat(T0.replace("Z", "+00:00"))
        self.assertEqual(
            row["window_started_at"],
            (updated - timedelta(days=7)).isoformat(timespec="microseconds"),
        )
        self.assertEqual(row["window_ended_at"], T0)
        metric_names = {
            row[0]
            for row in self.kb.connection.execute(
                "SELECT metric_name FROM provider_metric_observation"
            )
        }
        self.assertIn("CARDMARKET_AVG_1D:GENERIC", metric_names)
        self.assertIn("CARDMARKET_AVG_7D:GENERIC", metric_names)
        self.assertIn("CARDMARKET_AVG_30D:GENERIC", metric_names)

    def test_market_bucket_is_evidence_not_a_fabricated_exact_variant(self):
        self.ingest(tcgdex_record(self.pricing_payload()))
        observations = self.kb.connection.execute(
            "SELECT canonical_card_id FROM market_observation"
        ).fetchall()
        self.assertTrue(all(row["canonical_card_id"] is None for row in observations))
        fields = {
            row[0]
            for row in self.kb.connection.execute(
                "SELECT DISTINCT field_name FROM field_claim"
            )
        }
        self.assertIn("market_segment", fields)
        self.assertNotIn("finish", fields)
        self.assertNotIn("edition", fields)
        self.assertNotIn("print_variant", fields)
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT COUNT(*) FROM identity_resolution WHERE resolution_state = 'UNKNOWN'"
            ).fetchone()[0],
            4,
        )

    def test_tcgdex_replay_is_deterministic(self):
        record = tcgdex_record(self.pricing_payload())
        self.ingest(record)
        first_ids = {
            row[0] for row in self.kb.connection.execute("SELECT id FROM market_observation")
        }
        self.ingest(record)
        second_ids = {
            row[0] for row in self.kb.connection.execute("SELECT id FROM market_observation")
        }
        self.assertEqual(second_ids, first_ids)
        self.assertEqual(self.kb.observation_count(), 14)
        self.assertEqual(self.sidecar.diagnostics.observations_accepted, 14)
        self.assertEqual(self.sidecar.diagnostics.observations_replayed, 14)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class CollectorAndIsolationTests(SidecarTestCase):
    def test_collectors_only_return_raw_records(self):
        gcc_calls = []

        def gcc_get(url, **kwargs):
            gcc_calls.append((url, kwargs))
            return _FakeResponse(
                {
                    "info": {"currentPage": 1, "nextPage": None},
                    "results": [gcc_payload()],
                }
            )

        gcc_result = GCCMarketplaceCollector(
            http_get=gcc_get, clock=lambda: T1
        ).collect("auction")
        self.assertEqual(len(gcc_result.records), 1)
        self.assertEqual(gcc_result.records[0].payload["priceInCents"], 3000)
        self.assertEqual(
            gcc_calls[0][1]["params"]["sellingTypeGroup"], "AUCTION"
        )

        tcgdex_payload = {"id": "base1-4", "pricing": {}}
        tcgdex_result = TCGdexCollector(
            http_get=lambda *args, **kwargs: _FakeResponse(tcgdex_payload),
            clock=lambda: T1,
        ).collect_card("en", "request-target-must-not-be-used-as-evidence")
        self.assertEqual(tcgdex_result.records[0].source_native_record_id, "base1-4")

    def test_source_failure_is_isolated_and_later_gcc_record_persists(self):
        broken = RawSourceRecord(
            source_code="broken",
            source_name="Broken",
            source_role="PROVIDER",
            source_native_record_id="broken-1",
            payload={"id": "broken-1"},
            retrieved_at=T1,
        )

        def fail_normalizer(_record):
            raise RuntimeError("fixture failure")

        sidecar = ShadowSidecar(
            self.persistence,
            normalizers={
                "broken": fail_normalizer,
                "gcc": __import__(
                    "robot_kb.sidecar.normalizers", fromlist=["normalize_gcc"]
                ).normalize_gcc,
            },
        )
        sidecar.run_source("broken", lambda: CollectionResult((broken,)))
        sidecar.run_source(
            "gcc", lambda: CollectionResult((gcc_record(gcc_payload()),))
        )
        self.assertEqual(sidecar.diagnostics.source_failures, 1)
        self.assertEqual(sidecar.diagnostics.observations_accepted, 1)
        self.assertEqual(self.kb.observation_count(), 1)

    def test_v4_entrypoints_have_no_sidecar_dependency(self):
        root = Path(__file__).resolve().parents[1]
        production_files = [
            root / "watcher.py",
            root / "run_watcher_safe.py",
            root / "run_watcher_multimarket.py",
            root / "run_final_auction_check.py",
            root / "v4_auction_item_discovery.py",
            root / "v4_auction_last_chance.py",
        ]
        for path in production_files:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("robot_kb.sidecar", source, path.name)
            self.assertNotIn("from robot_kb import sidecar", source, path.name)


if __name__ == "__main__":
    unittest.main()
