from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
MODULE_PATH = LOCAL / "robot_kb_ebay_rapidapi_shadow.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_ebay_rapidapi_shadow", MODULE_PATH)
assert SPEC and SPEC.loader
shadow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shadow
SPEC.loader.exec_module(shadow)


def product(**overrides):
    row = {
        "item_id": "123456789012",
        "title": "Pokemon Pikachu 025/165 English PSA 10",
        "sale_price": 105.5,
        "currency": "$",
        "condition": "Graded",
        "buying_format": "Auction",
        "date_sold": "Aug 20, 2026",
        "image_url": "https://i.ebayimg.com/example.jpg",
        "shipping_price": 5.25,
        "link": "https://www.ebay.com/itm/123456789012",
    }
    row.update(overrides)
    return row


def payload(products=None, **overrides):
    value = {
        "success": True,
        "average_price": 9999,
        "median_price": 8888,
        "min_price": 1,
        "max_price": 99999,
        "results": len(products or []),
        "total_results": len(products or []),
        "products": products or [],
    }
    value.update(overrides)
    return value


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.headers = {"x-ratelimit-remaining": "49"}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def post(self, url, *, headers, json, timeout):
        self.calls.append((url, headers, json, timeout))
        return self.response

    def close(self):
        self.closed = True


class FakeObservationType(Enum):
    PROVIDER_METRIC_OBSERVATION = "PROVIDER_METRIC_OBSERVATION"


class FakeSourceKind(Enum):
    PROVIDER = "PROVIDER"


@dataclass(frozen=True)
class FakeClaim:
    field_name: str
    value: object
    source_kind: object


