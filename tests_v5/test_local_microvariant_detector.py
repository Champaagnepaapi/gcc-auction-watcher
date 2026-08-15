from __future__ import annotations

import io
import unittest
from dataclasses import replace

from PIL import Image, ImageDraw

from tests_v5.test_visual_identity import PokeTraceSession, card_payload, identity, provider
from v5.microvariant_detector import (
    CanonicalMicrovariantReference,
    DeterministicLocalMicrovariantEvidenceProvider,
    MicrovariantEvidenceRequest,
)
from v5.microvariants import (
    EDITION_CONFLICT,
    EDITION_UNKNOWN,
    FIRST_EDITION_CONFIRMED,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_NOT_APPLICABLE,
    OTHER_VARIANT_CONFIRMED,
    UNLIMITED_CONFIRMED,
    LocalMicrovariantValidator,
    MicrovariantApplicability,
)
from v5.poketrace_identity import PokeTraceIdentityResolver
from v5.visual_identity import LocalVisualIdentityResolver


def synthetic_card(marker: str = "none", *, size=(256, 356), glare=False) -> bytes:
    image = Image.new("RGB", size, (34, 78, 112))
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle((4, 4, width - 5, height - 5), outline=(235, 190, 65), width=max(2, width // 50))
    draw.rectangle((18, 30, width - 19, int(height * 0.58)), fill=(55, 135, 95))
    draw.ellipse((int(width * .27), int(height * .18), int(width * .73), int(height * .48)), fill=(205, 105, 55))
    draw.rectangle((20, int(height * .68), width - 21, int(height * .88)), fill=(210, 180, 82))
    if marker == "first":
        draw.rectangle((18, int(height * .55), 74, int(height * .66)), fill=(15, 15, 15))
        draw.line((23, int(height * .60), 68, int(height * .60)), fill=(245, 245, 245), width=5)
    elif marker == "promo":
        draw.ellipse((width - 82, 18, width - 20, 80), fill=(235, 35, 45), outline="white", width=5)
    elif marker == "stamp":
        draw.rectangle((width - 118, int(height * .52), width - 14, int(height * .69)), fill=(245, 245, 245))
        draw.line((width - 108, int(height * .60), width - 24, int(height * .60)), fill=(15, 15, 15), width=8)
    elif marker == "tiny":
        draw.rectangle((18, int(height * .55), 20, int(height * .55) + 2), fill="black")
    if glare:
        draw.rectangle((0, 0, int(width * .55), int(height * .62)), fill="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def candidate(
    variant: str,
    *,
    card_id: str = "fixture",
    image: str = "https://cdn.poketrace.com/fixture.png",
    set_name: str = "Base Set",
    language: str | None = "English",
    rarity: str = "Rare",
):
    value = card_payload(card_id, "004/102", image, variant=variant)
    value["set"] = {"name": set_name, "slug": set_name.casefold().replace(" ", "-")}
    value["rarity"] = rarity
    if language is not None:
        value["language"] = language
    return value


def evidence_request(
    seller: bytes,
    winning,
    winning_scan: bytes | None,
    competitors=(),
):
    return MicrovariantEvidenceRequest(
        identity("004/102"),
        winning,
        (seller,),
        CanonicalMicrovariantReference(winning, winning_scan) if winning_scan else None,
        tuple(CanonicalMicrovariantReference(metadata, scan) for metadata, scan in competitors),
        MicrovariantApplicability(MICROVARIANT_APPLICABLE, "OFFLINE_FIXTURE"),
    )


class DeterministicDetectorUnitTests(unittest.TestCase):
    def setUp(self):
        self.detector = DeterministicLocalMicrovariantEvidenceProvider()
        self.validator = LocalMicrovariantValidator()
        self.first = candidate("1st Edition Holofoil", card_id="first")
        self.unlimited = candidate("Unlimited Holofoil", card_id="unlimited")
        self.first_scan = synthetic_card("first")
        self.unlimited_scan = synthetic_card("none")

    def resolve(self, seller, winning, winning_scan, competitors):
        evidence = self.detector(evidence_request(seller, winning, winning_scan, competitors))
        return self.validator.resolve(
            identity("004/102"),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "OFFLINE_FIXTURE"),
            candidate=winning,
            evidence=evidence,
            visual_attempted=True,
        )

    def test_01_default_detector_is_concrete(self):
        visual = LocalVisualIdentityResolver(
            PokeTraceIdentityResolver(provider(PokeTraceSession({"data": []}))),
            ebay_image_fetcher=lambda _url: None,
        )
        self.assertIsInstance(
            visual.microvariant_evidence_provider,
            DeterministicLocalMicrovariantEvidenceProvider,
        )

    def test_02_exact_pair_confirms_first(self):
        result = self.resolve(self.first_scan, self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.assertEqual(result.edition_status, FIRST_EDITION_CONFIRMED)
        self.assertFalse(result.blocks_economics)

    def test_03_exact_pair_confirms_unlimited(self):
        result = self.resolve(self.unlimited_scan, self.unlimited, self.unlimited_scan, ((self.first, self.first_scan),))
        self.assertEqual(result.edition_status, UNLIMITED_CONFIRMED)
        self.assertFalse(result.blocks_economics)

    def test_04_cropped_region_stays_unknown(self):
        image = Image.open(io.BytesIO(self.first_scan)).crop((0, 0, 80, 356))
        output = io.BytesIO(); image.save(output, "PNG")
        result = self.resolve(output.getvalue(), self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)

    def test_05_low_resolution_stays_unknown(self):
        result = self.resolve(synthetic_card("first", size=(64, 89)), self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)

    def test_06_glare_stays_unknown(self):
        result = self.resolve(synthetic_card("first", glare=True), self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)

    def test_07_bad_alignment_stays_unknown(self):
        unrelated = Image.new("RGB", (256, 356), (10, 10, 10))
        draw = ImageDraw.Draw(unrelated)
        for offset in range(0, 356, 24):
            draw.line((0, offset, 255, 355 - offset), fill="white", width=7)
        output = io.BytesIO(); unrelated.save(output, "PNG")
        result = self.resolve(output.getvalue(), self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)

    def test_08_near_identical_references_below_margin_stay_unknown(self):
        close = synthetic_card("tiny")
        result = self.resolve(self.unlimited_scan, self.unlimited, self.unlimited_scan, ((self.first, close),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)

    def test_09_only_premium_reference_never_confirms(self):
        result = self.resolve(self.first_scan, self.first, self.first_scan, ())
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)

    def test_10_provider_first_metadata_is_not_visual_evidence(self):
        result = self.resolve(self.first_scan, self.first, self.first_scan, ())
        self.assertTrue(result.premium_candidate_not_inherited)
        self.assertFalse(result.visual_confirmed)

    def test_11_seller_unlimited_against_winning_first_is_conflict(self):
        result = self.resolve(self.unlimited_scan, self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_CONFLICT)

    def test_12_seller_first_against_winning_unlimited_is_conflict(self):
        result = self.resolve(self.first_scan, self.unlimited, self.unlimited_scan, ((self.first, self.first_scan),))
        self.assertEqual(result.edition_status, EDITION_CONFLICT)

    def test_13_cross_set_reference_rejected_by_reference_assembler(self):
        wrong = candidate("Unlimited Holofoil", set_name="Jungle")
        self.assertFalse(LocalVisualIdentityResolver._same_exact_macro(identity("004/102"), self.first, wrong))

    def test_14_cross_language_reference_rejected_by_reference_assembler(self):
        first = candidate("1st Edition Holofoil", language="English")
        french = candidate("Unlimited Holofoil", language="French")
        self.assertFalse(LocalVisualIdentityResolver._same_exact_macro(identity("004/102"), first, french))

    def test_15_exact_promo_pair_can_confirm(self):
        promo = candidate("Holofoil", rarity="Promo")
        standard = candidate("Holofoil", rarity="Rare")
        result = self.resolve(synthetic_card("promo"), promo, synthetic_card("promo"), ((standard, self.unlimited_scan),))
        self.assertEqual(result.edition_status, OTHER_VARIANT_CONFIRMED)

    def test_16_exact_stamped_pair_can_confirm(self):
        stamped = candidate("Stamped Holofoil")
        normal = candidate("Holofoil")
        result = self.resolve(synthetic_card("stamp"), stamped, synthetic_card("stamp"), ((normal, self.unlimited_scan),))
        self.assertEqual(result.edition_status, OTHER_VARIANT_CONFIRMED)

    def test_17_holo_reverse_static_pair_is_unknown(self):
        holo = candidate("Holofoil")
        reverse = candidate("Reverse Holofoil")
        result = self.resolve(self.first_scan, holo, self.first_scan, ((reverse, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)
        self.assertEqual(result.blocker_dimension, "finish")

    def test_18_multiple_dimensions_stay_unknown(self):
        premium = candidate("1st Edition Stamped Holofoil")
        other = candidate("Unlimited Reverse Holofoil")
        result = self.resolve(self.first_scan, premium, self.first_scan, ((other, self.unlimited_scan),))
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)
        self.assertEqual(result.blocker_dimension, "multiple")

    def test_19_detection_is_memory_only(self):
        request = evidence_request(self.first_scan, self.first, self.first_scan, ((self.unlimited, self.unlimited_scan),))
        self.detector(request)
        self.assertFalse(hasattr(self.detector, "path"))
        self.assertFalse(hasattr(self.detector, "session"))

    def test_20_detector_has_no_model_client(self):
        self.assertFalse(any("model" in name or "vision" in name for name in vars(self.detector)))

    def test_21_explicit_unlimited_metadata_vs_first_pixels_is_conflict(self):
        evidence = self.detector(
            evidence_request(
                self.first_scan,
                self.unlimited,
                self.unlimited_scan,
                ((self.first, self.first_scan),),
            )
        )
        result = self.validator.resolve(
            replace(identity("004/102"), edition="Unlimited"),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            candidate=self.unlimited,
            evidence=evidence,
            visual_attempted=True,
        )
        self.assertEqual(result.edition_status, EDITION_CONFLICT)

    def test_22_explicit_first_metadata_vs_unlimited_pixels_is_conflict(self):
        evidence = self.detector(
            evidence_request(
                self.unlimited_scan,
                self.first,
                self.first_scan,
                ((self.unlimited, self.unlimited_scan),),
            )
        )
        result = self.validator.resolve(
            replace(identity("004/102"), edition="1st Edition"),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            candidate=self.first,
            evidence=evidence,
            visual_attempted=True,
        )
        self.assertEqual(result.edition_status, EDITION_CONFLICT)


class DetectorPipelineGateTests(unittest.TestCase):
    def make_visual(self, *, seller_marker="first", include_competitor=True, eu=False, post=None):
        first_scan = synthetic_card("first")
        unlimited_scan = synthetic_card("none")
        first = candidate("1st Edition Holofoil", card_id="first", image="https://cdn.poketrace.com/first.png")
        unlimited = candidate("Unlimited Holofoil", card_id="unlimited", image="https://cdn.poketrace.com/unlimited.png")
        us_cards = [first] + ([unlimited] if include_competitor else [])
        eu_first = candidate("1st Edition Holofoil", card_id="eu-first", image="https://cdn.poketrace.com/eu-first.png")
        eu_first["market"] = "EU"; eu_first["currency"] = "EUR"
        eu_first["prices"] = {"cardmarket": {"AGGREGATED": {"avg": 80}}}
        payload = (lambda kwargs: {"data": us_cards if kwargs["params"]["market"] == "US" else [eu_first]}) if eu else {"data": us_cards}
        session = PokeTraceSession(payload)
        market = provider(session, pro=eu)
        images = {
            "https://cdn.poketrace.com/first.png": first_scan,
            "https://cdn.poketrace.com/unlimited.png": unlimited_scan,
            "https://cdn.poketrace.com/eu-first.png": first_scan,
        }
        seller = first_scan if seller_marker == "first" else unlimited_scan
        visual = LocalVisualIdentityResolver(
            PokeTraceIdentityResolver(market),
            ebay_image_fetcher=lambda _url: seller,
            candidate_image_fetcher=lambda url: images.get(url),
            enabled=True,
            minimum_score=0.50,
            minimum_margin=0.0,
            eu_enrichment_enabled=eu,
            post_macro_applicability_resolver=post,
        )
        return session, market, visual

    def test_23_confirmed_microvariant_allows_us_snapshot_prime(self):
        _session, market, visual = self.make_visual()
        result = visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",), microvariant_applicability=MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"))
        self.assertTrue(result.matched)
        self.assertEqual(result.microvariant.edition_status, FIRST_EDITION_CONFIRMED)
        self.assertIsNotNone(market.snapshot_for(result.identity))
        self.assertEqual(visual.counters.market_snapshots_primed, 1)

    def test_24_unknown_prevents_us_snapshot_prime(self):
        _session, market, visual = self.make_visual(include_competitor=False)
        result = visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",), microvariant_applicability=MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"))
        self.assertTrue(result.microvariant.blocks_economics)
        self.assertIsNone(market.snapshot_for(result.identity).us_values)
        self.assertEqual(visual.counters.market_snapshots_primed, 0)
        self.assertEqual(visual.counters.market_snapshot_not_primed_microvariant, 1)

    def test_25_confirmed_non_us_runs_exactly_one_eu_enrichment(self):
        session, _market, visual = self.make_visual(eu=True)
        result = visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",), marketplace_id="EBAY_FR", microvariant_applicability=MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"))
        self.assertEqual(result.microvariant.edition_status, FIRST_EDITION_CONFIRMED)
        self.assertEqual(visual.counters.eu_enrichment_attempts, 1)
        self.assertEqual(visual.counters.eu_enrichment_matches, 1)
        self.assertEqual([call[1]["params"]["market"] for call in session.calls], ["US", "EU"])

    def test_26_unknown_prevents_eu_and_counts_reason(self):
        session, _market, visual = self.make_visual(include_competitor=False, eu=True)
        visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",), marketplace_id="EBAY_FR", microvariant_applicability=MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"))
        self.assertEqual(visual.counters.eu_enrichment_attempts, 0)
        self.assertEqual(visual.counters.eu_enrichment_not_attempted_microvariant, 1)
        self.assertEqual(len(session.calls), 1)

    def test_27_two_blocked_rescues_count_pre_market_twice(self):
        _session, _market, visual = self.make_visual(include_competitor=False)
        for _ in range(2):
            visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",), microvariant_applicability=MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"))
        self.assertEqual(visual.counters.market_snapshot_not_primed_microvariant, 2)
        self.assertEqual(visual.counters.microvariant_gate_blocked_before_market, 2)

    def test_28_post_macro_applicability_gets_one_second_chance(self):
        calls = []
        def post(resolved):
            calls.append(resolved)
            return MicrovariantApplicability(MICROVARIANT_APPLICABLE, "TCGDEX_EXACT")
        _session, _market, visual = self.make_visual(post=post)
        result = visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.microvariant.edition_status, FIRST_EDITION_CONFIRMED)
        self.assertEqual(visual.counters.applicability_post_macro_resolved, 1)

    def test_29_not_applicable_does_not_invoke_detector_gate(self):
        _session, _market, visual = self.make_visual(include_competitor=False)
        result = visual.resolve_identity(identity(None), ("https://i.ebayimg.com/front.png",), microvariant_applicability=MicrovariantApplicability(MICROVARIANT_NOT_APPLICABLE, "TCGDEX_EXACT"))
        self.assertFalse(result.microvariant.visual_attempted)
        self.assertTrue(result.microvariant.blocks_economics)
        self.assertEqual(result.microvariant.edition_status, EDITION_CONFLICT)


if __name__ == "__main__":
    unittest.main()
