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
    import requests
except ModuleNotFoundError:
    requests = types.ModuleType("requests")
    requests.Session = object
    requests.Response = object
    requests.RequestException = Exception
    sys.modules["requests"] = requests

from v5.ebay import parse_ebay_item
from v5.ebay_live_diagnostic import (
    CATEGORY_QUERY,
    DEFAULT_CATEGORY_TREE_URL,
    MARKETPLACES,
    OAUTH_SCOPE,
    OAUTH_URL,
    RESULT_LIMIT,
    SEARCH_URL,
    EbayLiveDiagnostic,
    render_live_summary,
)


FIXTURES = Path(__file__).parent / "fixtures"
WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "v5-ebay-diagnostic.yml"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def complete_item():
    return load_fixture("ebay_get_item_complete_en.json")


def partial_fr_item():
    return load_fixture("ebay_get_item_partial_fr.json")


def search_summary(item):
    return {
        key: deepcopy(item[key])
        for key in (
            "itemId",
            "title",
            "price",
            "buyingOptions",
            "conditionId",
            "condition",
            "image",
            "additionalImages",
        )
        if key in item
    }


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
        search_responses=None,
        detail_payloads=None,
        taxonomy_categories=None,
        taxonomy_failures=None,
        detail_failures=None,
    ):
        self.oauth_response = oauth_response or FakeResponse(
            200,
            {"access_token": "live-application-token-never-log", "expires_in": 7200},
        )
        default = complete_item()
        default_search = FakeResponse(
            200, {"total": 1, "itemSummaries": [search_summary(default)]}
        )
        self.search_responses = search_responses or {
            marketplace: default_search for marketplace in MARKETPLACES
        }
        self.detail_payloads = detail_payloads or {default["itemId"]: default}
        self.taxonomy_categories = taxonomy_categories or {
            "EBAY_US": "183454",
            "EBAY_CH": "183454",
        }
        self.taxonomy_failures = taxonomy_failures or {}
        self.detail_failures = detail_failures or {}
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.oauth_response

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        marketplace = kwargs.get("headers", {}).get("X-EBAY-C-MARKETPLACE-ID")
        if url == DEFAULT_CATEGORY_TREE_URL:
            failure = self.taxonomy_failures.get((marketplace, "tree"))
            if isinstance(failure, Exception):
                raise failure
            if failure:
                return failure
            return FakeResponse(200, {"categoryTreeId": f"tree-{marketplace}"})
        if "get_category_suggestions" in url:
            failure = self.taxonomy_failures.get((marketplace, "suggestions"))
            if isinstance(failure, Exception):
                raise failure
            if failure:
                return failure
            category_id = self.taxonomy_categories[marketplace]
            return FakeResponse(
                200,
                {"categorySuggestions": [{"category": {"categoryId": category_id}}]},
            )
        if url == SEARCH_URL:
            return self.search_responses[marketplace]
        if "/buy/browse/v1/item/" in url:
            encoded_id = url.rsplit("/", 1)[-1]
            item_id = encoded_id.replace("%7C", "|").replace("%7c", "|")
            failure = self.detail_failures.get(item_id)
            if isinstance(failure, Exception):
                raise failure
            if failure:
                return failure
            return FakeResponse(200, deepcopy(self.detail_payloads[item_id]))
        raise AssertionError("Unexpected fake URL")


def run_successfully(item=None, session=None):
    chosen = item or complete_item()
    if session is None:
        response = FakeResponse(
            200, {"total": 1, "itemSummaries": [search_summary(chosen)]}
        )
        session = FakeLiveSession(
            search_responses={marketplace: response for marketplace in MARKETPLACES},
            detail_payloads={chosen["itemId"]: chosen},
        )
    diagnostic = EbayLiveDiagnostic(
        "client-id-secret-value", "client-secret-never-log", session=session
    )
    captured = io.StringIO()
    with redirect_stdout(captured):
        summary = diagnostic.run()
    return summary, render_live_summary(summary), session, captured.getvalue()


