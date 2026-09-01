import unittest
from decimal import Decimal

import japan_edge_hunter as base
import japan_edge_ppt_provider_catalog_fix as provider_fix

ppt = provider_fix.shadow


class FakeResponse:
    def __init__(self, payload, status_code=200, consumed=1, remaining=19999):
        self._payload = payload
        self.status_code = status_code
        self.headers = {
            "X-Api-Calls-Consumed": str(consumed),
            "X-Ratelimit-Daily-Remaining": str(remaining),
        }

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, dict(kwargs.get("params") or {})))
        if not self.responses:
            raise AssertionError("unexpected provider call")
        return self.responses.pop(0)


class FakeFx:
    def convert(self, amount, source, target, on_date):
        self.last = (amount, source, target, on_date)
        return Decimal(str(amount))


def identity(
    set_name="151",
    number="166/165",
    year=2023,
    edition="Unlimited",
    attribute="",
    variety="Full Art",
):
    return base.Identity(
        name="Bulbasaur",
        set_name=set_name,
        number=number,
        language="Japanese",
        grader="PSA",
        grade="10",
        year=year,
        edition=edition,
        attribute=attribute,
        variety=variety,
        rarity="Art Rare",
    )


class JapanEdgePptExactSetShadowTests(unittest.TestCase):
    def test_reviewed_set_id_mapping(self):
        self.assertEqual(ppt.expected_provider_set_id(identity()), "23599")
        self.assertIsNone(
            ppt.expected_provider_set_id(
                identity("VSTAR Universe", "228/172", 2022)
            )
        )
        self.assertIsNone(
            ppt.expected_provider_set_id(identity("Unknown", "1/100", 2026))
        )

    def test_unmapped_set_fails_before_network(self):
        session = FakeSession([])
        budget = ppt.PptBudget(interval_seconds=0)
        snapshot, diagnostics = ppt.fetch_japanese_snapshot(
            identity("Unknown", "1/100", 2026),
            api_key="not-used",
            budget=budget,
            session=session,
            fx=FakeFx(),
        )
        self.assertEqual(snapshot.status, "CATALOG_SET_ID_UNMAPPED")
        self.assertEqual(session.calls, [])
        self.assertEqual(budget.http_calls, 0)
        self.assertEqual(diagnostics["lookup_strategy"], "UNMAPPED_SET_NO_NETWORK")

    def test_match_requires_japanese_exact_set_id_and_number(self):
        card = identity()
        exact = {
            "setId": 23599,
            "setName": "SV2a: Pokemon Card 151",
            "cardNumber": "166/165",
            "name": "Bulbasaur",
        }
        self.assertEqual(
            ppt.match_japanese_identity(card, [exact], "23599").status,
            "EXACT",
        )
        self.assertEqual(
            ppt.match_japanese_identity(
                card, [dict(exact, setId=23908)], "23599"
            ).status,
            "CLEAN_NO_MATCH",
        )
        self.assertEqual(
            ppt.match_japanese_identity(
                card, [dict(exact, cardNumber="167/165")], "23599"
            ).status,
            "CLEAN_NO_MATCH",
        )
        self.assertEqual(
            ppt.match_japanese_identity(
                card, [dict(exact, language="English")], "23599"
            ).status,
            "CLEAN_NO_MATCH",
        )

    def test_sensitive_variant_stays_fail_closed(self):
        card = identity(variety="Master Ball Reverse")
        row = {
            "setId": 23599,
            "cardNumber": "166/165",
            "name": "Bulbasaur",
            "variant": "Holo",
        }
        match = ppt.match_japanese_identity(card, [row], "23599")
        self.assertEqual(match.status, "MICROVARIANT_UNPROVEN")

    def test_scoped_request_uses_japanese_exact_set_id_and_small_limit(self):
        row = {
            "setId": 23599,
            "setName": "SV2a: Pokemon Card 151",
            "cardNumber": "166/165",
            "name": "Bulbasaur",
            # no row-level language/tcgPlayerId: mirrors the observed PPT shape
        }
        session = FakeSession([FakeResponse({"data": [row]})])
        budget = ppt.PptBudget(interval_seconds=0)
        snapshot, diagnostics = ppt.fetch_japanese_snapshot(
            identity(),
            api_key="fake",
            budget=budget,
            session=session,
            fx=FakeFx(),
        )
        self.assertEqual(snapshot.status, "CLEAN_INSUFFICIENT")
        self.assertEqual(len(session.calls), 1)
        params = session.calls[0][1]
        self.assertEqual(params["language"], "japanese")
        self.assertEqual(params["setId"], "23599")
        self.assertEqual(params["search"], "166")
        self.assertEqual(params["limit"], 5)
        self.assertEqual(diagnostics["provider_set_id_expected"], "23599")

    def test_candidate_diagnostics_are_bounded_and_allow_listed(self):
        rows = [
            {
                "name": f"Card {index}",
                "setId": 23599,
                "setName": "SV2a: Pokemon Card 151",
                "cardNumber": f"{index}/165",
                "tcgPlayerId": str(index),
                "secret": "must-not-leak",
            }
            for index in range(12)
        ]
        diagnostics = ppt.provider_candidate_diagnostics(rows)
        self.assertEqual(len(diagnostics), ppt.MAX_DIAGNOSTIC_CANDIDATES)
        self.assertTrue(all("secret" not in row for row in diagnostics))
        self.assertTrue(
            all(set(row).issubset(set(ppt.DIAGNOSTIC_FIELDS)) for row in diagnostics)
        )

    def test_pending_budget_always_contains_non_economic_schema(self):
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
                        "edition": "Unlimited",
                        "attribute": "",
                        "variety": "Full Art",
                        "rarity": "Art Rare",
                    },
                    "external_reference": {
                        "fair_eur": None,
                    },
                }
            ]
        }
        output = ppt.enrich_report(
            report,
            api_key="not-used",
            budget=ppt.PptBudget(interval_seconds=0),
            session=FakeSession([]),
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

    def test_full_match_parses_psa10_aggregate_without_independence(self):
        shallow = {
            "setId": 23599,
            "setName": "SV2a: Pokemon Card 151",
            "cardNumber": "166/165",
            "name": "Bulbasaur",
            "tcgPlayerId": "123",
        }
        deep = dict(shallow)
        deep["ebay"] = {
            "salesByGrade": {
                "psa10": {
                    "count": 12,
                    "averagePrice": 105.0,
                    "medianPrice": 100.0,
                    "smartMarketPrice": {"price": 102.0},
                    "lastSaleDate": "2026-08-15",
                }
            },
            "priceHistory": {
                "psa10": {
                    "2026-08-01": {"count": 2, "average": 95.0},
                    "2026-08-15": {"count": 3, "average": 105.0},
                }
            },
        }
        session = FakeSession(
            [FakeResponse({"data": [shallow]}), FakeResponse({"data": [deep]})]
        )
        snapshot, diagnostics = ppt.fetch_japanese_snapshot(
            identity(),
            api_key="fake",
            budget=ppt.PptBudget(interval_seconds=0),
            session=session,
            fx=FakeFx(),
            now=ppt.datetime(2026, 8, 16, tzinfo=ppt.timezone.utc),
        )
        self.assertEqual(snapshot.status, "MATCHED")
        self.assertEqual(snapshot.sales_count, 12)
        self.assertEqual(snapshot.fair_value_usd, 102.0)
        self.assertEqual(snapshot.fair_value_eur, 102.0)
        self.assertEqual(diagnostics["provider_set_id_expected"], "23599")
        safe = ppt._safe_payload(snapshot, diagnostics=diagnostics)
        self.assertEqual(safe["independent_market_increment"], 0)
        self.assertIs(safe["production_decision_use"], False)
        self.assertIs(safe["notification_use"], False)


if __name__ == "__main__":
    unittest.main()
