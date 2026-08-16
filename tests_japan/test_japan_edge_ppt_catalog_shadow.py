import unittest
from decimal import Decimal

import japan_edge_hunter as base
import japan_edge_ppt_shadow as legacy
import japan_edge_ppt_catalog_shadow as catalog


class FakeResponse:
    status_code = 200
    headers = {
        "X-Api-Calls-Consumed": "1",
        "X-Ratelimit-Daily-Remaining": "19999",
    }

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, dict(kwargs.get("params") or {})))
        return FakeResponse(self.payload)


class FakeFx:
    def convert(self, value, source, target, on_date):
        return Decimal(str(value))


def identity(set_name="151", number="166/165", year=2023):
    return base.Identity(
        "Bulbasaur",
        set_name,
        number,
        "Japanese",
        "PSA",
        "10",
        year,
    )


class JapanEdgePptCatalogShadowTests(unittest.TestCase):
    def test_reviewed_exact_set_ids(self):
        self.assertEqual(catalog.expected_provider_set_id(identity()), "sv2a")
        self.assertEqual(
            catalog.expected_provider_set_id(identity("VSTAR Universe", "228/172", 2022)),
            "s12a",
        )
        self.assertIsNone(catalog.expected_provider_set_id(identity("Unknown Set", "1/100", 2026)))

    def test_exact_set_id_and_number_are_mandatory(self):
        card = identity()
        exact = {
            "language": "Japanese",
            "setId": "sv2a",
            "setName": "Pokemon Card 151",
            "cardNumber": "166/165",
            "name": "Bulbasaur",
        }
        wrong_set = dict(exact, setId="sv3")
        wrong_number = dict(exact, cardNumber="167/165")
        self.assertEqual(
            catalog.match_japanese_catalog_identity(card, [exact], "sv2a").status,
            "EXACT",
        )
        self.assertEqual(
            catalog.match_japanese_catalog_identity(card, [wrong_set], "sv2a").status,
            "CLEAN_NO_MATCH",
        )
        self.assertEqual(
            catalog.match_japanese_catalog_identity(card, [wrong_number], "sv2a").status,
            "CLEAN_NO_MATCH",
        )

    def test_scoped_request_uses_language_and_exact_set_id(self):
        row = {
            "language": "Japanese",
            "setId": "sv2a",
            "setName": "Pokemon Card 151",
            "cardNumber": "166/165",
            "name": "Bulbasaur",
            # Intentionally no tcgPlayerId: one request is enough for this test.
        }
        session = FakeSession({"data": [row]})
        budget = legacy.PptBudget(max_http_calls=8, max_credits=40, interval_seconds=0)
        snapshot, diagnostics = catalog.fetch_japanese_snapshot_catalog(
            identity(),
            api_key="not-a-real-secret",
            budget=budget,
            session=session,
            fx=FakeFx(),
        )
        self.assertEqual(snapshot.status, "CLEAN_INSUFFICIENT")
        self.assertEqual(len(session.calls), 1)
        params = session.calls[0][1]
        self.assertEqual(params.get("language"), "japanese")
        self.assertEqual(params.get("setId"), "sv2a")
        self.assertEqual(params.get("search"), "166/165")
        self.assertEqual(diagnostics.get("provider_set_id_expected"), "sv2a")

    def test_candidate_diagnostics_are_bounded_and_non_secret(self):
        rows = [
            {
                "name": f"Card {index}",
                "setId": "sv2a",
                "setName": "Pokemon Card 151",
                "cardNumber": f"{index}/165",
                "language": "Japanese",
                "tcgPlayerId": str(index),
                "apiKey": "must-not-leak",
            }
            for index in range(20)
        ]
        diagnostics = catalog.provider_candidate_diagnostics(rows)
        self.assertEqual(len(diagnostics), catalog.MAX_DIAGNOSTIC_CANDIDATES)
        self.assertTrue(all("apiKey" not in row for row in diagnostics))

    def test_pending_budget_row_always_has_safety_schema(self):
        report = {
            "opportunities": [
                {
                    "identity": {
                        "name": "Bulbasaur",
                        "set_name": "151",
                        "number": "166/165",
                        "language": "Japanese",
                        "grader": "PSA",
                        "grade": "10",
                        "year": 2023,
                        "edition": "",
                        "attribute": "",
                        "variety": "",
                        "rarity": "",
                    }
                }
            ]
        }
        output = catalog.enrich_report_catalog(
            report,
            api_key="not-used",
            budget=legacy.PptBudget(max_http_calls=8, max_credits=40, interval_seconds=0),
            session=FakeSession({"data": []}),
            fx=FakeFx(),
            max_candidates=0,
        )
        shadow = output["opportunities"][0]["ppt_japanese_shadow"]
        self.assertEqual(shadow["status"], "PENDING_BUDGET")
        self.assertEqual(shadow["evidence_class"], "SOLD_AGGREGATED")
        self.assertEqual(shadow["correlation_group"], "EBAY_GRADED_AGGREGATE")
        self.assertEqual(shadow["independent_market_increment"], 0)
        self.assertIs(shadow["production_decision_use"], False)
        self.assertIs(shadow["notification_use"], False)


if __name__ == "__main__":
    unittest.main()