class EbayEnrichmentParserTests(unittest.TestCase):
    def test_complete_english_localized_aspects_cover_identity_fields(self):
        listing = parse_ebay_item(complete_item())
        self.assertTrue(listing.identity.is_unambiguous_pokemon())
        self.assertEqual(listing.identity.card_name, "Fixturemon")
        self.assertEqual(listing.identity.set, "Fixture Set")
        self.assertEqual(listing.identity.card_number, "7/100")
        self.assertEqual(listing.identity.rarity, "Rare")
        self.assertEqual(listing.identity.finish, "Holo")
        self.assertEqual(listing.identity.edition, "Unlimited")
        self.assertEqual(listing.identity.illustrator, "Fixture Artist")

    def test_product_aspect_groups_enrich_variant(self):
        listing = parse_ebay_item(complete_item())
        self.assertEqual(listing.identity.variant, "Standard")
        self.assertIn("Parallel/Variety", listing.aspects)

    def test_partial_french_aspects_remain_explicitly_insufficient(self):
        listing = parse_ebay_item(partial_fr_item())
        self.assertEqual(listing.identity.game, "Pokémon JCC")
        self.assertEqual(listing.identity.card_name, "Testmon")
        self.assertEqual(listing.identity.card_number, "9/99")
        self.assertEqual(listing.identity.illustrator, "Artiste Test")
        self.assertFalse(listing.identity.is_unambiguous_pokemon())
        self.assertEqual(
            set(listing.identity.missing_required_fields()), {"set", "language"}
        )

    def test_french_labelled_title_is_only_a_fallback_for_missing_fields(self):
        item = partial_fr_item()
        item["title"] += " | langue: Français"
        listing = parse_ebay_item(item)
        self.assertEqual(listing.identity.language, "Français")
        self.assertIsNone(listing.identity.set)


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
        item = complete_item()
        _, rendered, _, _ = run_successfully(item)
        forbidden_values = (
            item["itemId"],
            item["title"],
            item["itemWebUrl"],
            item["price"]["value"],
            item["seller"]["username"],
            item["image"]["imageUrl"],
            item["localizedAspects"][1]["value"],
        )
        for value in forbidden_values:
            self.assertNotIn(str(value), rendered)

    def test_diagnostic_writes_no_api_response_to_disk(self):
        session = FakeLiveSession()
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
    def test_taxonomy_is_resolved_separately_for_us_and_ch(self):
        summary, _, session, _ = run_successfully()
        self.assertTrue(all(value.taxonomy_ok for value in summary.marketplaces))
        tree_calls = [call for call in session.gets if call[0] == DEFAULT_CATEGORY_TREE_URL]
        self.assertEqual(len(tree_calls), 2)
        self.assertEqual(
            {call[1]["params"]["marketplace_id"] for call in tree_calls},
            set(MARKETPLACES),
        )
        suggestion_calls = [
            call for call in session.gets if "get_category_suggestions" in call[0]
        ]
        self.assertEqual(len(suggestion_calls), 2)
        self.assertTrue(all(call[1]["params"]["q"] == CATEGORY_QUERY for call in suggestion_calls))

    def test_different_marketplace_taxonomies_are_not_silently_equalized(self):
        session = FakeLiveSession(
            taxonomy_categories={"EBAY_US": "183454", "EBAY_CH": "999999"}
        )
        summary, rendered, session, _ = run_successfully(session=session)
        self.assertFalse(summary.same_category_id)
        self.assertIn("same category ID: NO", rendered)
        search_calls = [call for call in session.gets if call[0] == SEARCH_URL]
        categories = {
            call[1]["headers"]["X-EBAY-C-MARKETPLACE-ID"]: call[1]["params"]["category_ids"]
            for call in search_calls
        }
        self.assertEqual(categories, {"EBAY_US": "183454", "EBAY_CH": "999999"})

    def test_search_and_get_item_respect_limits_and_request_product(self):
        _, _, session, _ = run_successfully()
        search_calls = [call for call in session.gets if call[0] == SEARCH_URL]
        self.assertEqual(len(search_calls), 2)
        for _, kwargs in search_calls:
            self.assertEqual(kwargs["params"]["filter"], "conditionIds:{4000}")
            self.assertEqual(kwargs["params"]["limit"], str(RESULT_LIMIT))
            self.assertEqual(kwargs["params"]["q"], "Pokémon")
        get_calls = [call for call in session.gets if "/buy/browse/v1/item/" in call[0]]
        self.assertEqual(len(get_calls), 1)
        self.assertEqual(get_calls[0][1]["params"], {"fieldgroups": "PRODUCT"})

    def test_get_item_is_capped_at_twenty_calls_per_marketplace(self):
        detail_payloads = {}
        search_responses = {}
        for marketplace in MARKETPLACES:
            summaries = []
            for index in range(RESULT_LIMIT + 1):
                item = complete_item()
                item["itemId"] = f"v1|{marketplace}-{index}|0"
                detail_payloads[item["itemId"]] = item
                summaries.append(search_summary(item))
            search_responses[marketplace] = FakeResponse(
                200, {"total": len(summaries), "itemSummaries": summaries}
            )
        session = FakeLiveSession(
            search_responses=search_responses,
            detail_payloads=detail_payloads,
        )
        summary = EbayLiveDiagnostic("client", "secret", session=session).run()
        self.assertEqual(
            [value.results_received for value in summary.marketplaces],
            [RESULT_LIMIT, RESULT_LIMIT],
        )
        self.assertEqual(
            [value.get_item_calls for value in summary.marketplaces],
            [RESULT_LIMIT, RESULT_LIMIT],
        )

    def test_cross_marketplace_duplicate_is_deduplicated_before_get_item(self):
        summary, _, session, _ = run_successfully()
        self.assertEqual(summary.duplicate_items, 1)
        self.assertEqual(summary.unique_items, 1)
        get_calls = [call for call in session.gets if "/buy/browse/v1/item/" in call[0]]
        self.assertEqual(len(get_calls), 1)
        self.assertEqual([value.get_item_success for value in summary.marketplaces], [1, 1])

    def test_identity_coverage_improves_after_get_item(self):
        summary, _, _, _ = run_successfully()
        self.assertEqual(summary.identity.before_usable, 0)
        self.assertEqual(summary.identity.after_usable, 2)
        self.assertEqual(summary.identity.localized_aspects_available, 2)
        self.assertEqual(summary.identity.product_data_available, 2)
        self.assertEqual(summary.identity.card_name, 2)
        self.assertEqual(summary.identity.variant, 2)

    def test_condition_4000_reaches_missing_market_values_without_grading(self):
        summary, rendered, _, _ = run_successfully()
        self.assertEqual(summary.cheap_filter.market_values_missing, 2)
        self.assertEqual(summary.cheap_filter.passed, 0)
        self.assertIn("CardGrader calls: 0", rendered)

    def test_condition_2750_is_rejected_from_raw_pipeline(self):
        item = complete_item()
        item["conditionId"] = "2750"
        item["condition"] = "Professionally graded"
        summary, _, _, _ = run_successfully(item)
        self.assertEqual(summary.cheap_filter.reject_identity, 2)
        self.assertEqual(summary.cheap_filter.market_values_missing, 0)


