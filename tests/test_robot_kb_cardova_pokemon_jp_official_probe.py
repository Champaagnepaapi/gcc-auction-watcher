from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_pokemon_jp_official_probe as probe


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, text="", url=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.url = url or probe.OFFICIAL_RESULT_API

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        response = self.responses.pop(0)
        if response.url == probe.OFFICIAL_RESULT_API and url != probe.OFFICIAL_RESULT_API:
            response.url = url
        return response


class StubCatalog:
    def __init__(self, result):
        self.result = result
        self.result_requests = 0
        self.detail_requests = 0

    def lookup_coordinate(self, local_id, namespace):
        return self.result


class CardovaPokemonJpOfficialProbeTests(unittest.TestCase):
    def record(self, **updates):
        value = {
            "source": "cardova_public_past_auction",
            "source_native_record_id": "01TEST",
            "source_url": "https://www.cardova.co.jp/en/auction/card/01TEST",
            "provider_sale_status": "PAID_COMPLETED",
            "provider_sale_status_proven": True,
            "sale_evidence_ready": True,
            "currency": "JPY",
            "currency_proven": True,
            "final_bid_jpy": 5000000,
            "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
            "certification_number": "153603277",
            "card_name": "Mario Pikachu",
            "set_name": "Pokemon TCG: Japanese XY Promo Mario Pikachu Special Box",
            "collector_number": "#294/XY-P",
            "language": "Japanese",
            "grader": "PSA",
            "grade": "10",
        }
        value.update(updates)
        return value

    def match(self, **updates):
        values = {
            "card_id": "32349",
            "detail_url": "https://www.pokemon-card.com/card-search/details.php/card/32349",
            "official_name": "マリオピカチュウ",
            "printed_number": "294/XY-P",
            "official_set_code": "XYP",
        }
        values.update(updates)
        return probe.OfficialCoordinateMatch(**values)

    def test_structural_promo_set_code_is_not_alias_table(self):
        cases = {
            "XY-P": "XYP",
            "BW-P": "BWP",
            "L-P": "LP",
            "DPt-P": "DPtP",
            "SM-P": "SMP",
        }
        for namespace, expected in cases.items():
            with self.subTest(namespace=namespace):
                code, status = probe.official_set_code(namespace)
                self.assertEqual(code, expected)
                self.assertEqual(status, "STRUCTURAL_PROMO_SET_CODE")

        for namespace in ("", "XY P", "102", "XY-P-EXTRA", "XY"):
            with self.subTest(namespace=namespace):
                code, _status = probe.official_set_code(namespace)
                self.assertEqual(code, "")

    def test_detail_page_requires_exact_printed_coordinate(self):
        html = """
        <html><body>
          <h1>マリオピカチュウ</h1>
          <div class='card'>XYP &nbsp; 294 / XY-P</div>
        </body></html>
        """
        match = probe.extract_exact_coordinate_from_detail(
            html,
            card_id="32349",
            local_id="294",
            namespace="XY-P",
            official_code="XYP",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.card_id, "32349")
        self.assertEqual(match.official_name, "マリオピカチュウ")
        self.assertEqual(match.printed_number, "294/XY-P")

        missing = probe.extract_exact_coordinate_from_detail(
            html,
            card_id="32349",
            local_id="293",
            namespace="XY-P",
            official_code="XYP",
        )
        self.assertIsNone(missing)

    def test_result_api_paginates_and_deduplicates_card_ids(self):
        session = FakeSession([
            FakeResponse(payload={
                "cardList": [{"cardID": "1"}, {"cardID": "2"}],
                "maxPage": 2,
            }),
            FakeResponse(payload={
                "cardList": [{"cardID": "2"}, {"cardID": "3"}],
                "maxPage": 2,
            }),
        ])
        catalog = probe.OfficialPokemonJpCatalog(session=session, delay_seconds=0)
        self.assertEqual(catalog.enumerate_set_card_ids("XYP"), ["1", "2", "3"])
        self.assertEqual(catalog.result_requests, 2)
        self.assertEqual(len(session.calls), 2)
        first_params = session.calls[0][1]["params"]
        self.assertEqual(first_params["pg"], "XYP")
        self.assertEqual(first_params["regulation_sidebar_form"], "all")

    def test_official_lookup_requires_unique_coordinate(self):
        exact_html = "<h1>マリオピカチュウ</h1><div>XYP 294 / XY-P</div>"
        other_html = "<h1>Other</h1><div>XYP 293 / XY-P</div>"
        session = FakeSession([
            FakeResponse(payload={"cardList": [{"cardID": "10"}, {"cardID": "11"}], "maxPage": 1}),
            FakeResponse(text=other_html, url="https://www.pokemon-card.com/card-search/details.php/card/10"),
            FakeResponse(text=exact_html, url="https://www.pokemon-card.com/card-search/details.php/card/11"),
        ])
        catalog = probe.OfficialPokemonJpCatalog(session=session, delay_seconds=0)
        match, status, count = catalog.lookup_coordinate("294", "XY-P")
        self.assertEqual(status, "OFFICIAL_COORDINATE_EXACT_UNIQUE")
        self.assertEqual(count, 1)
        self.assertIsNotNone(match)
        self.assertEqual(match.card_id, "11")

        ambiguous_session = FakeSession([
            FakeResponse(payload={"cardList": [{"cardID": "20"}, {"cardID": "21"}], "maxPage": 1}),
            FakeResponse(text=exact_html, url="https://www.pokemon-card.com/card-search/details.php/card/20"),
            FakeResponse(text=exact_html, url="https://www.pokemon-card.com/card-search/details.php/card/21"),
        ])
        ambiguous = probe.OfficialPokemonJpCatalog(session=ambiguous_session, delay_seconds=0)
        match, status, count = ambiguous.lookup_coordinate("294", "XY-P")
        self.assertIsNone(match)
        self.assertEqual(status, "OFFICIAL_COORDINATE_AMBIGUOUS")
        self.assertEqual(count, 2)

    def test_provider_403_is_fail_visible_not_no_match(self):
        session = FakeSession([FakeResponse(status_code=403, payload={}, url=probe.OFFICIAL_RESULT_API)])
        catalog = probe.OfficialPokemonJpCatalog(session=session, delay_seconds=0)
        with self.assertRaisesRegex(probe.OfficialProviderError, "OFFICIAL_HTTP_403"):
            catalog.enumerate_set_card_ids("XYP")

    def test_probe_proves_macro_only_and_never_sale_transaction(self):
        catalog = StubCatalog((self.match(), "OFFICIAL_COORDINATE_EXACT_UNIQUE", 1))
        row, reason = probe.probe_record(self.record(), catalog=catalog)
        self.assertEqual(reason, "OFFICIAL_COORDINATE_EXACT_UNIQUE")
        self.assertIsNotNone(row)
        self.assertEqual(row["macro_identity_status"], "EXACT")
        self.assertEqual(row["official_card_id"], "32349")
        self.assertTrue(row["official_catalog_entry_unique"])
        self.assertFalse(row["microvariant_exact"])
        self.assertFalse(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_non_japanese_and_nonpromo_records_fail_closed(self):
        catalog = StubCatalog((self.match(), "OFFICIAL_COORDINATE_EXACT_UNIQUE", 1))
        row, reason = probe.probe_record(self.record(language="English"), catalog=catalog)
        self.assertIsNone(row)
        self.assertEqual(reason, "OFFICIAL_JP_LANGUAGE_REQUIRED")

        row, reason = probe.probe_record(self.record(collector_number="102/100"), catalog=catalog)
        self.assertIsNone(row)
        self.assertEqual(reason, "NUMBER_NAMESPACE_ABSENT")

    def test_run_counts_macro_exact_separately_from_microvariant(self):
        catalog = StubCatalog((self.match(), "OFFICIAL_COORDINATE_EXACT_UNIQUE", 1))
        payload = probe.run(
            [self.record(), self.record(source_native_record_id="b", collector_number="102/100")],
            max_records=2,
            catalog=catalog,
        )
        self.assertEqual(payload["japanese_promo_coordinate_candidate_count"], 1)
        self.assertEqual(payload["unique_official_search_set_codes"], ["XYP"])
        self.assertEqual(payload["official_macro_identity_exact_count"], 1)
        self.assertEqual(payload["exact_microvariant_count"], 0)
        self.assertEqual(payload["blocked"].get("NUMBER_NAMESPACE_ABSENT"), 1)
        self.assertEqual(
            payload["blocked"].get("OFFICIAL_COORDINATE_DOES_NOT_PROVE_ALL_COMMERCIAL_VARIANT_AXES"),
            1,
        )

    def test_safety_summary_is_strictly_read_only(self):
        summary = probe.safe_summary()
        self.assertEqual(summary["official_source"], "pokemon-card.com")
        self.assertTrue(summary["structural_set_code_transform_only"])
        self.assertTrue(summary["official_unique_coordinate_required"])
        self.assertTrue(summary["microvariant_exact_required_for_sale_evidence"])
        for key in (
            "provider_set_alias_table_used",
            "fuzzy_matching",
            "translation_assumed",
            "payment_completed_at_proven",
            "robot_kb_write",
            "sale_transaction_stored",
            "sale_transaction_ready",
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
