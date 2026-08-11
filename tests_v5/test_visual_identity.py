from __future__ import annotations

import io
import unittest
from decimal import Decimal

from PIL import Image, ImageDraw

from v5.card_number_ocr import CardNumberOCRConfig, LocalCardNumberOCR
from v5.market_values.poketrace import PokeTraceConfig, PokeTraceProvider
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import PokeTraceIdentityResolver
from v5.visual_identity import LocalVisualIdentityResolver, render_visual_identity_counters


class Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


class PokeTraceSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/v1/cards"):
            payload = self.payload(kwargs) if callable(self.payload) else self.payload
            return Response(payload)
        raise AssertionError(f"unexpected network image request: {url}")


def provider(session, *, pro=False):
    provider_type = PokeTraceProvider if pro else FreeTierPokeTraceProvider
    return provider_type(
        config=PokeTraceConfig(
            enabled=True,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        ),
        session=session,
        sleeper=lambda _seconds: None,
    )


def card_payload(
    card_id,
    number,
    image_url,
    *,
    variant="Holofoil",
    market="US",
):
    return {
        "id": card_id,
        "name": "Charizard",
        "cardNumber": number,
        "set": {"name": "Base Set", "slug": "base-set"},
        "variant": variant,
        "rarity": "Rare Holo",
        "productType": "single",
        "market": market,
        "currency": "USD" if market == "US" else "EUR",
        "image": image_url,
        "prices": (
            {
                "ebay": {"NEAR_MINT": {"median7d": 100}},
                "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
            }
            if market == "US"
            else {
                "cardmarket": {
                    "AGGREGATED": {"avg": 80, "avg7d": 82, "avg30d": 85}
                },
                "cardmarket_unsold": {"NEAR_MINT": {"low": 65, "median7d": 81}},
            }
        ),
    }


def identity(number=None, *, ambiguous=False):
    return CardIdentity(
        game="Pokemon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number=number,
        language="English",
        variant="Holofoil",
        ambiguities=("catalog_identity_ambiguous",) if ambiguous else (),
    )


def card_image(style):
    image = Image.new("RGB", (300, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 290, 410), outline="black", width=8)
    if style == "a":
        draw.rectangle((30, 32, 270, 88), fill=(180, 30, 30))
        draw.rectangle((45, 105, 255, 260), fill=(25, 85, 185))
        draw.ellipse((85, 135, 215, 245), fill=(240, 170, 25), outline="black", width=5)
        draw.rectangle((35, 290, 265, 365), fill=(235, 215, 70))
        draw.line((50, 315, 250, 315), fill="black", width=6)
        draw.line((50, 340, 210, 340), fill="black", width=5)
    elif style == "b":
        draw.rectangle((30, 32, 270, 88), fill=(35, 135, 55))
        draw.rectangle((45, 105, 255, 260), fill=(160, 45, 155))
        draw.polygon(((150, 125), (235, 235), (65, 235)), fill=(80, 210, 210))
        draw.rectangle((35, 290, 265, 365), fill=(90, 185, 130))
        draw.line((65, 305, 235, 350), fill="black", width=7)
    else:
        draw.rectangle((30, 32, 270, 365), fill=(125, 125, 125))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def ebay_photo(card_bytes):
    card = Image.open(io.BytesIO(card_bytes)).convert("RGB")
    card = card.resize((255, 357))
    canvas = Image.new("RGB", (480, 480), (225, 220, 205))
    canvas.paste(card, (115, 60))
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


class SequenceOCRRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def __call__(self, _png_bytes, _psm, _timeout):
        return self.outputs.pop(0) if self.outputs else ""


