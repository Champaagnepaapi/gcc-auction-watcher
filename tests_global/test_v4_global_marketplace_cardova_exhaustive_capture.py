from __future__ import annotations

import unittest
from types import SimpleNamespace

import v4_global_marketplace_cardova_exhaustive_capture as target


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.url = "https://api.cardova.co.jp/public/list"
        self.request = SimpleNamespace(method="GET")
        self.status = 200
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class PagedFakePage:
    def __init__(self, payloads_by_page):
        self.payloads_by_page = payloads_by_page
        self.handler = None
        self.request_handler = None
        self.visited = []

    def on(self, event, handler):
        if event == "request":
            self.request_handler = handler
            return
        if event != "response":
            raise AssertionError(event)
        self.handler = handler

    def remove_listener(self, event, handler):
        if event == "request":
            self.request_handler = None
            return
        if event != "response":
            raise AssertionError(event)
        if self.handler is handler:
            self.handler = None

    def goto(self, url, **_kwargs):
        self.visited.append(url)
        page_number = 1
        if "page=" in url:
            page_number = int(url.split("page=", 1)[1].split("&", 1)[0])
        if self.handler:
            for payload in self.payloads_by_page.get(page_number, []):
                # Real browser lifecycle and lane-specific inventory envelope.
                import copy
                payload = copy.deepcopy(payload)
                if "/auction" in url:
                    for rows in target.base._row_lists(payload):
                        for row in rows:
                            row["listing_type"] = 1
                response = FakeResponse(payload)
                self.request_handler(response.request)
                self.handler(response)

    def wait_for_timeout(self, _milliseconds):
        return None

    def evaluate(self, _script):
        return None


def _row(ulid, *, grader="P", category="Pokemon"):
    return {
        "ulid": ulid,
        "listing_type": 4,
        "asking_price": 10000,
        "set_quantity": 1,
        "authentication_company_code": grader,
        "grade": "10",
        "language": "Japanese",
        "player": "Pikachu",
        "variety": "Pokemon 151",
        "card_number": "173/165",
        "category": category,
    }


class CardovaExhaustiveCaptureTests(unittest.TestCase):
    def test_listing_array_key_does_not_hide_request_bound_envelope(self):
        page = PagedFakePage({1: [{"data": {"listings": [_row("one")], "current_page": 1, "last_page": 1}}]})
        result = target.capture_cardova_public_inventory_exhaustive(page, max_pages_each=1)
        self.assertEqual(len(result.page_evidence), 2)
        self.assertTrue(result.complete)

    def test_late_listing_response_is_awaited_before_navigation(self):
        class LatePage(PagedFakePage):
            def goto(self, url, **kwargs):
                self.pending, self.ticks = url, 0
                self.url = url
            def wait_for_timeout(self, ms):
                self.ticks += 1
                if self.ticks == 3:
                    super().goto(self.pending)
        payload = {"data": {"items": [_row("late")], "current_page": 1, "last_page": 1}}
        result = target.capture_cardova_public_inventory_exhaustive(LatePage({1: [payload]}), max_pages_each=1)
        self.assertEqual(result.accepted_rows, 2)
        self.assertTrue(result.complete)

    def test_unrelated_json_is_not_inventory_readiness(self):
        page = PagedFakePage({1: [{"configuration": {"ok": True}}]})
        result = target.capture_cardova_public_inventory_exhaustive(page, max_pages_each=1)
        self.assertEqual(result.status, "PUBLIC_INVENTORY_UNPROVEN")
        self.assertFalse(result.complete)

    def test_out_of_scope_middle_pages_do_not_stop_later_pokemon_discovery(self):
        page = PagedFakePage(
            {
                1: [{"data": {"items": [_row("first")]}}],
                2: [{"data": {"items": [_row("sports", category="Basketball")]}}],
                3: [{"data": {"items": [_row("bgs", grader="BGS")]}}],
                4: [{"data": {"items": [_row("late")]}}],
            }
        )
        result = target.capture_cardova_public_inventory_exhaustive(
            page, max_pages_each=4, settle_ms=0
        )
        ids = {row["ulid"] for row in result.fixed_payload["list"]}
        self.assertIn("first", ids)
        self.assertIn("late", ids)
        # Four pages are visited for each of auction/fixed because no provider
        # pagination proof was supplied.
        self.assertEqual(result.pages_visited, 8)
        self.assertFalse(result.complete)

    def test_explicit_last_page_metadata_is_required_for_complete(self):
        payload = {
            "data": {
                "items": [_row("one")],
                "current_page": 1,
                "last_page": 1,
            }
        }
        page = PagedFakePage({1: [payload]})
        result = target.capture_cardova_public_inventory_exhaustive(
            page, max_pages_each=12, settle_ms=0
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.pages_visited, 2)

    def test_page_cap_or_duplicate_rows_never_claims_complete(self):
        payload = {"data": {"items": [_row("same")]}}
        page = PagedFakePage({1: [payload], 2: [payload], 3: [payload]})
        result = target.capture_cardova_public_inventory_exhaustive(
            page, max_pages_each=3, settle_ms=0
        )
        self.assertFalse(result.complete)
        self.assertEqual(result.pages_visited, 6)

    def test_graphql_has_next_false_without_page_coordinate_stays_incomplete(self):
        payload = {
            "data": {
                "items": [_row("one")],
                "pageInfo": {"hasNextPage": False},
            }
        }
        page = PagedFakePage({1: [payload]})
        result = target.capture_cardova_public_inventory_exhaustive(
            page, max_pages_each=12, settle_ms=0
        )
        self.assertFalse(result.complete)


if __name__ == "__main__":
    unittest.main()
