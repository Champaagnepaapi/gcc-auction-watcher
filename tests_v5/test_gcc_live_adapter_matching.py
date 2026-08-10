import unittest
from dataclasses import replace

import watcher
from v5.gcc_live_adapter import (
    GCCCatalogResolution,
    V4RenderedGCCHistorySource,
)
from v5.market_values.gcc_history.models import CanonicalCollectible, MatchClass


def _lot(*, set_name="", year=None, number="4/102", body=""):
    return watcher.Lot(
        url=f"https://gradedcardcenter.com/item/{set_name or 'missing'}-{year or 'none'}-{number.replace('/', '-')}",
        title="PSA 10 Charizard",
        current_price=500.0,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_set=set_name,
        card_number=number,
        language="English",
        year=year,
        set_family=set_name,
        body=body,
    )


def _target(*, year=None):
    return CanonicalCollectible(
        card_name="charizard",
        set_name="base set",
        card_number="4/102",
        language="english",
        year=year,
        set_family="base set",
        category="pokemon",
    )


class GCCRepresentativeSelectionTests(unittest.TestCase):
    def _source(self, lots, catalog_resolver=None):
        opened = []
        bounds = []

        def inventory(diagnostics, **kwargs):
            diagnostics.fixed_coverage.pages_requested = 3
            bounds.append(kwargs)
            return tuple(lots)

        def inspect(_page, value, *, log_listing_errors=True):
            self.assertFalse(log_listing_errors)
            opened.append(value.url)
            return replace(value, body="Historique des ventes", inspection_error="")

        source = V4RenderedGCCHistorySource(
            object(),
            inventory_fetcher=inventory,
            item_inspector=inspect,
            history_extractor=lambda *_args, **_kwargs: (),
            catalog_resolver=catalog_resolver,
        )
        return source, opened, bounds

    def test_unique_strong_match_is_accepted(self):
        source, opened, bounds = self._source([_lot(set_name="", year=1999)])
        source.fetch(_target(year=1999))
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(len(opened), 1)
        self.assertEqual(source.representative_exact, 0)
        self.assertEqual(source.representative_strong, 1)
        self.assertEqual(source.representative_ambiguous, 0)
        self.assertEqual(source.no_representative, 0)
        self.assertEqual(bounds, [{"min_price": 0.0, "max_price": None}])

    def test_multiple_distinct_strong_matches_are_rejected_as_ambiguous(self):
        source, opened, _bounds = self._source(
            [_lot(set_name="", year=1999), _lot(set_name="", year=2000)],
            catalog_resolver=lambda _identity: GCCCatalogResolution(),
        )
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 0)
        self.assertEqual(opened, [])
        self.assertEqual(source.representative_strong, 0)
        self.assertEqual(source.representative_ambiguous, 1)
        self.assertEqual(source.no_representative, 0)

    def test_conflict_never_opens_page_and_counts_no_representative(self):
        source, opened, _bounds = self._source(
            [_lot(set_name="Base Set", number="5/102")],
            catalog_resolver=lambda _identity: GCCCatalogResolution(),
        )
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 0)
        self.assertEqual(opened, [])
        self.assertGreaterEqual(source.identity_conflicts, 1)
        self.assertEqual(source.no_representative, 1)

    def test_exact_match_has_priority(self):
        source, opened, _bounds = self._source(
            [_lot(set_name="Base Set", year=None), _lot(set_name="", year=1999)]
        )
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(len(opened), 1)
        self.assertEqual(source.representative_exact, 1)
        self.assertEqual(source.representative_strong, 0)

    def test_public_catalogue_exact_fallback_can_rescue_missing_on_sale_rep(self):
        resolved = _lot(
            set_name="Base Set",
            year=None,
            body="Historique des ventes\nPSA 10 Charizard\n100 €",
        )
        calls = []

        def resolver(identity):
            calls.append(identity.key)
            return GCCCatalogResolution(resolved, MatchClass.EXACT_MATCH, False)

        source, opened, _bounds = self._source([], catalog_resolver=resolver)
        source.fetch(_target(year=None))
        self.assertEqual(len(calls), 1)
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(source.representative_exact, 1)
        self.assertEqual(source.no_representative, 0)
        # The catalogue fallback already inspected the public item page.
        self.assertEqual(opened, [])

    def test_public_catalogue_unique_strong_fallback_is_accepted(self):
        resolved = _lot(
            set_name="",
            year=1999,
            body="Historique des ventes\nPSA 10 Charizard\n100 €",
        )
        source, _opened, _bounds = self._source(
            [],
            catalog_resolver=lambda _identity: GCCCatalogResolution(
                resolved, MatchClass.STRONG_MATCH, False
            ),
        )
        source.fetch(_target(year=1999))
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(source.representative_strong, 1)
        self.assertEqual(source.representative_ambiguous, 0)

    def test_public_catalogue_ambiguity_is_never_opened_as_market_history(self):
        source, opened, _bounds = self._source(
            [],
            catalog_resolver=lambda _identity: GCCCatalogResolution(
                None, None, True
            ),
        )
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 0)
        self.assertEqual(opened, [])
        self.assertEqual(source.representative_ambiguous, 1)
        self.assertEqual(source.no_representative, 0)

    def test_inventory_conflict_can_be_rescued_only_by_safe_catalogue_exact(self):
        resolved = _lot(
            set_name="Base Set",
            year=None,
            body="Historique des ventes\nPSA 10 Charizard\n100 €",
        )
        source, opened, _bounds = self._source(
            [_lot(set_name="Base Set", number="5/102")],
            catalog_resolver=lambda _identity: GCCCatalogResolution(
                resolved, MatchClass.EXACT_MATCH, False
            ),
        )
        source.fetch(_target(year=None))
        self.assertGreaterEqual(source.identity_conflicts, 1)
        self.assertEqual(source.representative_exact, 1)
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