class LocalVisualIdentityTests(unittest.TestCase):
    def make_resolver(self, payload, ebay_images, canonical_images, **kwargs):
        session = PokeTraceSession(payload)
        market = provider(session, pro=kwargs.pop("pro", False))
        identity_resolver = PokeTraceIdentityResolver(market)
        visual = LocalVisualIdentityResolver(
            identity_resolver,
            ebay_image_fetcher=lambda url: ebay_images.get(url),
            candidate_image_fetcher=lambda url: canonical_images.get(url),
            enabled=True,
            minimum_score=kwargs.pop("minimum_score", 0.60),
            minimum_margin=kwargs.pop("minimum_margin", 0.06),
            override_number_minimum_score=kwargs.pop(
                "override_number_minimum_score", 0.60
            ),
            override_number_minimum_margin=kwargs.pop(
                "override_number_minimum_margin", 0.06
            ),
            **kwargs,
        )
        return session, market, visual

    def test_visual_match_rescues_missing_card_number_and_primes_market(self):
        a = card_image("a")
        b = card_image("b")
        payload = {
            "data": [
                card_payload("char-a", "004/102", "https://cdn.poketrace.com/a.png"),
                card_payload("char-b", "11/108", "https://cdn.poketrace.com/b.png"),
            ]
        }
        session, market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {
                "https://cdn.poketrace.com/a.png": a,
                "https://cdn.poketrace.com/b.png": b,
            },
        )

        result = visual.resolve_identity(
            identity(number=None), ["https://i.ebayimg.com/front.png"]
        )
        snapshot = market.snapshot_for(result.identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, "char-a")
        self.assertEqual(result.identity.card_number, "004/102")
        self.assertEqual(visual.counters.rescued, 1)
        self.assertEqual(visual.counters.market_snapshots_primed, 1)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))
        api_calls = [call for call in session.calls if call[0].endswith("/v1/cards")]
        self.assertEqual(len(api_calls), 1)

    def test_wrong_structured_number_can_be_overridden_only_by_strong_visual_evidence(self):
        a = card_image("a")
        b = card_image("b")
        payload = {
            "data": [
                card_payload("char-a", "004/102", "https://cdn.poketrace.com/a.png"),
                card_payload("char-b", "11/108", "https://cdn.poketrace.com/b.png"),
            ]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {
                "https://cdn.poketrace.com/a.png": a,
                "https://cdn.poketrace.com/b.png": b,
            },
        )

        result = visual.resolve_identity(
            identity(number="999/999", ambiguous=True),
            ["https://i.ebayimg.com/front.png"],
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.identity.card_number, "004/102")
        self.assertEqual(result.identity.ambiguities, ())
        self.assertEqual(visual.counters.card_number_overrides, 1)
        self.assertEqual(visual.counters.ambiguities_cleared, 1)

    def test_visually_identical_candidates_remain_ambiguous(self):
        a = card_image("a")
        payload = {
            "data": [
                card_payload("char-a", "004/102", "https://cdn.poketrace.com/a.png"),
                card_payload("char-a-variant", "004/102", "https://cdn.poketrace.com/a2.png"),
            ]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {
                "https://cdn.poketrace.com/a.png": a,
                "https://cdn.poketrace.com/a2.png": a,
            },
        )

        result = visual.resolve_identity(
            identity(number=None, ambiguous=True),
            ["https://i.ebayimg.com/front.png"],
        )

        self.assertFalse(result.matched)
        self.assertEqual(visual.counters.close_second, 1)
        self.assertEqual(visual.counters.rescued, 0)

    def test_low_confidence_photo_is_rejected(self):
        a = card_image("a")
        b = card_image("b")
        payload = {
            "data": [
                card_payload("char-a", "004/102", "https://cdn.poketrace.com/a.png"),
                card_payload("char-b", "11/108", "https://cdn.poketrace.com/b.png"),
            ]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": card_image("gray")},
            {
                "https://cdn.poketrace.com/a.png": a,
                "https://cdn.poketrace.com/b.png": b,
            },
            minimum_score=0.98,
        )

        result = visual.resolve_identity(
            identity(number=None), ["https://i.ebayimg.com/front.png"]
        )

        self.assertFalse(result.matched)
        self.assertEqual(visual.counters.low_confidence, 1)

    def test_local_ocr_can_rescue_after_visual_low_confidence(self):
        a = card_image("a")
        b = card_image("b")
        payload = {
            "data": [
                card_payload("char-a", "004/102", "https://cdn.poketrace.com/a.png"),
                card_payload("char-b", "11/108", "https://cdn.poketrace.com/b.png"),
            ]
        }
        local_ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(
                enabled=True,
                minimum_votes=2,
                override_minimum_votes=3,
            ),
            runner=SequenceOCRRunner(["004/102", "004/102", "004/102", ""]),
        )
        _session, market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": card_image("gray")},
            {
                "https://cdn.poketrace.com/a.png": a,
                "https://cdn.poketrace.com/b.png": b,
            },
            minimum_score=0.99,
            override_number_minimum_score=0.99,
            card_number_ocr=local_ocr,
        )

        result = visual.resolve_identity(
            identity(number="999/999", ambiguous=True),
            ["https://i.ebayimg.com/front.png"],
        )
        snapshot = market.snapshot_for(result.identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, "char-a")
        self.assertEqual(result.identity.card_number, "004/102")
        self.assertEqual(result.identity.ambiguities, ())
        self.assertEqual(visual.counters.rescued, 0)
        self.assertEqual(visual.counters.ocr_rescued, 1)
        self.assertEqual(local_ocr.counters.structured_number_overrides, 1)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))

    def test_renderer_does_not_expose_key_or_image_urls(self):
        a = card_image("a")
        payload = {
            "data": [
                card_payload("char-a", "004/102", "https://cdn.poketrace.com/a.png")
            ]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {"https://cdn.poketrace.com/a.png": a},
        )
        visual.resolve_identity(identity(number=None), ["https://i.ebayimg.com/front.png"])
        rendered = render_visual_identity_counters(visual)
        self.assertNotIn("secret-never-render", rendered)
        self.assertNotIn("ebayimg", rendered)
        self.assertNotIn("poketrace.com/a", rendered)
        self.assertIn("persisted images/OCR text: 0", rendered)
        self.assertIn("model API calls: 0", rendered)
        self.assertIn("no visual candidates after metadata filter", rendered)
        self.assertIn("no usable eBay image after fetch", rendered)

    def test_non_us_rescue_primes_strict_eu_snapshot_without_replacing_identity(self):
        a = card_image("a")
        us = card_payload("us-char", "004/102", "https://cdn.poketrace.com/us.png")
        eu = card_payload(
            "eu-char", "004/102", "https://cdn.poketrace.com/eu.png", market="EU"
        )
        payload = lambda kwargs: {
            "data": [us if kwargs["params"]["market"] == "US" else eu]
        }
        session, market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {"https://cdn.poketrace.com/us.png": a},
            eu_enrichment_enabled=True,
            pro=True,
        )

        result = visual.resolve_identity(
            identity(number=None),
            ["https://i.ebayimg.com/front.png"],
            marketplace_id="EBAY_IT",
        )
        snapshot = market.snapshot_for(result.identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.identity.language, "English")
        self.assertEqual(snapshot.us_record_id, "us-char")
        self.assertEqual(snapshot.eu_record_id, "eu-char")
        self.assertEqual(visual.counters.eu_enrichment_attempts, 1)
        self.assertEqual(visual.counters.eu_enrichment_matches, 1)
        self.assertEqual(visual.counters.cardmarket_snapshots_recovered, 1)
        self.assertEqual(
            [call[1]["params"]["market"] for call in session.calls],
            ["US", "EU"],
        )

    def test_eu_missing_variant_requires_independent_visual_confirmation(self):
        a = card_image("a")
        us = card_payload("us-char", "004/102", "https://cdn.poketrace.com/us.png")
        eu = card_payload(
            "eu-char",
            "004/102",
            "https://cdn.poketrace.com/eu.png",
            market="EU",
            variant=None,
        )
        payload = lambda kwargs: {
            "data": [us if kwargs["params"]["market"] == "US" else eu]
        }
        _session, market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {
                "https://cdn.poketrace.com/us.png": a,
                "https://cdn.poketrace.com/eu.png": a,
            },
            eu_enrichment_enabled=True,
            pro=True,
        )

        result = visual.resolve_identity(
            identity(number=None),
            ["https://i.ebayimg.com/front.png"],
            marketplace_id="EBAY_ES",
        )

        self.assertTrue(result.matched)
        self.assertEqual(market.snapshot_for(result.identity).eu_record_id, "eu-char")
        self.assertEqual(visual.counters.eu_enrichment_matches, 1)

    def test_eu_explicit_variant_conflict_is_rejected_even_if_image_matches(self):
        a = card_image("a")
        us = card_payload("us-char", "004/102", "https://cdn.poketrace.com/us.png")
        eu = card_payload(
            "eu-reverse",
            "004/102",
            "https://cdn.poketrace.com/eu.png",
            market="EU",
            variant="Reverse Holofoil",
        )
        payload = lambda kwargs: {
            "data": [us if kwargs["params"]["market"] == "US" else eu]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {
                "https://cdn.poketrace.com/us.png": a,
                "https://cdn.poketrace.com/eu.png": a,
            },
            eu_enrichment_enabled=True,
            pro=True,
        )

        visual.resolve_identity(
            identity(number=None),
            ["https://i.ebayimg.com/front.png"],
            marketplace_id="EBAY_FR",
        )

        self.assertEqual(visual.counters.eu_enrichment_matches, 0)
        self.assertEqual(visual.counters.eu_enrichment_rejected_variant, 1)

    def test_eu_wrong_core_and_missing_image_stay_rejected(self):
        a = card_image("a")
        us = card_payload("us-char", "004/102", "https://cdn.poketrace.com/us.png")
        wrong_core = card_payload(
            "eu-partial-number",
            "004",
            "https://cdn.poketrace.com/wrong.png",
            market="EU",
        )
        missing_scan = card_payload(
            "eu-no-scan",
            "004/102",
            "",
            market="EU",
            variant=None,
        )
        payload = lambda kwargs: {
            "data": [
                us
                if kwargs["params"]["market"] == "US"
                else wrong_core,
                *(
                    []
                    if kwargs["params"]["market"] == "US"
                    else [missing_scan]
                ),
            ]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {"https://cdn.poketrace.com/us.png": a},
            eu_enrichment_enabled=True,
            pro=True,
        )

        visual.resolve_identity(
            identity(number=None),
            ["https://i.ebayimg.com/front.png"],
            marketplace_id="EBAY_DE",
        )

        self.assertEqual(visual.counters.eu_enrichment_matches, 0)
        self.assertEqual(visual.counters.eu_enrichment_rejected_core, 1)
        self.assertEqual(visual.counters.eu_enrichment_rejected_no_image, 1)

    def test_multiple_exact_eu_variants_remain_ambiguous(self):
        a = card_image("a")
        us = card_payload("us-char", "004/102", "https://cdn.poketrace.com/us.png")
        eu_one = card_payload(
            "eu-one", "004/102", "https://cdn.poketrace.com/eu-one.png", market="EU"
        )
        eu_two = card_payload(
            "eu-two", "004/102", "https://cdn.poketrace.com/eu-two.png", market="EU"
        )
        payload = lambda kwargs: {
            "data": [
                us
                if kwargs["params"]["market"] == "US"
                else eu_one,
                *([] if kwargs["params"]["market"] == "US" else [eu_two]),
            ]
        }
        _session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {"https://cdn.poketrace.com/us.png": a},
            eu_enrichment_enabled=True,
            pro=True,
        )

        visual.resolve_identity(
            identity(number=None),
            ["https://i.ebayimg.com/front.png"],
            marketplace_id="EBAY_IT",
        )

        self.assertEqual(visual.counters.eu_enrichment_matches, 0)
        self.assertEqual(visual.counters.eu_enrichment_ambiguous, 1)

    def test_us_rescue_never_attempts_eu_enrichment(self):
        a = card_image("a")
        payload = {
            "data": [
                card_payload(
                    "us-char", "004/102", "https://cdn.poketrace.com/us.png"
                )
            ]
        }
        session, _market, visual = self.make_resolver(
            payload,
            {"https://i.ebayimg.com/front.png": ebay_photo(a)},
            {"https://cdn.poketrace.com/us.png": a},
            eu_enrichment_enabled=True,
            pro=True,
        )

        visual.resolve_identity(
            identity(number=None),
            ["https://i.ebayimg.com/front.png"],
            marketplace_id="EBAY_US",
        )

        self.assertEqual(visual.counters.eu_enrichment_attempts, 0)
        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
