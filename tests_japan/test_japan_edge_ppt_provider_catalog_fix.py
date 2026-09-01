import unittest
from decimal import Decimal

import japan_edge_hunter as base
import japan_edge_ppt_provider_catalog_fix as fix

shadow = fix.shadow


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers = {
            "X-Api-Calls-Consumed": "1",
            "X-Ratelimit-Daily-Remaining": "19999",
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
        return Decimal(str(amount))


def identity(set_name="151", number="166/165", year=2023):
    return base.Identity(
        name="Bulbasaur",
        set_name=set_name,
        number=number,
        language="Japanese",
        grader="PSA",
        grade="10",
        year=year,
        edition="Unlimited",
        attribute="",
        variety="Full Art",
        rarity="Art Rare",
    )


class ProviderCatalogFixTests(unittest.TestCase):
    def test_151_uses_observed_numeric_ppt_set_id(self):
        self.assertEqual(shadow.expected_provider_set_id(identity()), "23599")
        self.assertIsNone(
            shadow.expected_provider_set_id(
                identity("VSTAR Universe", "228/172", 2022)
            )
        )

    def test_missing_row_language_is_allowed_only_with_exact_reviewed_set_id(self):
        row = {
            "name": "Bulbasaur - 166/165",
            "setId": 23599,
            "setName": "SV2a: Pokemon Card 151",
            "cardNumber": "166/165",
            "tcgPlayerId": "566511",
            "rarity": "Art Rare",
        }
        match = fix.match_japanese_identity(identity(), [row], "23599")
        self.assertEqual(match.status, "EXACT")
        self.assertEqual(
            match.reason, "JP_QUERY_SCOPE_PROVIDER_SET_ID_NUMBER_AND_VARIANT"
        )
        wrong = fix.match_japanese_identity(
            identity(), [dict(row, setId=23908)], "23599"
        )
        self.assertEqual(wrong.status, "CLEAN_NO_MATCH")

    def test_explicit_non_japanese_row_is_rejected(self):
        row = {
            "name": "Bulbasaur - 166/165",
            "setId": 23599,
            "setName": "SV2a: Pokemon Card 151",
            "cardNumber": "166/165",
            "language": "English",
        }
        self.assertEqual(
            fix.match_japanese_identity(identity(), [row], "23599").status,
            "CLEAN_NO_MATCH",
        )

    def test_live_shape_can_reach_exact_psa10_aggregate(self):
        shallow = {
            "name": "Bulbasaur - 166/165",
            "setId": 23599,
            "setName": "SV2a: Pokemon Card 151",
            "cardNumber": "166/165",
            "tcgPlayerId": "566511",
            "rarity": "Art Rare",
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
        snapshot, diagnostics = shadow.fetch_japanese_snapshot(
            identity(),
            api_key="fake",
            budget=shadow.PptBudget(interval_seconds=0),
            session=session,
            fx=FakeFx(),
            now=shadow.datetime(2026, 8, 16, tzinfo=shadow.timezone.utc),
        )
        self.assertEqual(snapshot.status, "MATCHED")
        self.assertEqual(snapshot.sales_count, 12)
        self.assertEqual(snapshot.fair_value_usd, 102.0)
        self.assertEqual(diagnostics["provider_set_id_expected"], "23599")
        self.assertEqual(session.calls[0][1]["setId"], "23599")
        self.assertEqual(session.calls[0][1]["language"], "japanese")

    def test_unobserved_vstar_set_still_fails_before_network(self):
        session = FakeSession([])
        snapshot, diagnostics = shadow.fetch_japanese_snapshot(
            identity("VSTAR Universe", "228/172", 2022),
            api_key="not-used",
            budget=shadow.PptBudget(interval_seconds=0),
            session=session,
            fx=FakeFx(),
        )
        self.assertEqual(snapshot.status, "CATALOG_SET_ID_UNMAPPED")
        self.assertEqual(session.calls, [])
        self.assertEqual(diagnostics["lookup_strategy"], "UNMAPPED_SET_NO_NETWORK")


if __name__ == "__main__":
    unittest.main()
