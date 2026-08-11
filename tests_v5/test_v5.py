import json
import os
import sys
import types
import unittest
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


# Les tests restent executables hors ligne, meme avant installation des
# dependances du requirements.txt. Les sessions HTTP sont toutes injectees.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_module = types.ModuleType("requests")
    requests_module.Session = object
    requests_module.Response = object
    requests_module.RequestException = Exception
    sys.modules["requests"] = requests_module

from v5.ebay import (
    EbayBrowseClient,
    EbayBrowseConfig,
    card_identity_from_aspects,
    parse_ebay_item,
)
from v5.grading import (
    CardGraderAIConfig,
    CardGraderAIProvider,
    ConservativeProbabilityPolicy,
    GradeProviderUnavailable,
    PaidCallNotAuthorized,
    parse_cardgrader_assessment,
)
from v5.models import (
    GRADING_AFTER_VISUAL_ASSESSMENT,
    PSA10_DEPENDENT,
    RAW_RESALE,
    CardIdentity,
    CostInputs,
    GradeAssessment,
    GradeImagePair,
    GradeProbabilities,
    ImageQuality,
    MarketValue,
    MarketValues,
    StructuredGradingStatus,
)
from v5.scanner import (
    BACK_IMAGE_MISSING,
    GRADING_UNAVAILABLE,
    IDENTITY_AMBIGUOUS,
    INSUFFICIENT_PHOTOS,
    INSUFFICIENT_MAX_PLAUSIBLE_UPSIDE,
    INSUFFICIENT_PSA_DATA,
    NON_PROFITABLE_EV,
    RAW_BEATS_GRADING,
    RAW_MARKET_INSUFFICIENT,
    RAW_PATH_NON_PROFITABLE,
    RAW_PATH_PROFITABLE,
    RawCardScanner,
    SafeguardConfig,
    ScanRequest,
    VISUAL_GRADING_QUOTA_REACHED,
    format_diagnostic,
)
from v5.valuation import StaticMarketDataProvider


FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def market_values(case_name):
    raw = load_json("market_cases.json")[case_name]

    def value(name):
        item = raw.get(name)
        if item is None:
            return None
        return MarketValue(
            amount=Decimal(item["amount"]),
            currency="EUR",
            sample_size=item["sample_size"],
            confidence="high",
            source="offline fixture",
        )

    return MarketValues(
        raw=value("raw"),
        psa8=value("psa8"),
        psa9=value("psa9"),
        psa10=value("psa10"),
        psa7_or_lower=value("psa7_or_lower"),
    )


class FakeGradeProvider:
    def __init__(self, assessment=None):
        self.assessment = assessment or GradeAssessment(
            predicted_grade=10.0,
            centering=9.5,
            corners=9.5,
            edges=9.0,
            surface=9.0,
            confidence=0.85,
            issues=("fixture",),
            image_quality=ImageQuality.HIGH,
            provider="offline fixture",
        )
        self.calls = 0

    def assess(self, image_pair, identity):
        self.calls += 1
        return self.assessment


class UnavailableGradeProvider:
    def assess(self, image_pair, identity):
        raise GradeProviderUnavailable("service indisponible dans la fixture")


def provider_for(listing, values, grade_provider=None, safeguards=None):
    key = (
        listing.identity.card_name,
        listing.identity.set,
        listing.identity.card_number,
    )
    return RawCardScanner(
        grade_provider or FakeGradeProvider(),
        StaticMarketDataProvider({key: values}),
        safeguards=safeguards or SafeguardConfig(maximum_paid_gradings_per_run=1),
    )


def standard_costs(listing, **changes):
    values = {
        "purchase_price": listing.price,
        "shipping_to_buyer": listing.shipping_price,
        "buyer_fees": Decimal("2"),
        "grading_fee": Decimal("20"),
        "shipping_for_grading": Decimal("10"),
        "marketplace_selling_fee_rate": Decimal("0.13"),
        "other_costs": Decimal("3"),
        "currency": listing.currency,
    }
    values.update(changes)
    return CostInputs(**values)


