"""Explicit V5 adapter for the already-existing V4 GCC access path.

Inventory is read from the public on-sale-items endpoint already used by V4.
For an exact identity present in that inventory, one normal authenticated GCC
item page is rendered and its sales-history text is parsed by the shared V4/V5
extractor.  No private endpoint, stealth mode, persistence, or bypass is used.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Callable, Mapping, Sequence

import watcher
from gcc_history_shared import HistoricalParsingDiagnostics

from .market_values.gcc_history.identity import canonicalize_collectible, match_identity
from .market_values.gcc_history.models import CanonicalCollectible, MatchClass


GCC_V4_ACCESS_MECHANISM = (
    "V4 public on-sale-items inventory + normal authenticated Playwright item page rendered history"
)


def _call_without_v4_detail_logs(function, *args, **kwargs):
    """Reuse V4 behavior while keeping the V5 workflow aggregate-only."""

    original_log = watcher.log
    watcher.log = lambda _message: None
    try:
        return function(*args, **kwargs)
    finally:
        watcher.log = original_log


def _lot_identity(lot: watcher.Lot) -> CanonicalCollectible:
    parsed = watcher.extract_card_identity(lot)
    core = parsed.get("core") or lot.title
    set_name = lot.card_set or parsed.get("series") or ""
    card_number = lot.card_number or parsed.get("ref") or ""
    return canonicalize_collectible(
        CanonicalCollectible(
            card_name=core or None,
            set_name=set_name or None,
            card_number=card_number or None,
            language=(lot.language or parsed.get("language") or None),
            variant=lot.variant or None,
            year=lot.year,
            set_family=lot.set_family or set_name or None,
            category="pokemon",
        )
    )


class V4RenderedGCCHistorySource:
    mode = "LIVE"
    live_available = True
    access_mechanism = GCC_V4_ACCESS_MECHANISM

    def __init__(
        self,
        page: object,
        *,
        inventory_fetcher: Callable[..., Sequence[watcher.Lot]] = watcher.collect_fixed_lots_from_api,
        item_inspector: Callable[..., watcher.Lot] = watcher.inspect_item,
        history_extractor: Callable[..., Sequence[watcher.HistoricalSale]] = watcher.extract_historical_sales,
    ) -> None:
        self._page = page
        self._inventory_fetcher = inventory_fetcher
        self._item_inspector = item_inspector
        self._history_extractor = history_extractor
        self._inventory_loaded = False
        self._by_name: dict[str, list[tuple[CanonicalCollectible, watcher.Lot]]] = {}
        self._records: list[Mapping[str, object]] = []
        self._fetch_cache: dict[tuple[object, ...], tuple[Mapping[str, object], ...]] = {}
        self.live_calls = 0
        self.identities_queried = 0
        self.identity_cache_hits = 0
        self.inventory_pages_requested = 0
        self.identity_conflicts = 0
        self.parsing = HistoricalParsingDiagnostics()

    def _load_inventory(self) -> None:
        if self._inventory_loaded:
            return
        self._inventory_loaded = True
        diagnostics = watcher.RunDiagnostics()
        lots = tuple(
            _call_without_v4_detail_logs(self._inventory_fetcher, diagnostics)
        )
        self.inventory_pages_requested = diagnostics.fixed_coverage.pages_requested
        for lot in lots:
            identity = _lot_identity(lot)
            if not identity.minimum_identity_complete or not identity.card_name:
                continue
            self._by_name.setdefault(identity.card_name, []).append((identity, lot))

    def fetch(self, identity: CanonicalCollectible) -> Sequence[Mapping[str, object]]:
        canonical = canonicalize_collectible(identity)
        if canonical.key in self._fetch_cache:
            self.identity_cache_hits += 1
            return self._fetch_cache[canonical.key]
        self.identities_queried += 1
        self._load_inventory()
        matches: list[watcher.Lot] = []
        for candidate_identity, lot in self._by_name.get(canonical.card_name or "", ()):
            result = match_identity(canonical, candidate_identity)
            if result.match_class is MatchClass.EXACT_MATCH:
                matches.append(lot)
            elif result.conflicts:
                self.identity_conflicts += 1
        if not matches:
            self._fetch_cache[canonical.key] = ()
            return ()

        # One exact page per identity is the minimum real mechanism.  Its
        # rendered history already contains the comparable transactions.
        inspected = _call_without_v4_detail_logs(
            self._item_inspector,
            self._page,
            replace(matches[0]),
            log_listing_errors=False,
        )
        self.live_calls += 1
        if inspected.inspection_error:
            self._fetch_cache[canonical.key] = ()
            return ()

        local_parsing = HistoricalParsingDiagnostics()
        sales = _call_without_v4_detail_logs(
            self._history_extractor, inspected, local_parsing
        )
        self.parsing.merge(local_parsing)
        records = tuple(self._record(canonical, sale) for sale in sales)
        self._records.extend(records)
        self._fetch_cache[canonical.key] = records
        return records

    def calibration_records(self) -> Sequence[Mapping[str, object]]:
        return tuple(self._records)

    @staticmethod
    def _record(
        identity: CanonicalCollectible, sale: watcher.HistoricalSale
    ) -> Mapping[str, object]:
        grade: object = sale.grade
        if sale.grade_qualifier:
            grade = sale.grade_qualifier
        return {
            "source": "GCC_RENDERED_V4",
            "status": "sold",
            "completed": True,
            "sale_type": "unknown",
            "card_name": identity.card_name,
            "set_name": identity.set_name,
            "card_number": identity.card_number,
            "language": identity.language,
            "variant": identity.variant,
            "first_edition": identity.first_edition,
            "finish": identity.finish,
            "promo": identity.promo,
            "stamped": identity.stamped,
            "special_print": identity.special_print,
            "year": identity.year,
            "set_family": identity.set_family,
            "category": identity.category,
            "grader": sale.grader or "UNKNOWN",
            "grade": grade,
            "price": str(sale.price),
            "currency": "EUR",
            "sale_date": sale.sold_at.date().isoformat() if sale.sold_at else None,
        }


class V4GCCBrowserSession(AbstractContextManager[V4RenderedGCCHistorySource]):
    """Own a normal Chromium context using the existing GCC storage state."""

    def __init__(self, session_file: str = "gcc_session.json") -> None:
        self.session_file = session_file
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> V4RenderedGCCHistorySource:
        try:
            self._playwright = watcher.sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                locale="fr-FR",
                timezone_id="Europe/Zurich",
                storage_state=self.session_file,
            )
            page = self._context.new_page()
            page.set_default_timeout(watcher.TEXT_TIMEOUT)
            page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)
            return V4RenderedGCCHistorySource(page)
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        return None