class LiveDiagnosticImageTests(unittest.TestCase):
    def test_search_and_get_item_additional_images_are_counted(self):
        item = complete_item()
        summary_item = search_summary(item)
        summary_item["additionalImages"] = [item["additionalImages"][0]]
        response = FakeResponse(200, {"total": 1, "itemSummaries": [summary_item]})
        session = FakeLiveSession(
            search_responses={marketplace: response for marketplace in MARKETPLACES},
            detail_payloads={item["itemId"]: item},
        )
        summary, _, _, _ = run_successfully(session=session)
        self.assertEqual(summary.images.search_primary, 2)
        self.assertEqual(summary.images.search_additional, 2)
        self.assertEqual(summary.images.get_item_primary, 2)
        self.assertEqual(summary.images.get_item_additional, 2)
        self.assertEqual(summary.images.total_images, 6)

    def test_multiple_unlabelled_images_are_candidate_never_confirmed_back(self):
        summary, _, _, _ = run_successfully()
        self.assertEqual(summary.images.back_candidate, 2)
        self.assertEqual(summary.images.back_confirmed, 0)
        self.assertEqual(summary.images.back_unknown, 0)
        self.assertEqual(summary.cheap_filter.reject_images, 2)

    def test_explicit_semantic_role_can_confirm_back(self):
        item = complete_item()
        item["additionalImages"][0]["role"] = "BACK"
        summary, _, _, _ = run_successfully(item)
        self.assertEqual(summary.images.back_confirmed, 2)
        self.assertEqual(summary.images.back_candidate, 0)