def image_pair(listing):
    return GradeImagePair(
        front_url=listing.primary_image_url,
        back_url=listing.additional_image_urls[0],
    )


class EbayOfficialConnectorTests(unittest.TestCase):
    def setUp(self):
        self.payload = load_json("ebay_raw_item.json")

    def test_structured_payload_extracts_required_fields(self):
        listing = parse_ebay_item(self.payload)
        self.assertEqual(listing.grading_status, StructuredGradingStatus.RAW)
        self.assertEqual(listing.item_id, "v1|123456789012|0")
        self.assertEqual(listing.price, Decimal("50.00"))
        self.assertEqual(listing.shipping_price, Decimal("5.00"))
        self.assertEqual(listing.condition_id, "4000")
        self.assertTrue(listing.is_buy_it_now)
        self.assertEqual(listing.seller.username, "fixture-seller")
        self.assertEqual(len(listing.image_urls), 3)
        self.assertEqual(listing.category_id, "183454")
        self.assertEqual(listing.identity.card_name, "Charizard")
        self.assertEqual(listing.identity.set, "Base Set")
        self.assertEqual(listing.identity.card_number, "4/102")
        self.assertTrue(listing.identity.is_unambiguous_pokemon())

    def test_raw_title_alone_never_proves_ungraded_status(self):
        payload = deepcopy(self.payload)
        payload.pop("conditionId")
        payload["localizedAspects"] = [
            aspect
            for aspect in payload["localizedAspects"]
            if aspect["name"] != "Graded"
        ]
        listing = parse_ebay_item(payload)
        self.assertIn("RAW", listing.title)
        self.assertEqual(listing.grading_status, StructuredGradingStatus.UNKNOWN)

    def test_conflicting_identity_is_explicitly_ambiguous(self):
        identity = card_identity_from_aspects(
            {
                "Game": ("Pokemon TCG",),
                "Card Name": ("Charizard", "Dark Charizard"),
                "Set": ("Base Set",),
                "Card Number": ("4/102",),
                "Language": ("English",),
            }
        )
        self.assertFalse(identity.is_unambiguous_pokemon())
        self.assertIn("card_name", identity.ambiguities[0])

    def test_browse_search_uses_official_raw_aspect_filter(self):
        session = FakeEbaySession(self.payload)
        config = EbayBrowseConfig(
            client_id="client",
            client_secret="secret",
            marketplace_id="EBAY_FR",
            category_id="183454",
            raw_aspect_name="Graded",
            raw_aspect_value="No",
        )
        listings = EbayBrowseClient(config, session=session).search_raw_pokemon_cards(
            limit=10
        )
        self.assertEqual(len(listings), 1)
        search_call = next(call for call in session.gets if "item_summary/search" in call[0])
        self.assertEqual(
            search_call[1]["params"]["aspect_filter"],
            "categoryId:183454,Graded:{No}",
        )
        self.assertTrue(search_call[0].startswith("https://api.ebay.com/"))


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeEbaySession:
    def __init__(self, detail):
        self.detail = detail
        self.gets = []
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"access_token": "offline-token"})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if "item_summary/search" in url:
            return FakeResponse({"itemSummaries": [{"itemId": self.detail["itemId"]}]})
        return FakeResponse(self.detail)


class GradingTests(unittest.TestCase):
    def test_cardgrader_fixture_preserves_prediction_subgrades_and_quality(self):
        assessment = parse_cardgrader_assessment(
            load_json("cardgrader_completed.json")
        )
        self.assertEqual(assessment.predicted_grade, 10.0)
        self.assertEqual(assessment.centering, 10.0)
        self.assertEqual(assessment.surface, 9.0)
        self.assertEqual(assessment.confidence, 0.86)
        self.assertEqual(assessment.image_quality, ImageQuality.HIGH)
        self.assertEqual(len(assessment.issues), 2)

    def test_paid_cardgrader_call_is_blocked_before_network(self):
        session = FakeEbaySession({})
        provider = CardGraderAIProvider(
            CardGraderAIConfig(api_key="fixture-key", allow_paid_calls=False),
            session=session,
        )
        with self.assertRaises(PaidCallNotAuthorized):
            provider.assess(
                GradeImagePair("https://example/front.jpg", "https://example/back.jpg"),
                CardIdentity(
                    "Pokemon TCG", "Charizard", "Base Set", "4/102", 1999, "English"
                ),
            )
        self.assertEqual(session.posts, [])
        self.assertEqual(session.gets, [])

    def test_probabilities_sum_to_one_and_invalid_distribution_is_rejected(self):
        probabilities = ConservativeProbabilityPolicy().probabilities_for(
            FakeGradeProvider().assessment
        )
        self.assertAlmostEqual(sum(probabilities.as_tuple()), 1.0)
        with self.assertRaises(ValueError):
            GradeProbabilities(0.5, 0.4, 0.2, 0.0)


