from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
if str(LOCAL) not in sys.path:
    sys.path.insert(0, str(LOCAL))

try:
    harvest = importlib.import_module("robot_kb_multisource_harvest")
    entrypoint = importlib.import_module("robot_kb_multisource_entrypoint")
    p3_compat = importlib.import_module("robot_kb_multisource_p3_compat")
except ModuleNotFoundError as error:
    # The broad V4 test workflow intentionally does not checkout the pinned P3
    # Robot KB runtime. The dedicated Robot KB workflow adds .robot-kb-p3 to
    # PYTHONPATH and must execute this suite fully.
    if error.name == "robot_kb":
        harvest = None
        entrypoint = None
        p3_compat = None
    else:
        raise


@unittest.skipIf(harvest is None, "pinned Robot KB P3 runtime is not present in this V4-only test lane")
class RobotKbMultisourceHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = (LOCAL / "robot_kb_local_runner.sh").read_text(encoding="utf-8")
        cls.installer = (LOCAL / "Installer Robot KB Local.command").read_text(encoding="utf-8")
        cls.harvester = (LOCAL / "robot_kb_multisource_harvest.py").read_text(encoding="utf-8")
        cls.entrypoint_source = (LOCAL / "robot_kb_multisource_entrypoint.py").read_text(encoding="utf-8")
        cls.provider_config = (LOCAL / "Configurer APIs Robot KB.command").read_text(encoding="utf-8")

    def test_catalog_scope_is_single_cards_across_us_eu_and_english_japanese(self):
        self.assertEqual(
            harvest.POKETRACE_LANES,
            (
                ("US", "pokemon"),
                ("US", "pokemon-japanese"),
                ("EU", "pokemon"),
                ("EU", "pokemon-japanese"),
            ),
        )
        self.assertIn('"product_type": "single"', self.harvester)

    def test_provider_auth_contracts_use_only_runtime_keys(self):
        self.assertIn('{"X-API-Key": key, "Accept": "application/json"}', self.harvester)
        self.assertIn('{"Authorization": f"Bearer {key}", "Accept": "application/json"}', self.harvester)
        self.assertNotIn("RobotPokemonKB.poketrace-api", self.harvester)
        self.assertNotIn("RobotPokemonKB.ppt-api", self.harvester)

    def test_provider_evidence_classes_never_promote_asks_to_sold(self):
        self.assertEqual(harvest.evidence_class("ebay"), "SOLD_AGGREGATED")
        self.assertEqual(harvest.evidence_class("cardmarket_unsold"), "FIXED_ASK_AGGREGATED")
        self.assertEqual(harvest.evidence_class("cardmarket"), "MARKET_AGGREGATED")
        self.assertEqual(harvest.evidence_class("tcgplayer"), "MARKET_AGGREGATED")

    def test_poketrace_history_preserves_source_class_and_sale_count(self):
        payload = {
            "data": [
                {"date": "2026-08-20", "source": "ebay", "avg": 123.45, "saleCount": 4},
                {"date": "2026-08-20", "source": "cardmarket_unsold", "avg": 88.0},
            ],
            "pagination": {"hasMore": False},
        }
        metrics = harvest.poketrace_history_metrics(
            payload,
            "card-1",
            "PSA_10",
            "US",
            "2026-08-26T12:00:00+00:00",
        )
        sold = [row for row in metrics if row.market == "ebay"]
        asks = [row for row in metrics if row.market == "cardmarket_unsold"]
        self.assertTrue(sold)
        self.assertTrue(asks)
        self.assertTrue(all(row.evidence_class == "SOLD_AGGREGATED" for row in sold))
        self.assertTrue(all(row.sample_size == 4 for row in sold))
        self.assertTrue(all(row.evidence_class == "FIXED_ASK_AGGREGATED" for row in asks))

    def test_ppt_graded_metrics_are_aggregate_sold_not_item_level_sales(self):
        card = {
            "tcgPlayerId": "42",
            "name": "Pikachu",
            "setName": "Example Set",
            "cardNumber": "001/100",
            "ebay": {
                "salesByGrade": {
                    "PSA 10": {
                        "count": 7,
                        "medianPrice": 250,
                        "averagePrice": 260,
                        "lastSaleDate": "2026-08-25T10:00:00Z",
                    }
                }
            },
        }
        metrics = harvest.ppt_card_metrics(card, "2026-08-26T12:00:00+00:00")
        graded = [row for row in metrics if row.name.startswith("PPT_EBAY_GRADED")]
        self.assertGreaterEqual(len(graded), 2)
        self.assertTrue(all(row.evidence_class == "SOLD_AGGREGATED" for row in graded))
        self.assertTrue(all(row.sample_size == 7 for row in graded))

    def test_sealed_poketrace_product_is_rejected(self):
        card = {
            "id": "sealed-1",
            "productType": "sealed",
            "prices": {"ebay": {"PSA_10": {"avg": 100}}},
        }
        self.assertEqual(harvest.poketrace_current_metrics(card, "2026-08-26T12:00:00Z"), [])

    def test_marketplace_fingerprint_keeps_baseline_then_material_changes(self):
        first = {
            "market": "magi",
            "source_id": "abc",
            "evidence_type": "FIXED_ASK",
            "price": 1000,
            "currency": "JPY",
            "observed_at": "2026-08-26T10:00:00Z",
            "identity": {"name": "Pikachu", "number": "1/100"},
        }
        later_same = dict(first, observed_at="2026-08-26T12:00:00Z")
        repriced = dict(later_same, price=900)
        self.assertEqual(
            entrypoint.semantic_marketplace_fingerprint(first),
            entrypoint.semantic_marketplace_fingerprint(later_same),
        )
        self.assertNotEqual(
            entrypoint.semantic_marketplace_fingerprint(first),
            entrypoint.semantic_marketplace_fingerprint(repriced),
        )

    def test_p3_compat_uses_only_fields_supported_by_pinned_schema(self):
        listing = SimpleNamespace(evidence_type="FIXED_ASK")
        metric = SimpleNamespace(
            name="PPT_EBAY_GRADED:PSA 10:MEDIAN",
            amount_minor=25000,
            currency="USD",
            event_at="2026-08-25T10:00:00+00:00",
            sample_size=7,
        )
        self.assertEqual(
            set(p3_compat.listing_fact(listing)),
            p3_compat.P3_LISTING_FACT_FIELDS,
        )
        self.assertEqual(
            set(p3_compat.provider_metric_fact(metric)),
            p3_compat.P3_PROVIDER_METRIC_FACT_FIELDS,
        )
        self.assertNotIn("provider_sale_evidence", p3_compat.listing_fact(listing))
        self.assertNotIn("evidence_class", p3_compat.provider_metric_fact(metric))
        self.assertNotIn("item_level_sold", p3_compat.provider_metric_fact(metric))
        self.assertIn("p3_compat.install(harvest)", self.entrypoint_source)

    def test_p3_compat_provider_metric_does_not_redeclare_existing_market_source(self):
        try:
            from robot_kb.repository import KnowledgeBase
        except ModuleNotFoundError:
            self.skipTest("pinned Robot KB P3 runtime is not present in this V4-only test lane")

        p3_compat.install(harvest)
        metric = harvest.Metric(
            provider="poketrace",
            native_id="metric-cardmarket-1",
            name="POKETRACE_CURRENT:CARDMARKET:PSA_10:AVG",
            amount_minor=12345,
            currency="EUR",
            observed_at="2026-08-27T00:30:00+00:00",
            event_at="2026-08-26T00:00:00+00:00",
            precision="DAY",
            sample_size=4,
            evidence_class="MARKET_AGGREGATED",
            card_id="card-1",
            claims=(("card_name", "Pikachu"),),
            market="cardmarket",
        )
        self.assertEqual(p3_compat.provider_metric_upstream(metric), (None, None))
        with KnowledgeBase.open(":memory:") as kb:
            # Reproduce the physical Mac failure: this global code already exists
            # under metadata that is not the synthetic MARKET row P3 would create.
            kb.create_source_system("cardmarket", "Cardmarket", "LISTING_PLATFORM")
            stored = harvest.persist_metrics(
                kb,
                (metric,),
                {"source": "cardmarket", "avg": 123.45},
                "poketrace-card:EU:card-1",
                "poketrace",
                "2026-08-27T00:30:00+00:00",
            )
            self.assertEqual(stored, 1)
            row = kb.connection.execute(
                "SELECT upstream_market_system_id FROM market_observation "
                "WHERE source_native_record_id = ?",
                (metric.native_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(row["upstream_market_system_id"])

    def test_401_and_403_provider_auth_failures_are_fail_visible(self):
        for status in (401, 403):
            fake = SimpleNamespace(
                request_json=lambda *_args, _status=status, **_kwargs: (_status, {}, {}),
            )
            p3_compat.install(fake)
            diag = harvest.Diagnostics()
            result_status, _payload, _headers = fake.request_json(
                object(), "https://example.invalid", {}, {}, 1, diag, "provider"
            )
            self.assertEqual(result_status, status)
            self.assertEqual(diag.source_failures, 1)

    def test_runner_reads_provider_keys_from_keychain_only_and_preserves_v4_quota(self):
        self.assertIn('POKETRACE_KEYCHAIN_SERVICE="RobotPokemonKB.poketrace-api"', self.runner)
        self.assertIn('PPT_KEYCHAIN_SERVICE="RobotPokemonKB.ppt-api"', self.runner)
        self.assertIn('security find-generic-password -w -a "$PROVIDER_KEYCHAIN_ACCOUNT"', self.runner)
        self.assertIn('ROBOT_KB_PPT_REMAINING_RESERVE:-15000', self.runner)
        self.assertIn('ROBOT_KB_POKETRACE_REMAINING_RESERVE:-5000', self.runner)
        self.assertIn('robot_kb_multisource_entrypoint.py', self.runner)
        self.assertIn('acquire_lock multisource', self.runner)
        self.assertIn('acquire_lock collector', self.runner)

    def test_installer_wires_public_and_paid_launchagents_without_secrets_in_plist(self):
        self.assertIn('python" -m playwright install chromium', self.installer)
        self.assertIn('com.robotpokemon.kb.markets', self.installer)
        self.assertIn('com.robotpokemon.kb.paid', self.installer)
        self.assertIn('range(0, 24, 2)', self.installer)
        self.assertIn('(1, 7, 13, 19)', self.installer)
        self.assertIn('security add-generic-password -U -a "$PROVIDER_KEYCHAIN_ACCOUNT"', self.installer)
        launchagent_block = self.installer.split("<<'PY'", 1)[1].split("\nPY", 1)[0]
        self.assertNotIn("POKETRACE_API_KEY", launchagent_block)
        self.assertNotIn("POKEMON_PRICE_TRACKER_API_KEY", launchagent_block)
        self.assertNotIn("PGPASSWORD", launchagent_block)

    def test_provider_repair_helper_validates_before_keychain_overwrite(self):
        self.assertIn("https://api.poketrace.com/v1/auth/info", self.provider_config)
        self.assertIn("https://www.pokemonpricetracker.com/api/v2/sets?language=english", self.provider_config)
        self.assertIn('security add-generic-password -U -a "$ACCOUNT"', self.provider_config)
        self.assertIn('if [ "$status" != "200" ]', self.provider_config)
        self.assertIn('"$RUNNER" paid', self.provider_config)
        self.assertNotIn("echo $candidate", self.provider_config)

    def test_paid_access_window_and_safety_flags_are_explicit(self):
        self.assertEqual(harvest.DEFAULT_PAID_UNTIL, "2026-09-12T00:00:00Z")
        payload = harvest.Diagnostics().payload()
        self.assertFalse(payload["automatic_purchase"])
        self.assertFalse(payload["automatic_bid"])
        self.assertFalse(payload["automatic_checkout"])
        self.assertFalse(payload["automatic_payment"])
        self.assertFalse(payload["marketplace_ask_is_sold"])
        self.assertFalse(payload["provider_aggregate_is_item_level_sold"])


if __name__ == "__main__":
    unittest.main()