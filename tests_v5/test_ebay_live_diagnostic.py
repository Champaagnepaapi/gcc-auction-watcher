import builtins
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_module = types.ModuleType("requests")
    requests_module.Session = object
    requests_module.Response = object
    requests_module.RequestException = Exception
    sys.modules["requests"] = requests_module

from v5.ebay_live_diagnostic import (
    CATEGORY_ID,
    MARKETPLACES,
    OAUTH_SCOPE,
    OAUTH_URL,
    RESULT_LIMIT,
    SEARCH_URL,
    EbayLiveDiagnostic,
    render_live_summary,
)


FIXTURES = Path(__file__).parent / "fixtures"
WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "v5-ebay-diagnostic.yml"
)


def fixture_item():
    return json.loads(
        (FIXTURES / "ebay_raw_item.json").read_text(encoding="utf-8")
    )


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeLiveSession:
    def __init__(
        self,
        oauth_response=None,
        marketplace_responses=None,
        detail_payload=None,
    ):
        self.oauth_response = oauth_response or FakeResponse(
            200,
            {
                "access_token": "live-application-token-never-log",
                "expires_in": 7200,
            },
        )
        default_search = FakeResponse(
            200, {"total": 1, "itemSummaries": [fixture_item()]}
        )
        self.marketplace_responses = marketplace_responses or {
            marketplace: default_search for marketplace in MARKETPLACES
        }
        self.detail_payload = detail_payload or fixture_item()
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.oauth_response

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if url == SEARCH_URL:
            marketplace = kwargs["headers"]["X-EBAY-C-MARKETPLACE-ID"]
            return self.marketplace_responses[marketplace]
        return FakeResponse(200, deepcopy(self.detail_payload))


def run_successfully(item=None):
    session = FakeLiveSession(detail_payload=item or fixture_item())
    diagnostic = EbayLiveDiagnostic(
        "client-id-secret-value",
        "client-secret-never-log",
        session=session,
    )
    captured = io.StringIO()
    with redirect_stdout(captured):
        summary = diagnostic.run()
    return summary, render_live_summary(summary), session, captured.getvalue()


class LiveDiagnosticPrivacyTests(unittest.TestCase):
    def test_token_and_secrets_are_never_logged(self):
        summary, rendered, _, runtime_output = run_successfully()
        self.assertTrue(summary.oauth.token_obtained)
        self.assertEqual(runtime_output, "")
        for forbidden in (
            "live-application-token-never-log",
            "client-id-secret-value",
            "client-secret-never-log",
        ):
            self.assertNotIn(forbidden, rendered)
            self.assertNotIn(forbidden, runtime_output)

    def test_no_listing_level_data_appears_in_summary(self):
        item = fixture_item()
        _, rendered, _, _ = run_successfully(item)
        forbidden_values = (
            item["itemId"],
            item["title"],
            item["itemWebUrl"],
            item["price"]["value"],
            item["seller"]["username"],
            item["image"]["imageUrl"],
        )
        for value in forbidden_values:
            self.assertNotIn(str(value), rendered)

    def test_diagnostic_writes_no_api_response_to_disk(self):
        item = fixture_item()
        session = FakeLiveSession(detail_payload=item)
        diagnostic = EbayLiveDiagnostic("client", "secret", session=session)
        with patch.object(builtins, "open", wraps=builtins.open) as mocked_open:
            diagnostic.run()
        mocked_open.assert_not_called()

    def test_summary_explicitly_confirms_zero_side_effects(self):
        _, rendered, _, _ = run_successfully()
        self.assertIn("CardGrader calls: 0", rendered)
        self.assertIn("Purchases: 0", rendered)
        self.assertIn("Bids: 0", rendered)
        self.assertIn("Checkout: 0", rendered)
        self.assertIn("Persisted eBay records: 0", rendered)