class ScannerSafeguardTests(unittest.TestCase):
    def setUp(self):
        self.listing = parse_ebay_item(load_json("ebay_raw_item.json"))

    def evaluate(
        self,
        values,
        listing=None,
        costs=None,
        grade_provider=None,
        pair=None,
        safeguards=None,
    ):
        listing = listing or self.listing
        scanner = provider_for(
            listing,
            values,
            grade_provider=grade_provider,
            safeguards=safeguards,
        )
        return scanner.evaluate(
            ScanRequest(
                listing=listing,
                image_pair=pair or image_pair(listing),
                costs=costs or standard_costs(listing),
            )
        )

    def test_raw_profitable_even_in_psa9_is_retained(self):
        diagnostic = self.evaluate(market_values("profitable_in_psa9"))
        self.assertTrue(diagnostic.retained)
        self.assertGreater(diagnostic.valuation.stress_psa9_profit, 0)
        self.assertGreater(diagnostic.valuation.expected_profit, 0)
        self.assertNotIn(PSA10_DEPENDENT, diagnostic.risk_flags)
        output = format_diagnostic(diagnostic)
        self.assertIn("RAW CANDIDATE", output)
        self.assertIn("Stress PSA9:", output)
        self.assertIn("Cout total si grading:", output)
        self.assertIn("Resultat PSA10:", output)
        self.assertIn("Resultat PSA9:", output)
        self.assertIn("Resultat PSA8:", output)
        self.assertIn("EV probabiliste nette:", output)
        self.assertIn("Break-even P(PSA10):", output)
        self.assertIn("Pourquoi retenue:", output)

    def test_raw_profitable_only_in_psa10_is_flagged_and_rejected(self):
        values = market_values("psa10_only")
        costs = standard_costs(self.listing, purchase_price=Decimal("80"))
        diagnostic = self.evaluate(values, costs=costs)
        self.assertGreater(diagnostic.valuation.expected_profit, 0)
        self.assertLess(diagnostic.valuation.stress_psa9_profit, 0)
        self.assertIn(PSA10_DEPENDENT, diagnostic.risk_flags)
        self.assertFalse(diagnostic.retained)
        output = format_diagnostic(diagnostic)
        self.assertIn("Classification: speculatif / PSA10_DEPENDENT", output)

    def test_single_photo_is_rejected_before_grading(self):
        listing = replace(self.listing, additional_image_urls=())
        grade_provider = FakeGradeProvider()
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"),
            listing=listing,
            grade_provider=grade_provider,
            pair=GradeImagePair(listing.primary_image_url, None),
        )
        self.assertIn(INSUFFICIENT_PHOTOS, diagnostic.grading_reasons)
        self.assertEqual(grade_provider.calls, 0)

    def test_missing_explicit_back_is_rejected(self):
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"),
            pair=GradeImagePair(self.listing.primary_image_url, None),
        )
        self.assertIn(BACK_IMAGE_MISSING, diagnostic.reasons)

    def test_ambiguous_identity_is_rejected_before_grading(self):
        identity = replace(
            self.listing.identity,
            card_number=None,
            ambiguities=("card_number: two possible values",),
        )
        listing = replace(self.listing, identity=identity)
        grade_provider = FakeGradeProvider()
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"),
            listing=listing,
            grade_provider=grade_provider,
        )
        self.assertIn(IDENTITY_AMBIGUOUS, diagnostic.reasons)
        self.assertEqual(grade_provider.calls, 0)

    def test_grading_api_unavailable_has_safe_rejection(self):
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"),
            grade_provider=UnavailableGradeProvider(),
        )
        self.assertIn(GRADING_UNAVAILABLE, diagnostic.reasons)
        self.assertFalse(diagnostic.retained)
        self.assertIsNone(diagnostic.valuation)

    def test_fees_can_make_candidate_non_profitable(self):
        grade_provider = FakeGradeProvider()
        costs = standard_costs(
            self.listing,
            marketplace_selling_fee_rate=Decimal("0.40"),
            other_costs=Decimal("70"),
        )
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"),
            costs=costs,
            grade_provider=grade_provider,
        )
        self.assertIsNone(diagnostic.valuation)
        self.assertLess(diagnostic.psa10_profit, 0)
        self.assertIn(
            INSUFFICIENT_MAX_PLAUSIBLE_UPSIDE, diagnostic.grading_reasons
        )
        self.assertFalse(diagnostic.retained)
        self.assertEqual(grade_provider.calls, 0)

    def test_missing_psa9_value_never_creates_artificial_ev(self):
        values = replace(market_values("profitable_in_psa9"), psa9=None)
        diagnostic = self.evaluate(values)
        self.assertIn(INSUFFICIENT_PSA_DATA, diagnostic.grading_reasons)
        self.assertIn(RAW_PATH_NON_PROFITABLE, diagnostic.reasons)
        self.assertIsNone(diagnostic.valuation)

    def test_low_image_quality_is_rejected(self):
        grade_provider = FakeGradeProvider(
            replace(FakeGradeProvider().assessment, image_quality=ImageQuality.LOW)
        )
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"), grade_provider=grade_provider
        )
        self.assertFalse(diagnostic.retained)
        self.assertIsNone(diagnostic.valuation)

    def test_unknown_significant_cost_is_rejected_before_paid_provider(self):
        grade_provider = FakeGradeProvider()
        costs = standard_costs(self.listing, grading_fee=None)
        diagnostic = self.evaluate(
            market_values("profitable_in_psa9"),
            costs=costs,
            grade_provider=grade_provider,
        )
        self.assertFalse(diagnostic.retained)
        self.assertEqual(grade_provider.calls, 0)


