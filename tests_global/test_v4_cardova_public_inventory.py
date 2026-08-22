from __future__ import annotations

import unittest
from types import SimpleNamespace

import v4_cardova_public_inventory as cardova


class FakeResponse:
    def __init__(self, payload, *, url="https://api.cardova.co.jp/public/list", method="GET", content_type="application/json"):
        self._payload = payload
        self.url = url
        self.request = SimpleNamespace(method=method)
        self.headers = {"content-type": content_type}

    def json(self):
        return self._payload


class FakePage:
    def __init__(self, responses):
        self.responses = list(responses)
        self.handler = None
        self.visited = []

    def on(self, event, handler):
        self.assert_event(event)
        self.handler = handler

    def remove_listener(self, event, handler):
        self.assert_event(event)
        if self.handler is handler:
            self.handler = None

    def goto(self, url, **_kwargs):
        self.visited.append(url)
        if self.handler is not None:
            for response in self.responses:
                self.handler(response)

    def wait_for_timeout(self, _milliseconds):
        return None

    def evaluate(self, _script):
        return None

    @staticmethod
    def assert_event(event):
        if event != "response":
            raise AssertionError(event)


def _fixed(**overrides):
    row = {
        "ulid": "fixed-1",
        "listing_type": 4,
        "asking_price": 25000,
        "set_quantity": 1,
        "authentication_company_code": "P",
        "grade": "10.0",
        "language": "Japanese",
        "player": "Pikachu",
        "variety": "Pokemon TCG: Japanese Scarlet & Violet 151",
        "card_number": "#173/165",
        "category": "Pokemon",
        "token": "must-never-survive",
        "seller_email": "must-never-survive@example.invalid",
    }
    row.update(overrides)
    return row


def _auction(**overrides):
    row = {
        "ulid": "auction-1",
        "listing_type": 1,
        "bid_price": 12000,
        "start_price": 1000,
        "finished": 0,
        "end_date": "2026-08-22T12:00:00+00:00",
        "authentication_company_code": "P",
        "grade": "9",
        "language": "English",
        "player": "Charizard ex",
        "variety": "Pokemon TCG: Scarlet & Violet 151",
        "card_number": "#199/165",
        "category": "Pokemon",
    }
    row.update(overrides)
    return row


class CardovaPublicInventoryTests(unittest.TestCase):
    def test_anonymous_get_json_capture_is_whitelisted_and_deduplicated(self):
        payload = {
            "data": {
                "items": [
                    _fixed(),
                    _auction(),
                    _fixed(ulid="sports", category="Basketball", variety="NBA", player="Player"),
                    _fixed(ulid="bgs", authentication_company_code="BGS"),
                    _fixed(ulid="set", set_quantity=3),
                ]
            }
        }
        page = FakePage([FakeResponse(payload)])
        result = cardova.capture_cardova_public_inventory(page, max_pages_each=2, settle_ms=0)

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.accepted_rows, 2)
        self.assertEqual(len(result.fixed_payload["list"]), 1)
        self.assertEqual(len(result.auction_payload["list"]), 1)
        fixed = result.fixed_payload["list"][0]
        self.assertNotIn("token", fixed)
        self.assertNotIn("seller_email", fixed)
        self.assertEqual(fixed["ulid"], "fixed-1")
        self.assertGreaterEqual(result.rejected_rows.get("non_pokemon_or_unproven_category", 0), 1)
        self.assertGreaterEqual(result.rejected_rows.get("unsupported_grader", 0), 1)
        self.assertGreaterEqual(result.rejected_rows.get("multi_item_set", 0), 1)
        self.assertFalse(result.complete)

    def test_post_or_non_cardova_json_is_never_read(self):
        payload = {"list": [_fixed()]}
        page = FakePage(
            [
                FakeResponse(payload, method="POST"),
                FakeResponse(payload, url="https://example.com/public/list"),
            ]
        )
        result = cardova.capture_cardova_public_inventory(page, max_pages_each=1, settle_ms=0)
        self.assertEqual(result.status, "NO_PUBLIC_JSON")
        self.assertEqual(result.accepted_rows, 0)
        self.assertEqual(result.json_responses, 0)

    def test_non_json_cardova_response_is_ignored(self):
        page = FakePage([FakeResponse({"list": [_fixed()]}, content_type="text/html")])
        result = cardova.capture_cardova_public_inventory(page, max_pages_each=1, settle_ms=0)
        self.assertEqual(result.status, "NO_PUBLIC_JSON")
        self.assertEqual(result.raw_listing_rows, 0)

    def test_scope_requires_en_or_ja_psa_supported_grade_and_card_coordinate(self):
        rows = [
            _fixed(ulid="fr", language="French"),
            _fixed(ulid="psa7", grade="7"),
            _fixed(ulid="no-number", card_number=""),
            _fixed(ulid="good-en", language="English", grade="8.5"),
        ]
        page = FakePage([FakeResponse({"payload": {"listings": rows}})])
        result = cardova.capture_cardova_public_inventory(page, max_pages_each=1, settle_ms=0)
        self.assertEqual([row["ulid"] for row in result.fixed_payload["list"]], ["good-en"])
        self.assertGreaterEqual(result.rejected_rows.get("unsupported_language", 0), 1)
        self.assertGreaterEqual(result.rejected_rows.get("unsupported_grade", 0), 1)
        self.assertGreaterEqual(result.rejected_rows.get("missing_card_number", 0), 1)

    def test_public_navigation_never_uses_login_or_account_routes(self):
        page = FakePage([FakeResponse({"list": [_fixed()]})])
        cardova.capture_cardova_public_inventory(page, max_pages_each=1, settle_ms=0)
        self.assertTrue(page.visited)
        self.assertTrue(all("/login" not in url and "/my-" not in url for url in page.visited))
        self.assertTrue(any("/auction/weekly" in url for url in page.visited))
        self.assertTrue(any("/trade/live/fixed-price" in url for url in page.visited))


if __name__ == "__main__":
    unittest.main()
