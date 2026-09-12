from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_pricecharting_valuation as pc
import v4_global_marketplace_pricecharting_public_recovery as recovery


class _Response:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def json(self):
        return {}


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _lot(*, number="168/165", set_name="151", name="Charmander"):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test",
        title=name,
        current_price=30.0,
        source_type="auction",
        grader="PSA",
        grade="10",
        card_set=set_name,
        card_number=number,
        language="Japanese",
    )


def _provider(responses):
    return pc.PriceChartingProvider(
        config=pc.PriceChartingConfig(
            enabled=True,
            token=None,
            max_cards_per_run=8,
            public_request_interval_seconds=0.0,
        ),
        session=_Session(responses),
    )


class PriceChartingPublicRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recovery.install_global_marketplace_pricecharting_public_recovery()

    def test_search_redirect_product_page_is_scored_from_canonical_game_url(self):
        product = """
        <html><head>
          <link rel="canonical" href="https://www.pricecharting.com/game/pokemon-japanese-scarlet-%26-violet-151/charmander-168">
        </head><body>
          <h1>Charmander #168 Pokemon Japanese Scarlet &amp; Violet 151</h1>
          <div>Card Number: #168</div>
          <h2>Full Price Guide: Charmander #168 (Pokemon Japanese Scarlet &amp; Violet 151)</h2>
          <div>PSA 10 $110.17</div>
          <div>All prices are the current market price.</div>
        </body></html>
        """
        provider = _provider([_Response(product), _Response(product)])
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertAlmostEqual(evidence.estimate.central, 110.17)

    def test_html_entity_in_game_url_is_unescaped(self):
        url = recovery._pricecharting_game_url(
            "https://www.pricecharting.com/game/pokemon-japanese-scarlet-&amp;-violet-151/charmander-168"
        )
        self.assertIn("scarlet-&-violet-151", url)
        self.assertNotIn("amp;", url)

    def test_absolute_game_anchor_is_accepted_but_existing_exact_scoring_remains_required(self):
        search = """
        <a href="https://www.pricecharting.com/game/pokemon-japanese-promo/mischievous-pichu-214s-p">
          Mischievous Pichu #214/S-P
        </a>
        """
        product = """
        <h1>Mischievous Pichu #214/S-P Pokemon Japanese Promo</h1>
        <div>Card Number: #214/S-P</div>
        <h2>Full Price Guide: Mischievous Pichu #214/S-P (Pokemon Japanese Promo)</h2>
        <div>PSA 10 $114.99</div>
        <div>All prices are the current market price.</div>
        """
        provider = _provider([_Response(search), _Response(product)])
        lot = _lot(number="214/S-P", set_name="S-P Promotional", name="Mischievous Pichu")
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(lot, provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertAlmostEqual(evidence.estimate.central, 114.99)

    def test_full_fraction_no_match_gets_one_bounded_recovery_search(self):
        first_search = "<html><body>No exact result</body></html>"
        second_search = """
        <a href="/game/pokemon-japanese-scarlet-%26-violet-151/charmander-168">Charmander #168</a>
        """
        product = """
        <h1>Charmander #168 Pokemon Japanese Scarlet &amp; Violet 151</h1>
        <div>Card Number: #168</div>
        <h2>Full Price Guide: Charmander #168 (Pokemon Japanese Scarlet &amp; Violet 151)</h2>
        <div>PSA 10 $110.17</div>
        <div>All prices are the current market price.</div>
        """
        provider = _provider([_Response(first_search), _Response(second_search), _Response(product)])
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertIn("récupération de recherche", evidence.note)
        self.assertEqual(len(provider.session.calls), 3)

    def test_numeric_denominator_uses_provider_identity_surface_not_sold_title_noise(self):
        search = """
        <a href="/game/pokemon-japanese-mega-brave/bulbasaur-64">Bulbasaur #64</a>
        """
        product = """
        <h1>Bulbasaur #64 Pokemon Japanese Mega Brave</h1>
        <div>Card Number: #64</div>
        <div>Sold Listing: Wrong card 64/999 should not redefine product identity</div>
        <h2>Full Price Guide: Bulbasaur #64 (Pokemon Japanese Mega Brave)</h2>
        <div>PSA 10 $59.99</div>
        <div>All prices are the current market price.</div>
        """
        provider = _provider([_Response(search), _Response(product)])
        lot = _lot(number="64/63", set_name="Mega Brave", name="Bulbasaur")
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(lot, provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertAlmostEqual(evidence.estimate.central, 59.99)

    def test_explicit_wrong_numeric_denominator_on_identity_surface_still_blocks(self):
        search = """
        <a href="/game/pokemon-japanese-mega-brave/bulbasaur-64">Bulbasaur #64</a>
        """
        product = """
        <h1>Bulbasaur #64/999 Pokemon Japanese Mega Brave</h1>
        <div>Card Number: #64/999</div>
        <h2>Full Price Guide: Bulbasaur #64 (Pokemon Japanese Mega Brave)</h2>
        <div>PSA 10 $59.99</div>
        """
        provider = _provider([_Response(search), _Response(product)])
        result = provider.lookup(_lot(number="64/63", set_name="Mega Brave", name="Bulbasaur"))
        self.assertEqual(result.status, "CLEAN_NO_MATCH")
        self.assertIn("conflit", result.note)

    def test_direct_provider_url_recovery_is_revalidated_for_magneton(self):
        no_result = "<html><body>No result</body></html>"
        product = """
        <h1>Magneton #112 Pokemon Japanese Super Electric Breaker</h1>
        <div>Card Number: #112</div>
        <h2>Full Price Guide: Magneton #112 (Pokemon Japanese Super Electric Breaker)</h2>
        <div>PSA 10 $53.20</div>
        <div>All prices are the current market price.</div>
        """
        provider = _provider([_Response(no_result), _Response(no_result), _Response(product)])
        lot = _lot(number="112/106", set_name="Super Electric Breaker", name="Magneton")
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(lot, provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertIn("URL fournisseur", evidence.note)
        self.assertTrue(provider.session.calls[-1][0].endswith("/pokemon-japanese-super-electric-breaker/magneton-112"))

    def test_promo_recovery_query_keeps_full_code(self):
        lot = _lot(number="242/SV-P", set_name="SV-P Promos", name="Pikachu")
        query = recovery._recovery_query(lot)
        self.assertIn("242/SV-P", query)
        self.assertIn("Pokemon Japanese Promo", query)

    def test_ambiguous_second_search_never_becomes_matched(self):
        first_search = "<html><body>No exact result</body></html>"
        second_search = """
        <a href="/game/pokemon-japanese-set-a/charmander-168">Charmander #168</a>
        <a href="/game/pokemon-japanese-set-b/charmander-168">Charmander #168</a>
        """
        provider = _provider([_Response(first_search), _Response(second_search)])
        result = provider.lookup(_lot(set_name="Unknown Set"))
        self.assertNotEqual(result.status, "MATCHED")

    def test_full_price_guide_psa10_does_not_read_ungraded_compare_price(self):
        body = """
        Compare vs Other Items
        Ungraded | Grade 7 | Grade 8 | Grade 9 | Grade 9.5 | PSA 10
        $10.99 | $13.51 | $25.00 | $27.65 | $30.00 | $56.00

        Full Price Guide: Bulbasaur #64 (Pokemon Japanese Mega Brave)
        Ungraded | $10.99
        Grade 8 | $25.00
        Grade 9 | $27.65
        Grade 9.5 | $30.00
        PSA 10 | $56.00
        BGS 10 | $60.00

        All prices are the current market price.
        """
        self.assertEqual(pc._public_guide_value(body, "manual-only-price"), 56.0)
        self.assertEqual(pc._public_guide_value(body, "graded-price"), 27.65)
        self.assertEqual(pc._public_guide_value(body, "new-price"), 25.0)

    def test_explicit_promo_coordinate_conflict_is_rejected_before_numerator_scoring(self):
        wrong = {
            "id": "https://www.pricecharting.com/game/pokemon-japanese-promo/pikachu-daiichi-pan-291sm-p",
            "product-name": "Pikachu #291/SM-P",
            "console-name": "Pokemon Japanese Promo",
        }
        lot = _lot(number="291/SV-P", set_name="SV-P", name="Pikachu")
        self.assertTrue(recovery._candidate_has_number_conflict(lot, wrong))
        self.assertEqual(recovery._safe_candidates(lot, (wrong,)), ())

    def test_promo_coordinate_requires_exact_full_code_not_numerator_only(self):
        numerator_only = {
            "id": "https://www.pricecharting.com/game/pokemon-japanese-promo/pikachu-291",
            "product-name": "Pikachu #291",
            "console-name": "Pokemon Japanese Promo",
        }
        lot = _lot(number="291/SV-P", set_name="SV-P", name="Pikachu")
        self.assertTrue(recovery._candidate_has_number_conflict(lot, numerator_only))

    def test_one_http_429_is_retried_once_then_success(self):
        search = """
        <a href="/game/pokemon-japanese-scarlet-%26-violet-151/charmander-168">Charmander #168</a>
        """
        product = """
        <h1>Charmander #168 Pokemon Japanese Scarlet &amp; Violet 151</h1>
        <div>Card Number: #168</div>
        <h2>Full Price Guide: Charmander #168 (Pokemon Japanese Scarlet &amp; Violet 151)</h2>
        <div>PSA 10 $110.17</div>
        <div>All prices are the current market price.</div>
        """
        provider = _provider([_Response("rate limited", 429), _Response(search), _Response(product)])
        with (
            patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0),
            patch.object(recovery.time, "sleep", return_value=None),
        ):
            evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(len(provider.session.calls), 3)


if __name__ == "__main__":
    unittest.main()