class CheapFilterPipelineTests(unittest.TestCase):
    def setUp(self):
        self.base_listing = parse_ebay_item(load_json("ebay_raw_item.json"))
        self.values = market_values("profitable_in_psa9")

    def scanner(self, listing, grade_provider=None, safeguards=None, values=None):
        return provider_for(
            listing,
            values or self.values,
            grade_provider=grade_provider,
            safeguards=safeguards,
        )

    def request(self, price):
        listing = replace(self.base_listing, price=Decimal(price))
        return ScanRequest(
            listing=listing,
            image_pair=image_pair(listing),
            costs=standard_costs(listing),
        )

    def test_raw_two_euros_can_be_shortlisted_without_grading_call(self):
        request = self.request("2")
        grade_provider = FakeGradeProvider()
        result = self.scanner(request.listing, grade_provider).cheap_filter(request)
        self.assertTrue(result.eligible_for_visual_grading)
        self.assertGreater(result.psa9_profit, 0)
        self.assertEqual(grade_provider.calls, 0)

    def test_raw_fifty_cents_can_be_shortlisted_when_upside_is_sufficient(self):
        request = self.request("0.50")
        grade_provider = FakeGradeProvider()
        result = self.scanner(request.listing, grade_provider).cheap_filter(request)
        self.assertTrue(result.eligible_for_visual_grading)
        self.assertGreater(result.psa10_profit, 0)
        self.assertEqual(grade_provider.calls, 0)

    def test_two_euro_raw_with_psa10_at_eight_is_rejected_before_grading(self):
        request = self.request("2")
        low_values = replace(
            self.values,
            raw=replace(self.values.raw, amount=Decimal("3")),
            psa8=replace(self.values.psa8, amount=Decimal("6")),
            psa9=replace(self.values.psa9, amount=Decimal("7")),
            psa10=replace(self.values.psa10, amount=Decimal("8")),
            psa7_or_lower=replace(
                self.values.psa7_or_lower, amount=Decimal("4")
            ),
        )
        grade_provider = FakeGradeProvider()
        result = self.scanner(
            request.listing, grade_provider, values=low_values
        ).cheap_filter(request)
        self.assertFalse(result.eligible_for_visual_grading)
        self.assertIn(
            INSUFFICIENT_MAX_PLAUSIBLE_UPSIDE, result.grading_reasons
        )
        self.assertIn(RAW_PATH_NON_PROFITABLE, result.reasons)
        self.assertLess(result.psa10_profit, 0)
        self.assertEqual(grade_provider.calls, 0)

    def test_v4_ten_euro_minimum_never_leaks_into_v5(self):
        with patch.dict(os.environ, {"MIN_PRICE_EUR": "10"}, clear=True):
            safeguards = SafeguardConfig.from_env()
        self.assertEqual(safeguards.raw_min_price_eur, Decimal("0"))
        request = self.request("2")
        result = self.scanner(
            request.listing, safeguards=safeguards
        ).cheap_filter(request)
        self.assertTrue(result.eligible_for_visual_grading)

    def test_default_run_quota_disables_paid_visual_grading(self):
        with patch.dict(os.environ, {}, clear=True):
            safeguards = SafeguardConfig.from_env()
        self.assertEqual(safeguards.maximum_paid_gradings_per_run, 0)
        request = self.request("2")
        grade_provider = FakeGradeProvider()
        scanner = RawCardScanner(
            grade_provider,
            StaticMarketDataProvider(
                {
                    (
                        request.listing.identity.card_name,
                        request.listing.identity.set,
                        request.listing.identity.card_number,
                    ): self.values
                }
            ),
            safeguards=safeguards,
        )
        diagnostic = scanner.evaluate(request)
        self.assertTrue(diagnostic.retained)
        self.assertEqual(diagnostic.recommended_path, RAW_RESALE)
        self.assertNotIn(VISUAL_GRADING_QUOTA_REACHED, diagnostic.reasons)
        self.assertEqual(grade_provider.calls, 0)

    def test_scan_run_never_exceeds_paid_grading_quota(self):
        first = self.request("0.50")
        second = self.request("2")
        second = replace(
            second,
            listing=replace(second.listing, item_id="v1|second|0"),
        )
        grade_provider = FakeGradeProvider()
        safeguards = SafeguardConfig(maximum_paid_gradings_per_run=1)
        scanner = self.scanner(
            first.listing, grade_provider=grade_provider, safeguards=safeguards
        )
        diagnostics = scanner.scan_and_rank((first, second))
        self.assertEqual(grade_provider.calls, 1)
        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(all(item.retained for item in diagnostics))
        self.assertTrue(
            any(item.recommended_path == RAW_RESALE for item in diagnostics)
        )
        self.assertTrue(
            all(VISUAL_GRADING_QUOTA_REACHED not in item.reasons for item in diagnostics)
        )


