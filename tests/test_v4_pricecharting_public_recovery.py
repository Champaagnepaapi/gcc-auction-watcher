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
          <h2>Full Price Guide</h2>
          <div>PSA 10 $110.17</div>
        </body></html>
        """
        provider = _provider([_Response(product), _Response(product)])
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertAlmostEqual(evidence.estimate.central, 110.17)

    def test_absolute_game_anchor_is_accepted_but_existing_exact_scoring_remains_required(self):
        search = """
        <a href="https://www.pricecharting.com/game/pokemon-japanese-promo/mischievous-pichu-214s-p">
          Mischievous Pichu #214/S-P
        </a>
        """
        product = """
        <h1>Mischievous Pichu #214/S-P Pokemon Japanese Promo</h1>
        <div>Card Number: #214/S-P</div>
        <div>PSA 10 $114.99</div>
        """
        provider = _provider([_Response(search), _Response(product)])
        lot = _lot(number="214/S-P", set_name="S-P Promotional", name="Mischievous Pichu")
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(lot, provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertAlmostEqual(evidence.estimate.central, 114.99)

    def test_full_fraction_no_match_gets_one_numerator_retry_without_lowering_match_threshold(self):
        first_search = "<html><body>No exact result</body></html>"
        second_search = """
        <a href="/game/pokemon-japanese-scarlet-%26-violet-151/charmander-168">Charmander #168</a>
        """
        product = """
        <h1>Charmander #168 Pokemon Japanese Scarlet &amp; Violet 151</h1>
        <div>Card Number: #168</div>
        <div>PSA 10 $110.17</div>
        """
        provider = _provider([_Response(first_search), _Response(second_search), _Response(product)])
        with patch.object(watcher, "get_psa_apr_usd_per_eur", return_value=1.0):
            evidence = pc.pricecharting_evidence_for_lot(_lot(), provider=provider)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertIn("numerator", evidence.note)
        self.assertEqual(len(provider.session.calls), 3)

    def test_ambiguous_second_search_never_becomes_matched(self):
        first_search = "<html><body>No exact result</body></html>"
        second_search = """
        <a href="/game/pokemon-japanese-set-a/charmander-168">Charmander #168</a>
        <a href="/game/pokemon-japanese-set-b/charmander-168">Charmander #168</a>
        """
        provider = _provider([_Response(first_search), _Response(second_search)])
        result = provider.lookup(_lot(set_name="Unknown Set"))
        self.assertNotEqual(result.status, "MATCHED")


if __name__ == "__main__":
    unittest.main()