class LiveDiagnosticPipelineTests(unittest.TestCase):
    def test_condition_4000_is_accepted_as_raw_then_stops_at_market_values(self):
        summary, _, _, _ = run_successfully()
        for aggregate in summary.marketplaces:
            self.assertEqual(aggregate.raw_condition_4000, 1)
            self.assertEqual(aggregate.other_conditions, 0)
            self.assertEqual(aggregate.usable_identity, 1)
            self.assertEqual(aggregate.market_values_missing, 1)
            self.assertEqual(aggregate.cheap_filter_pass, 0)
            self.assertEqual(aggregate.cheap_filter_reject, 1)

    def test_condition_2750_is_rejected_from_raw_pipeline(self):
        item = fixture_item()
        item["conditionId"] = "2750"
        item["condition"] = "Professionally graded"
        summary, _, _, _ = run_successfully(item)
        for aggregate in summary.marketplaces:
            self.assertEqual(aggregate.raw_condition_4000, 0)
            self.assertEqual(aggregate.other_conditions, 1)
            self.assertEqual(aggregate.market_values_missing, 0)
            self.assertEqual(aggregate.cheap_filter_reject, 1)

    def test_us_and_ch_are_separate_requests_with_same_explicit_taxonomy(self):
        _, _, session, _ = run_successfully()
        search_calls = [call for call in session.gets if call[0] == SEARCH_URL]
        self.assertEqual(len(search_calls), 2)
        self.assertEqual(
            {
                call[1]["headers"]["X-EBAY-C-MARKETPLACE-ID"]
                for call in search_calls
            },
            {"EBAY_US", "EBAY_CH"},
        )
        for _, kwargs in search_calls:
            self.assertEqual(kwargs["params"]["category_ids"], CATEGORY_ID)
            self.assertEqual(kwargs["params"]["filter"], "conditionIds:{4000}")
            self.assertEqual(kwargs["params"]["limit"], str(RESULT_LIMIT))
            self.assertEqual(kwargs["params"]["q"], "Pokémon")

    def test_oauth_uses_production_client_credentials_and_minimal_scope(self):
        _, _, session, _ = run_successfully()
        self.assertEqual(len(session.posts), 1)
        url, kwargs = session.posts[0]
        self.assertEqual(url, OAUTH_URL)
        self.assertEqual(kwargs["auth"], ("client-id-secret-value", "client-secret-never-log"))
        self.assertEqual(kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(kwargs["data"]["scope"], OAUTH_SCOPE)

    def test_back_image_is_not_inferred_from_unlabelled_additional_images(self):
        summary, _, _, _ = run_successfully()
        for aggregate in summary.marketplaces:
            self.assertEqual(aggregate.front_image_available, 1)
            self.assertEqual(aggregate.back_image_available, 0)
            self.assertEqual(aggregate.insufficient_images, 1)


class LiveDiagnosticFailureTests(unittest.TestCase):
    def test_oauth_error_is_aggregated_without_browse_call(self):
        session = FakeLiveSession(
            oauth_response=FakeResponse(
                401,
                {
                    "error": "invalid_client",
                    "error_description": "client-secret-never-log",
                },
            )
        )
        summary = EbayLiveDiagnostic(
            "client-id-secret-value", "client-secret-never-log", session=session
        ).run()
        rendered = render_live_summary(summary)
        self.assertEqual(summary.oauth.http_status, "401")
        self.assertFalse(summary.oauth.token_obtained)
        self.assertEqual(session.gets, [])
        self.assertNotIn("client-secret-never-log", rendered)

    def test_browse_api_error_logs_only_technical_type_and_code(self):
        error_payload = {
            "errors": [
                {
                    "errorId": 12034,
                    "domain": "API_BROWSE",
                    "category": "REQUEST",
                    "message": "forbidden-listing-title",
                    "longMessage": "forbidden-item-id",
                }
            ]
        }
        session = FakeLiveSession(
            marketplace_responses={
                "EBAY_US": FakeResponse(500, error_payload),
                "EBAY_CH": FakeResponse(400, error_payload),
            }
        )
        summary = EbayLiveDiagnostic("client", "secret", session=session).run()
        rendered = render_live_summary(summary)
        self.assertIn("error type: REQUEST", rendered)
        self.assertIn("error code: 12034", rendered)
        self.assertNotIn("forbidden-listing-title", rendered)
        self.assertNotIn("forbidden-item-id", rendered)
        self.assertTrue(all(value.results_received == 0 for value in summary.marketplaces))

    def test_non_technical_error_identifier_is_redacted(self):
        error_payload = {
            "errors": [
                {
                    "errorId": "12034",
                    "category": "forbidden listing title",
                }
            ]
        }
        response = FakeResponse(400, error_payload)
        session = FakeLiveSession(
            marketplace_responses={"EBAY_US": response, "EBAY_CH": response}
        )
        rendered = render_live_summary(
            EbayLiveDiagnostic("client", "secret", session=session).run()
        )
        self.assertIn("error type: REDACTED_IDENTIFIER", rendered)
        self.assertNotIn("forbidden listing title", rendered)

    def test_empty_results_are_valid_aggregates(self):
        empty = FakeResponse(200, {"total": 0, "itemSummaries": []})
        session = FakeLiveSession(
            marketplace_responses={"EBAY_US": empty, "EBAY_CH": empty}
        )
        summary = EbayLiveDiagnostic("client", "secret", session=session).run()
        for aggregate in summary.marketplaces:
            self.assertEqual(aggregate.http_status, "200")
            self.assertEqual(aggregate.total_announced, 0)
            self.assertEqual(aggregate.results_received, 0)
            self.assertEqual(aggregate.cheap_filter_reject, 0)


class LiveDiagnosticWorkflowTests(unittest.TestCase):
    def test_workflow_is_manual_read_only_and_has_no_persistence_actions(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("actions/cache", workflow)
        self.assertNotIn("upload-artifact", workflow)

    def test_workflow_uses_only_expected_secrets_and_safety_locks(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("secrets.EBAY_CLIENT_ID", workflow)
        self.assertIn("secrets.EBAY_CLIENT_SECRET", workflow)
        self.assertIn('RAW_MAX_PAID_GRADINGS_PER_RUN: "0"', workflow)
        self.assertIn('CARDGRADER_V5_ALLOW_PAID_CALLS: "false"', workflow)
        self.assertNotIn("CARDGRADER_API_KEY", workflow)


if __name__ == "__main__":
    unittest.main()