class FakeObservation:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class RapidApiShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = (LOCAL / "robot_kb_local_runner.sh").read_text(encoding="utf-8")
        cls.configurer = (LOCAL / "Configurer APIs Robot KB.command").read_text(encoding="utf-8")
        cls.installer = (LOCAL / "Installer Robot KB Local.command").read_text(encoding="utf-8")
        cls.module_source = MODULE_PATH.read_text(encoding="utf-8")

    def test_request_is_post_products_only_and_outlier_removal_disabled(self):
        body = shadow.build_request_body("Pokemon Pikachu PSA 10")
        self.assertEqual(body["keywords"], "Pokemon Pikachu PSA 10")
        self.assertEqual(body["max_search_results"], 60)
        self.assertEqual(body["site_id"], "0")
        self.assertIs(body["remove_outliers"], False)

    def test_valid_auction_becomes_completed_item_shadow_candidate(self):
        parsed = shadow.parse_response(payload([product()]))
        self.assertFalse(parsed.provider_error)
        self.assertEqual(len(parsed.candidates), 1)
        row = parsed.candidates[0]
        self.assertEqual(row.item_id, "123456789012")
        self.assertEqual(row.sale_price_minor, 10550)
        self.assertEqual(row.shipping_price_minor, 525)
        self.assertEqual(row.currency, "USD")
        self.assertEqual(row.date_sold, "2026-08-20")
        self.assertFalse(row.accepted_offer_ambiguous)

    def test_accepts_offers_is_explicitly_ambiguous_final_price(self):
        parsed = shadow.parse_response(payload([product(buying_format="Accepts Offers")]))
        self.assertEqual(len(parsed.candidates), 1)
        self.assertTrue(parsed.candidates[0].accepted_offer_ambiguous)
        self.assertEqual(parsed.accepted_offer_ambiguous, 1)

    def test_aggregate_prices_are_ignored_and_never_become_candidates(self):
        parsed = shadow.parse_response(payload([]))
        self.assertEqual(parsed.candidates, ())
        self.assertTrue(parsed.provider_clean_no_match)
        self.assertEqual(
            set(parsed.aggregate_fields_ignored),
            {"average_price", "median_price", "min_price", "max_price"},
        )

    def test_duplicate_item_id_is_deduplicated_across_same_response(self):
        parsed = shadow.parse_response(payload([product(), product(title="same item duplicate")]))
        self.assertEqual(len(parsed.candidates), 1)
        self.assertEqual(parsed.duplicates, 1)

    def test_missing_sale_date_or_bad_item_identity_is_rejected(self):
        rows = [
            product(date_sold=None),
            product(item_id="not-an-id"),
            product(link="https://example.com/itm/123456789012"),
            product(currency="CAD"),
        ]
        parsed = shadow.parse_response(payload(rows))
        self.assertEqual(parsed.candidates, ())
        self.assertEqual(parsed.rejected, 4)
        self.assertFalse(parsed.provider_clean_no_match)

    def test_provider_failure_is_not_clean_no_match(self):
        session = FakeSession(FakeResponse(403, {"message": "Forbidden"}))
        code, summary = shadow.run_probe("secret-value", "Pokemon Pikachu PSA 10", session=session)
        self.assertEqual(code, 1)
        self.assertEqual(summary["http_status"], 403)
        self.assertEqual(summary["provider_error"], "http-403")
        self.assertFalse(summary["provider_clean_no_match"])
        self.assertFalse(summary["item_level_sold"])
        self.assertFalse(summary["genuine_sale_evidence"])

    def test_key_is_header_only_and_never_appears_in_sanitized_output(self):
        secret = "rapid-secret-never-log"
        session = FakeSession(FakeResponse(200, payload([product()])))
        code, summary = shadow.run_probe(secret, "Pokemon Pikachu PSA 10", session=session)
        self.assertEqual(code, 0)
        self.assertEqual(len(session.calls), 1)
        url, headers, body, _timeout = session.calls[0]
        self.assertEqual(url, shadow.RAPIDAPI_URL)
        self.assertEqual(headers["x-rapidapi-key"], secret)
        self.assertNotIn(secret, json.dumps(summary, sort_keys=True))
        self.assertNotIn(secret, json.dumps(body, sort_keys=True))

    def test_shadow_observation_cannot_be_genuine_sale_or_exact_identity(self):
        fake_runtime = (
            FakeObservationType,
            FakeSourceKind,
            FakeClaim,
            FakeObservation,
            object,
            object,
            object,
        )
        parsed = shadow.parse_response(payload([product()]))
        with patch.object(shadow, "_runtime", return_value=fake_runtime):
            observation = shadow.candidate_observation(
                parsed.candidates[0],
                query="Pokemon Pikachu PSA 10",
                observed_at="2026-08-28T12:00:00+00:00",
            )
        self.assertEqual(observation.observation_type, FakeObservationType.PROVIDER_METRIC_OBSERVATION)
        self.assertFalse(observation.genuine_sale_evidence)
        self.assertFalse(observation.exact_identity_eligible)
        self.assertEqual(
            set(observation.fact),
            {"metric_name", "metric_value_minor", "currency", "sample_size"},
        )
        self.assertEqual(
            observation.fact["metric_name"],
            "EBAY_RAPIDAPI_COMPLETED_ITEM_CANDIDATE",
        )
        self.assertEqual(observation.fact["sample_size"], 1)
        self.assertNotIn("upstream_market_code", observation.__dict__)
        self.assertIn("canonical_identity", observation.unresolved_dimensions)
        self.assertIn("commercial_microvariant", observation.unresolved_dimensions)
        self.assertIn("final_price_semantics", observation.unresolved_dimensions)

    def test_real_p3_persistence_keeps_candidate_as_unresolved_provider_metric(self):
        try:
            from robot_kb.repository import KnowledgeBase
        except ModuleNotFoundError:
            self.skipTest("pinned Robot KB P3 runtime is not present in this V4-only test lane")

        raw_payload = payload([product()])
        parsed = shadow.parse_response(raw_payload)
        observed_at = "2026-08-28T12:00:00+00:00"
        with KnowledgeBase.open(":memory:") as kb:
            stored = shadow.persist_shadow_response(
                kb,
                raw_payload,
                parsed,
                query="Pokemon Pikachu PSA 10",
                observed_at=observed_at,
            )
            self.assertEqual(stored, 1)
            row = kb.connection.execute(
                """
                SELECT o.observation_type, o.canonical_card_id,
                       o.upstream_market_system_id,
                       p.metric_name, p.metric_value_minor, p.currency,
                       p.sample_size
                FROM market_observation o
                JOIN provider_metric_observation p ON p.observation_id=o.id
                JOIN source_system s ON s.id=o.source_system_id
                WHERE s.code=? AND o.source_native_record_id=?
                """,
                (shadow.SOURCE_CODE, "ebay-item:123456789012"),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["observation_type"], "PROVIDER_METRIC_OBSERVATION")
            self.assertIsNone(row["canonical_card_id"])
            self.assertIsNone(row["upstream_market_system_id"])
            self.assertEqual(row["metric_name"], "EBAY_RAPIDAPI_COMPLETED_ITEM_CANDIDATE")
            self.assertEqual(row["metric_value_minor"], 10550)
            self.assertEqual(row["currency"], "USD")
            self.assertEqual(row["sample_size"], 1)
            self.assertEqual(
                kb.connection.execute("SELECT COUNT(*) AS n FROM sale_transaction").fetchone()["n"],
                0,
            )

            replay_stored = shadow.persist_shadow_response(
                kb,
                raw_payload,
                parsed,
                query="Pokemon Pikachu PSA 10",
                observed_at="2026-08-28T12:05:00+00:00",
            )
            self.assertEqual(replay_stored, 0)
            self.assertEqual(
                kb.connection.execute(
                    "SELECT COUNT(*) AS n FROM provider_metric_observation"
                ).fetchone()["n"],
                1,
            )

    def test_unsupported_site_is_fail_closed(self):
        with self.assertRaises(ValueError):
            shadow.build_request_body("Pokemon", site_id="77")
        parsed = shadow.parse_response(payload([product()]), site_id="77")
        self.assertEqual(parsed.provider_error, "unsupported-site-id")
        self.assertEqual(parsed.candidates, ())

    def test_mac_runner_reads_rapidapi_key_from_keychain_and_has_manual_modes_only(self):
        self.assertIn('EBAY_RAPIDAPI_KEYCHAIN_SERVICE="RobotPokemonKB.ebay-rapidapi"', self.runner)
        self.assertIn('ROBOT_KB_EBAY_RAPIDAPI_KEY="$(load_optional_secret "$EBAY_RAPIDAPI_KEYCHAIN_SERVICE")"', self.runner)
        self.assertIn('ebay-probe) run_ebay_rapidapi_shadow probe', self.runner)
        self.assertIn('ebay-shadow) run_ebay_rapidapi_shadow ingest', self.runner)
        self.assertIn('unset PGPASSWORD POKETRACE_API_KEY POKEMON_PRICE_TRACKER_API_KEY ROBOT_KB_EBAY_RAPIDAPI_KEY', self.runner)
        self.assertNotIn("ebay-rapidapi", self.installer)

    def test_keychain_config_mode_validates_before_overwrite_and_runs_probe_not_ingest(self):
        self.assertIn('EBAY_RAPIDAPI_SERVICE="RobotPokemonKB.ebay-rapidapi"', self.configurer)
        self.assertIn("ebay-average-selling-price.p.rapidapi.com/findCompletedItems", self.configurer)
        self.assertIn('-H "x-rapidapi-key: $key"', self.configurer)
        self.assertIn('security add-generic-password -U -a "$ACCOUNT"', self.configurer)
        self.assertIn('if [ "${1:-}" = "ebay" ]', self.configurer)
        ebay_block = self.configurer.split('if [ "${1:-}" = "ebay" ]', 1)[1].split("exit 0", 1)[0]
        self.assertIn('"$RUNNER" ebay-probe', ebay_block)
        self.assertNotIn('"$RUNNER" ebay-shadow', ebay_block)
        self.assertNotIn("echo $candidate", self.configurer)

    def test_module_is_robot_kb_shadow_only_and_has_no_v4_runtime_dependency(self):
        self.assertNotIn("import watcher", self.module_source)
        self.assertNotIn("run_watcher", self.module_source)
        self.assertIn('"item_level_sold": False', self.module_source)
        self.assertIn('"v4_economic_use": False', self.module_source)
        self.assertIn('genuine_sale_evidence=False', self.module_source)


if __name__ == "__main__":
    unittest.main()