class LiveDiagnosticFailureTests(unittest.TestCase):
    def test_oauth_error_is_aggregated_without_any_get(self):
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
            search_responses={
                "EBAY_US": FakeResponse(500, error_payload),
                "EBAY_CH": FakeResponse(400, error_payload),
            }
        )
        rendered = render_live_summary(
            EbayLiveDiagnostic("client", "secret", session=session).run()
        )
        self.assertIn("search error type: REQUEST", rendered)
        self.assertIn("search error code: 12034", rendered)
        self.assertNotIn("forbidden-listing-title", rendered)
        self.assertNotIn("forbidden-item-id", rendered)

    def test_taxonomy_failure_logs_only_error_type_and_code_and_no_category(self):
        error = FakeResponse(
            400,
            {"errors": [{"errorId": 62000, "category": "REQUEST", "message": "private"}]},
        )
        session = FakeLiveSession(
            taxonomy_failures={("EBAY_CH", "suggestions"): error}
        )
        summary = EbayLiveDiagnostic("client", "secret", session=session).run()
        rendered = render_live_summary(summary)
        self.assertIn("EBAY_CH:\nsearch results: 1\ngetItem success: 1\ntaxonomy: FAIL", rendered)
        self.assertIn("taxonomy error type: REQUEST", rendered)
        self.assertIn("taxonomy error code: 62000", rendered)
        self.assertNotIn("private", rendered)
        ch_search = next(
            call
            for call in session.gets
            if call[0] == SEARCH_URL
            and call[1]["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_CH"
        )
        self.assertNotIn("category_ids", ch_search[1]["params"])

    def test_get_item_404_and_timeout_fall_back_to_search_in_memory(self):
        us_item = complete_item()
        ch_item = partial_fr_item()
        responses = {
            "EBAY_US": FakeResponse(
                200, {"total": 1, "itemSummaries": [search_summary(us_item)]}
            ),
            "EBAY_CH": FakeResponse(
                200, {"total": 1, "itemSummaries": [search_summary(ch_item)]}
            ),
        }
        timeout = requests.RequestException("forbidden-item-id")
        session = FakeLiveSession(
            search_responses=responses,
            detail_payloads={us_item["itemId"]: us_item, ch_item["itemId"]: ch_item},
            detail_failures={
                us_item["itemId"]: FakeResponse(404, {"private": "payload"}),
                ch_item["itemId"]: timeout,
            },
        )
        summary = EbayLiveDiagnostic("client", "secret", session=session).run()
        self.assertEqual([value.get_item_success for value in summary.marketplaces], [0, 0])
        self.assertEqual([value.get_item_failure for value in summary.marketplaces], [1, 1])
        self.assertEqual(summary.unique_items, 2)

    def test_empty_results_are_valid_aggregates(self):
        empty = FakeResponse(200, {"total": 0, "itemSummaries": []})
        session = FakeLiveSession(
            search_responses={"EBAY_US": empty, "EBAY_CH": empty}
        )
        summary = EbayLiveDiagnostic("client", "secret", session=session).run()
        self.assertEqual(summary.unique_items, 0)
        self.assertEqual(summary.identity.after_usable, 0)
        self.assertEqual(summary.cheap_filter.passed, 0)


class LiveDiagnosticWorkflowTests(unittest.TestCase):
    def test_workflow_is_manual_read_only_and_has_no_persistence_actions(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: V5 eBay Enrichment Diagnostic", workflow)
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
