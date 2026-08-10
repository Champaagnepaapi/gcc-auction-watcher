"""Explicit V5 adapter for the already-existing V4 GCC access path.

The public on-sale-items inventory remains a fast path. When no safe
representative is currently on sale, V5 falls back to GCC's normal public
graded-card Explore UI, enables completed sales, searches the collectible,
opens a small bounded set of public item pages, and applies the same
exact/unique-strong identity policy before reading rendered sales history.

No private endpoint, stealth mode, persistence, access-control bypass, or
CAPTCHA circumvention is used.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence
from urllib.parse import urljoin

import watcher
from gcc_history_shared import HistoricalParsingDiagnostics

from .market_values.gcc_history.identity import canonicalize_collectible, match_identity
from .market_values.gcc_history.models import CanonicalCollectible, MatchClass


GCC_EXPLORE_URL = "https://gradedcardcenter.com/en/filters/explore/cards-graded"
GCC_CATALOG_CANDIDATE_LIMIT = 8
GCC_V4_ACCESS_MECHANISM = (
    "V4 public on-sale-items fast path + GCC public graded-card Explore/Completed Sales local-search fallback + normal authenticated Playwright item page rendered history"
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


@dataclass(frozen=True)
class GCCCatalogResolution:
    lot: watcher.Lot | None = None
    match_class: MatchClass | None = None
    ambiguous: bool = False


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
        catalog_resolver: Callable[[CanonicalCollectible], GCCCatalogResolution] | None = None,
    ) -> None:
        self._page = page
        self._inventory_fetcher = inventory_fetcher
        self._item_inspector = item_inspector
        self._history_extractor = history_extractor
        self._catalog_resolver = catalog_resolver or self._resolve_from_public_explore
        self._inventory_loaded = False
        self._by_name: dict[str, list[tuple[CanonicalCollectible, watcher.Lot]]] = {}
        self._records: list[Mapping[str, object]] = []
        self._fetch_cache: dict[tuple[object, ...], tuple[Mapping[str, object], ...]] = {}
        self.live_calls = 0
        self.identities_queried = 0
        self.identity_cache_hits = 0
        self.inventory_pages_requested = 0
        self.identity_conflicts = 0
        self.representative_exact = 0
        self.representative_strong = 0
        self.representative_ambiguous = 0
        self.no_representative = 0
        self.catalog_searches = 0
        self.catalog_candidate_pages_opened = 0
        self.catalog_completed_sales_enabled = 0
        self.catalog_search_failures = 0
        self.parsing = HistoricalParsingDiagnostics()

    def _load_inventory(self) -> None:
        if self._inventory_loaded:
            return
        self._inventory_loaded = True
        diagnostics = watcher.RunDiagnostics()
        lots = tuple(
            _call_without_v4_detail_logs(
                self._inventory_fetcher,
                diagnostics,
                min_price=0.0,
                max_price=None,
            )
        )
        self.inventory_pages_requested = diagnostics.fixed_coverage.pages_requested
        for lot in lots:
            identity = _lot_identity(lot)
            if not identity.card_name or not (identity.card_number or identity.set_name):
                continue
            self._by_name.setdefault(identity.card_name, []).append((identity, lot))

    @staticmethod
    def _first_visible(locator):
        try:
            count = locator.count()
        except Exception:
            return None
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None

    def _enable_completed_sales(self) -> bool:
        for label in ("Completed Sales", "Ventes réussies", "Ventes réussies"):
            try:
                labelled = self._page.get_by_label(label, exact=True)
                control = self._first_visible(labelled)
                if control is not None:
                    try:
                        checked = control.is_checked()
                    except Exception:
                        checked = False
                    if not checked:
                        try:
                            control.check()
                        except Exception:
                            control.click()
                    self._page.wait_for_timeout(500)
                    self.catalog_completed_sales_enabled += 1
                    return True
            except Exception:
                pass

        for label in ("Completed Sales", "Ventes réussies", "Ventes réussies"):
            try:
                text = self._page.get_by_text(label, exact=True)
                control = self._first_visible(text)
                if control is not None:
                    control.click()
                    self._page.wait_for_timeout(500)
                    self.catalog_completed_sales_enabled += 1
                    return True
            except Exception:
                pass
        return False

    def _catalog_search_box(self):
        # GCC exposes a site-wide search and a separate local Search control on
        # the graded-card Explore view.  Never fall back to a generic
        # input[type=search], because that can select the global header search
        # while leaving the Explore result list unchanged.
        selectors = (
            'input[placeholder="Search"]',
            'input[placeholder="Rechercher"]',
            'input[placeholder="Recherche"]',
        )
        for selector in selectors:
            try:
                control = self._first_visible(self._page.locator(selector))
                if control is not None:
                    return control
            except Exception:
                continue
        return None

    def _catalog_item_urls(self) -> tuple[str, ...]:
        try:
            links = self._page.locator('a[href*="/item/"]')
            count = min(links.count(), GCC_CATALOG_CANDIDATE_LIMIT * 2)
        except Exception:
            return ()
        urls: list[str] = []
        for index in range(count):
            try:
                href = links.nth(index).get_attribute("href")
            except Exception:
                continue
            if not href or "/item/" not in href:
                continue
            url = urljoin("https://gradedcardcenter.com", href)
            if url not in urls:
                urls.append(url)
            if len(urls) >= GCC_CATALOG_CANDIDATE_LIMIT:
                break
        return tuple(urls)

    @staticmethod
    def _catalog_queries(canonical: CanonicalCollectible) -> tuple[str, ...]:
        name = canonical.card_name or ""
        number = canonical.card_number or ""
        set_name = canonical.set_name or ""
        values = []
        for query in (
            " ".join(part for part in (name, number) if part),
            number,
            " ".join(part for part in (name, set_name) if part),
        ):
            clean = " ".join(query.split())
            if clean and clean not in values:
                values.append(clean)
        return tuple(values[:3])

    def _wait_for_local_catalogue_change(
        self, before_urls: tuple[str, ...]
    ) -> tuple[str, ...]:
        urls = before_urls
        for _ in range(10):
            self._page.wait_for_timeout(250)
            urls = self._catalog_item_urls()
            if urls != before_urls:
                return urls
        return urls

    def _resolve_from_public_explore(
        self, canonical: CanonicalCollectible
    ) -> GCCCatalogResolution:
        """Resolve a representative through GCC's normal public Explore UI.

        The UI visibly exposes a Completed Sales filter and a local Search field
        on the graded-card Explore view.  Every candidate item page is then
        verified with the strict V5 identity matcher before acceptance.
        """

        exact: watcher.Lot | None = None
        strong: dict[tuple[object, ...], watcher.Lot] = {}
        ambiguous_seen = False
        inspected_urls: set[str] = set()

        for query in self._catalog_queries(canonical):
            try:
                self._page.goto(
                    GCC_EXPLORE_URL,
                    wait_until="domcontentloaded",
                    timeout=watcher.NAV_TIMEOUT,
                )
                self._page.wait_for_timeout(500)
                self._enable_completed_sales()
                search_box = self._catalog_search_box()
                if search_box is None:
                    self.catalog_search_failures += 1
                    continue

                before_urls = self._catalog_item_urls()
                search_box.fill(query)
                self.catalog_searches += 1
                urls = self._wait_for_local_catalogue_change(before_urls)

                # Some form implementations only commit the local filter on
                # Enter.  Retry once, but only after selecting the explicit
                # local Search field above.
                if urls == before_urls:
                    try:
                        search_box.press("Enter")
                        urls = self._wait_for_local_catalogue_change(before_urls)
                    except Exception:
                        pass

                # A search that leaves exactly the same first candidates is not
                # treated as valid evidence; otherwise we would repeatedly open
                # unrelated catalogue entries and count their identity conflicts.
                if urls == before_urls:
                    self.catalog_search_failures += 1
                    continue
            except Exception:
                self.catalog_search_failures += 1
                continue

            for url in urls:
                if url in inspected_urls:
                    continue
                inspected_urls.add(url)
                candidate = watcher.Lot(
                    url=url,
                    title="",
                    current_price=None,
                    source_type="catalog",
                )
                inspected = _call_without_v4_detail_logs(
                    self._item_inspector,
                    self._page,
                    candidate,
                    log_listing_errors=False,
                )
                self.catalog_candidate_pages_opened += 1
                if inspected.inspection_error:
                    continue
                candidate_identity = _lot_identity(inspected)
                result = match_identity(canonical, candidate_identity)
                if result.match_class is MatchClass.EXACT_MATCH:
                    exact = inspected
                    break
                if result.match_class is MatchClass.STRONG_MATCH:
                    strong.setdefault(candidate_identity.key, inspected)
                elif result.match_class is MatchClass.AMBIGUOUS:
                    ambiguous_seen = True
                elif result.conflicts:
                    self.identity_conflicts += 1
            if exact is not None:
                break

        if exact is not None:
            return GCCCatalogResolution(exact, MatchClass.EXACT_MATCH, False)
        if len(strong) == 1:
            return GCCCatalogResolution(
                next(iter(strong.values())), MatchClass.STRONG_MATCH, False
            )
        if len(strong) > 1 or ambiguous_seen:
            return GCCCatalogResolution(None, None, True)
        return GCCCatalogResolution()

    def fetch(self, identity: CanonicalCollectible) -> Sequence[Mapping[str, object]]:
        canonical = canonicalize_collectible(identity)
        if canonical.key in self._fetch_cache:
            self.identity_cache_hits += 1
            return self._fetch_cache[canonical.key]
        self.identities_queried += 1
        self._load_inventory()

        exact_matches: list[watcher.Lot] = []
        strong_matches: dict[tuple[object, ...], watcher.Lot] = {}
        inventory_ambiguous = False
        for candidate_identity, lot in self._by_name.get(canonical.card_name or "", ()):
            result = match_identity(canonical, candidate_identity)
            if result.match_class is MatchClass.EXACT_MATCH:
                exact_matches.append(lot)
            elif result.match_class is MatchClass.STRONG_MATCH:
                strong_matches.setdefault(candidate_identity.key, lot)
            elif result.match_class is MatchClass.AMBIGUOUS:
                inventory_ambiguous = True
            elif result.conflicts:
                self.identity_conflicts += 1

        selected: watcher.Lot | None = None
        selected_inspected = False
        selected_class: MatchClass | None = None
        if exact_matches:
            selected = exact_matches[0]
            selected_class = MatchClass.EXACT_MATCH
        elif len(strong_matches) == 1:
            selected = next(iter(strong_matches.values()))
            selected_class = MatchClass.STRONG_MATCH
        else:
            resolution = self._catalog_resolver(canonical)
            selected = resolution.lot
            selected_class = resolution.match_class
            selected_inspected = selected is not None and bool(selected.body)
            if selected is None:
                if resolution.ambiguous or len(strong_matches) > 1 or inventory_ambiguous:
                    self.representative_ambiguous += 1
                else:
                    self.no_representative += 1
                self._fetch_cache[canonical.key] = ()
                return ()

        if selected_class is MatchClass.EXACT_MATCH:
            self.representative_exact += 1
        elif selected_class is MatchClass.STRONG_MATCH:
            self.representative_strong += 1
        else:
            self.no_representative += 1
            self._fetch_cache[canonical.key] = ()
            return ()

        if selected_inspected:
            inspected = selected
        else:
            inspected = _call_without_v4_detail_logs(
                self._item_inspector,
                self._page,
                replace(selected),
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