class RawResaleMvpTests(unittest.TestCase):
    def setUp(self):
        self.listing = replace(
            parse_ebay_item(load_json("ebay_raw_item.json")),
            price=Decimal("10"),
        )

    def values(self, raw="100", *, graded=False, confidence="high", samples=8):
        value = lambda amount: MarketValue(
            Decimal(amount), "EUR", samples, confidence, "offline fixture"
        )
        return MarketValues(
            raw=value(raw) if raw is not None else None,
            psa8=value("100") if graded else None,
            psa9=value("150") if graded else None,
            psa10=value("250") if graded else None,
            psa7_or_lower=value("60") if graded else None,
        )

    def request(self, **cost_changes):
        return ScanRequest(
            self.listing,
            image_pair(self.listing),
            standard_costs(self.listing, **cost_changes),
        )

    def scanner(self, values, provider=None, **safeguards):
        return provider_for(
            self.listing,
            values,
            grade_provider=provider,
            safeguards=SafeguardConfig(**safeguards),
        )

    def test_a_raw_only_profitable_is_retained_without_psa(self):
        diagnostic = self.scanner(
            self.values(), maximum_paid_gradings_per_run=0
        ).evaluate(self.request(grading_fee=None, shipping_for_grading=None))
        self.assertTrue(diagnostic.retained)
        self.assertEqual(diagnostic.recommended_path, RAW_RESALE)
        self.assertIn(RAW_PATH_PROFITABLE, diagnostic.reasons)
        self.assertNotIn(INSUFFICIENT_PSA_DATA, diagnostic.reasons)
        self.assertIsNone(diagnostic.valuation)
        self.assertIsNotNone(diagnostic.raw_valuation)

    def test_b_zero_paid_quota_retains_raw_and_never_calls_provider(self):
        grade_provider = FakeGradeProvider()
        diagnostic = self.scanner(
            self.values(graded=True),
            provider=grade_provider,
            maximum_paid_gradings_per_run=0,
        ).evaluate(self.request())
        self.assertTrue(diagnostic.retained)
        self.assertEqual(diagnostic.recommended_path, RAW_RESALE)
        self.assertNotIn(VISUAL_GRADING_QUOTA_REACHED, diagnostic.reasons)
        self.assertEqual(grade_provider.calls, 0)

    def test_c_raw_cost_basis_excludes_grading_costs_exactly(self):
        diagnostic = self.scanner(
            self.values(), maximum_paid_gradings_per_run=0
        ).evaluate(
            self.request(
                grading_fee=Decimal("999"),
                shipping_for_grading=Decimal("888"),
                marketplace_selling_fee_rate=Decimal("0.10"),
            )
        )
        raw = diagnostic.raw_valuation
        self.assertEqual(raw.fixed_non_grading_costs, Decimal("20"))
        self.assertEqual(raw.selling_fees, Decimal("10.00"))
        self.assertEqual(raw.total_cost_basis, Decimal("30.00"))
        self.assertEqual(raw.net_profit, Decimal("70.00"))

    def test_d_non_profitable_raw_without_graded_data_is_rejected(self):
        diagnostic = self.scanner(
            self.values(raw="10"), maximum_paid_gradings_per_run=0
        ).evaluate(self.request(grading_fee=None, shipping_for_grading=None))
        self.assertFalse(diagnostic.retained)
        self.assertEqual(diagnostic.recommended_path, "NONE")
        self.assertIn(RAW_PATH_NON_PROFITABLE, diagnostic.reasons)
        self.assertNotIn(INSUFFICIENT_PSA_DATA, diagnostic.reasons)

    def test_e_raw_ev_higher_than_supported_grading_recommends_raw(self):
        values = self.values(raw="200", graded=True)
        grade_provider = FakeGradeProvider()
        diagnostic = self.scanner(
            values,
            provider=grade_provider,
            maximum_paid_gradings_per_run=1,
            maximum_psa10_ev_share=Decimal("1"),
        ).evaluate(self.request())
        self.assertTrue(diagnostic.graded_comparison_available)
        self.assertEqual(diagnostic.recommended_path, RAW_RESALE)
        self.assertIn(RAW_BEATS_GRADING, diagnostic.reasons)
        self.assertGreater(
            diagnostic.raw_valuation.net_profit,
            diagnostic.valuation.expected_profit,
        )

    def test_f_higher_supported_grading_ev_can_be_recommended(self):
        values = self.values(raw="40", graded=True)
        grade_provider = FakeGradeProvider()
        diagnostic = self.scanner(
            values,
            provider=grade_provider,
            maximum_paid_gradings_per_run=1,
            maximum_psa10_ev_share=Decimal("1"),
        ).evaluate(self.request())
        self.assertTrue(diagnostic.raw_valuation.net_profit > 0)
        self.assertEqual(
            diagnostic.recommended_path, GRADING_AFTER_VISUAL_ASSESSMENT
        )
        self.assertGreater(
            diagnostic.valuation.expected_profit,
            diagnostic.raw_valuation.net_profit,
        )

    def test_g_missing_raw_with_strong_psa_never_fabricates_raw(self):
        diagnostic = self.scanner(
            self.values(raw=None, graded=True),
            maximum_paid_gradings_per_run=1,
            maximum_psa10_ev_share=Decimal("1"),
        ).evaluate(self.request())
        self.assertIsNone(diagnostic.raw_valuation)
        self.assertTrue(diagnostic.graded_comparison_available)
        self.assertEqual(
            diagnostic.recommended_path, GRADING_AFTER_VISUAL_ASSESSMENT
        )

    def test_h_ambiguous_identity_blocks_raw_and_grading(self):
        listing = replace(
            self.listing,
            identity=replace(self.listing.identity, ambiguities=("set ambiguous",)),
        )
        provider = FakeGradeProvider()
        scanner = provider_for(listing, self.values(graded=True), provider)
        diagnostic = scanner.evaluate(
            replace(self.request(), listing=listing)
        )
        self.assertFalse(diagnostic.retained)
        self.assertIsNone(diagnostic.raw_valuation)
        self.assertIn(IDENTITY_AMBIGUOUS, diagnostic.reasons)
        self.assertEqual(provider.calls, 0)

    def test_i_currency_mismatch_and_unknown_material_costs_block_raw(self):
        foreign = replace(
            self.values(),
            raw=replace(self.values().raw, currency="USD"),
        )
        cases = (
            (foreign, self.request(grading_fee=None, shipping_for_grading=None)),
            (
                self.values(),
                self.request(
                    buyer_fees=None,
                    grading_fee=None,
                    shipping_for_grading=None,
                ),
            ),
        )
        for values, request in cases:
            with self.subTest(values=values):
                diagnostic = self.scanner(
                    values, maximum_paid_gradings_per_run=0
                ).evaluate(request)
                self.assertFalse(diagnostic.retained)
                self.assertIsNone(diagnostic.raw_valuation)

    def test_weak_raw_evidence_remains_non_actionable(self):
        values = self.values(confidence="low", samples=1)
        diagnostic = self.scanner(
            values, maximum_paid_gradings_per_run=0
        ).evaluate(self.request(grading_fee=None, shipping_for_grading=None))
        self.assertFalse(diagnostic.retained)
        self.assertIsNone(diagnostic.raw_valuation)
        self.assertIn(RAW_MARKET_INSUFFICIENT, diagnostic.reasons)

    def test_raw_only_results_rank_by_supported_raw_profit(self):
        expensive = replace(self.listing, item_id="expensive", price=Decimal("20"))
        cheap = replace(self.listing, item_id="cheap", price=Decimal("5"))
        values = self.values(raw="100")
        scanner = provider_for(
            self.listing,
            values,
            safeguards=SafeguardConfig(maximum_paid_gradings_per_run=0),
        )
        requests = tuple(
            ScanRequest(
                listing,
                image_pair(listing),
                standard_costs(
                    listing, grading_fee=None, shipping_for_grading=None
                ),
            )
            for listing in (expensive, cheap)
        )
        diagnostics = scanner.scan_and_rank(requests)
        self.assertEqual(
            [item.listing.item_id for item in diagnostics], ["cheap", "expensive"]
        )
        self.assertTrue(
            all(item.recommended_path == RAW_RESALE for item in diagnostics)
        )


class EnvironmentConfigurationTests(unittest.TestCase):
    def test_ebay_credentials_are_read_from_environment(self):
        env = {
            "EBAY_CLIENT_ID": "id-from-env",
            "EBAY_CLIENT_SECRET": "secret-from-env",
            "EBAY_V5_CATEGORY_ID": "183454",
            "EBAY_V5_RAW_ASPECT_NAME": "Graded",
            "EBAY_V5_RAW_ASPECT_VALUE": "No",
        }
        with patch.dict(os.environ, env, clear=True):
            config = EbayBrowseConfig.from_env()
        self.assertEqual(config.client_id, "id-from-env")
        self.assertEqual(config.category_id, "183454")


if __name__ == "__main__":
    unittest.main()
