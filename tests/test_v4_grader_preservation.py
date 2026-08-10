import unittest

import watcher
from gcc_history_shared import parse_historical_grade


class _Locator:
    def __init__(self, text):
        self._text = text

    @property
    def first(self):
        return self

    def inner_text(self, timeout=None):
        return self._text


class _Page:
    def __init__(self, body, heading=""):
        self.body = body
        self.heading = heading

    def goto(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def locator(self, selector):
        if selector == "body":
            return _Locator(self.body)
        if selector == "h1":
            return _Locator(self.heading)
        raise AssertionError(selector)


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class V4StructuredGraderTests(unittest.TestCase):
    def test_requested_graders_are_distinct_supported_graders(self):
        for grader in ("SFG", "SGS", "SCA", "TCC"):
            with self.subTest(grader=grader):
                self.assertIn(grader, watcher.GRADERS)
                self.assertEqual(
                    watcher.parse_grader_grade(f"{grader} 9.5 Example Card"),
                    (grader, "9.5"),
                )
                evidence = parse_historical_grade(f"{grader} 9.5 Example Card\n25 €")
                self.assertEqual(evidence.grader, grader)
                self.assertEqual(evidence.grade, "9.5")

    def test_inspection_preserves_structured_api_grader_and_grade(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/fixture",
            title="SFG 9.5 Mega Latias Ex",
            current_price=35.0,
            source_type="fixed",
            grader="SFG",
            grade="9.5",
            card_set="Mega Symphonia",
            card_number="079/063",
            language="Japanese",
        )
        page = _Page(
            "Description\nArticle\nGradation\nDétails\nCatégorie\nPokemon\n"
            "Réference\n#079/063\nHistorique des ventes\nPSA 10 Mega Latias Ex\n18 €"
        )
        inspected = watcher.inspect_item(page, lot)
        self.assertEqual(inspected.grader, "SFG")
        self.assertEqual(inspected.grade, "9.5")
        self.assertEqual(watcher.extract_card_identity(inspected)["core"], "Mega Latias Ex")

    def test_unbounded_identity_inventory_omits_max_price_and_keeps_expensive_card(self):
        captured = []
        payload = {
            "info": {"currentPage": 1, "nextPage": None, "counts": {"total": 1}},
            "results": [
                {
                    "id": "fixture-expensive",
                    "priceInCents": 50000,
                    "item": {
                        "title": "PSA 10 Charizard",
                        "gradingCompany": "PSA",
                        "grade": "10",
                        "collectible": {
                            "category": "Pokemon",
                            "language": "English",
                            "yearOfDistribution": "1999",
                            "extension": "Base",
                            "set": "Base Set",
                            "reference": "4/102",
                            "type": "CARDS",
                        },
                    },
                }
            ],
        }

        def get(_url, *, params, **_kwargs):
            captured.append(dict(params))
            return _Response(payload)

        lots = watcher.collect_fixed_lots_from_api(
            http_get=get,
            max_pages=2,
            min_price=0.0,
            max_price=None,
        )
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].current_price, 500.0)
        self.assertNotIn("maxPriceInCents", captured[0])
        self.assertEqual(captured[0]["minPriceInCents"], 0)


if __name__ == "__main__":
    unittest.main()
