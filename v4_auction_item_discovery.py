from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import watcher


AUCTION_INDEX_URL = f"{watcher.BASE}/filtres/auctions"
PRIMARY_PROTOCOL = "GCC_AUCTION_INDEX_ENDING_FIRST_ITEM_LEVEL"
PRIMARY_SCOPE_STATUS = "COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS"
FALLBACK_SCOPE_STATUS = "LEGACY_LIVE_SALES_FALLBACK"
PRIMARY_END_REASON = "DISCOVERED_AUCTION_HORIZON_CROSSED"
PRIMARY_MODE = "AUCTION_INDEX_ITEM_LEVEL"
FALLBACK_MODE = "LEGACY_LIVE_SALES"
MAX_INDEX_SCROLLS = 24
SCROLL_PIXELS = 2400
SCROLL_WAIT_MS = 180
ORDER_TOLERANCE_MINUTES = 1

_ORIGINAL_COLLECT_LIVE_AUCTION_URLS = watcher.collect_live_auction_urls
_ORIGINAL_COLLECT_LOTS_FROM_LISTING = watcher.collect_lots_from_listing
_ORIGINAL_COVERAGE_STATUS_GETTER = watcher.CoverageAudit.status.fget
_ORIGINAL_LOG_SCAN_COVERAGE = watcher.log_scan_coverage
_INSTALLED = False


@dataclass(frozen=True)
class AuctionListingClassification:
    lot: Optional[watcher.Lot]
    terminal_status: Optional[str]
    timer_minutes: Optional[int]
    timer_text: str


@dataclass
class AuctionIndexDiscoveryResult:
    lots: list[watcher.Lot]
    coverage: watcher.CoverageAudit
    complete: bool
    scope_status: str
    rows_seen: int
    timers_parsed: int
    timerless_eligible: int
    order_verified: bool
    threshold_crossed: bool
    reason: str = ""


def timers_are_nondecreasing(
    values: list[int], tolerance_minutes: int = ORDER_TOLERANCE_MINUTES
) -> bool:
    if len(values) < 2:
        return False
    tolerance = max(0, tolerance_minutes)
    return all(
        later + tolerance >= earlier
        for earlier, later in zip(values, values[1:])
    )


def classify_auction_listing(
    item_url: str,
    anchor_text: str,
    blob: str,
    *,
    max_minutes: int,
) -> AuctionListingClassification:
    minutes, end_text = watcher.parse_listing_countdown_minutes(blob)

    if not watcher.listing_is_pokemon_card(blob):
        return AuctionListingClassification(
            None, watcher.ACCOUNT_EXCLUDED_BY_RULES, minutes, end_text
        )

    price = watcher.parse_money(blob)
    if price is None:
        return AuctionListingClassification(
            None, watcher.ACCOUNT_PARSE_FAILURE, minutes, end_text
        )
    if price < watcher.MIN_PRICE or price > watcher.MAX_PRICE:
        return AuctionListingClassification(
            None, watcher.ACCOUNT_EXCLUDED_BY_RULES, minutes, end_text
        )

    title = watcher.extract_card_title(
        existing_title="",
        listing_text=f"{anchor_text}\n{blob}",
    )
    lot = watcher.Lot(
        url=item_url,
        title=title,
        current_price=price,
        source_type="auction",
        sale_name="GCC auction index",
        listing_text=blob,
        minutes_to_end=minutes,
        end_text=end_text,
    )

    if minutes is not None and minutes > max_minutes:
        return AuctionListingClassification(
            None, watcher.ACCOUNT_EXCLUDED_BY_RULES, minutes, end_text
        )

    # A timerless card in the economic window is retained. The unchanged V4
    # main loop will inspect its item page as the existing conservative fallback.
    return AuctionListingClassification(lot, None, minutes, end_text)


def _canonical_item_url(href: str) -> str:
    raw = (href or "").strip()
    if not watcher.HREF_ITEM_RE.search(raw):
        return ""
    url = f"{watcher.BASE}{raw}" if raw.startswith("/") else raw
    return url.split("?", 1)[0]


def _auction_row_blob(anchor) -> tuple[str, str]:
    try:
        anchor_text = (anchor.inner_text(timeout=500) or "").strip()
    except Exception:
        anchor_text = ""

    candidates = [anchor_text]
    current = anchor
    for _ in range(5):
        try:
            current = current.locator("xpath=..")
            text = (current.inner_text(timeout=500) or "").strip()
            if text:
                candidates.append(text)
        except Exception:
            break

    with_price = [value for value in candidates if "€" in value]
    blob = min(with_price, key=len, default=max(candidates, key=len, default=""))
    return anchor_text, blob


def _try_select_ending_first(page) -> bool:
    selectors = (
        'text="Ventes se terminant en premier"',
        'label:has-text("Ventes se terminant en premier")',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() <= 0:
                continue
            locator.first.click(timeout=1200)
            page.wait_for_timeout(500)
            return True
        except Exception:
            continue
    return False


def _parse_visible_rows(page) -> list[tuple[str, str, str, Optional[int]]]:
    anchors = page.locator('a[href*="/item/"]')
    count = anchors.count()
    rows: list[tuple[str, str, str, Optional[int]]] = []
    seen: set[str] = set()

    for index in range(count):
        anchor = anchors.nth(index)
        try:
            item_url = _canonical_item_url(anchor.get_attribute("href") or "")
        except Exception:
            item_url = ""
        if not item_url or item_url in seen:
            continue
        seen.add(item_url)
        anchor_text, blob = _auction_row_blob(anchor)
        minutes, _ = watcher.parse_listing_countdown_minutes(blob)
        rows.append((item_url, anchor_text, blob, minutes))
    return rows


def discover_auction_index_lots(
    page,
    *,
    max_minutes: Optional[int] = None,
    max_scrolls: int = MAX_INDEX_SCROLLS,
) -> AuctionIndexDiscoveryResult:
    horizon = watcher.MAX_AUCTION_MINUTES if max_minutes is None else max(0, max_minutes)
    coverage = watcher.CoverageAudit("AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS)
    coverage.protocol = PRIMARY_PROTOCOL

    if not watcher._goto_with_coverage_retries(page, AUCTION_INDEX_URL, coverage):
        return AuctionIndexDiscoveryResult(
            [], coverage, False, FALLBACK_SCOPE_STATUS, 0, 0, 0, False, False,
            "auction index navigation failed",
        )

    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass

    clicked_sort = _try_select_ending_first(page)
    watcher.log(
        "Discovery auction item-level: /filtres/auctions | "
        f"tri fin proche {'cliqué' if clicked_sort else 'validé par ordre des timers'}"
    )

    classifications: dict[str, AuctionListingClassification] = {}
    ordered_timer_values: list[int] = []
    ordered_timer_ids: set[str] = set()
    all_row_ids: list[str] = []
    all_row_id_set: set[str] = set()
    pending_terminal: dict[str, str] = {}
    last_height = None
    stable_scrolls = 0
    threshold_confirmations = 0
    threshold_crossed = False
    order_verified = False
    complete = False
    reason = ""

    for _ in range(max(1, max_scrolls)):
        try:
            rows = _parse_visible_rows(page)
        except Exception as error:
            reason = f"auction index rows unreadable: {type(error).__name__}"
            break

        new_ids = 0
        for item_url, anchor_text, blob, minutes in rows:
            if item_url not in all_row_id_set:
                all_row_id_set.add(item_url)
                all_row_ids.append(item_url)
                new_ids += 1

            if item_url not in ordered_timer_ids and minutes is not None:
                ordered_timer_ids.add(item_url)
                ordered_timer_values.append(minutes)

            if item_url in classifications:
                continue
            classification = classify_auction_listing(
                item_url,
                anchor_text,
                blob,
                max_minutes=horizon,
            )
            classifications[item_url] = classification
            if classification.terminal_status is not None:
                pending_terminal[item_url] = classification.terminal_status

        order_verified = timers_are_nondecreasing(ordered_timer_values)
        threshold_crossed = any(value > horizon for value in ordered_timer_values)

        if order_verified and threshold_crossed:
            threshold_confirmations += 1
            if threshold_confirmations >= 2:
                complete = True
                reason = PRIMARY_END_REASON
                break
        else:
            threshold_confirmations = 0

        try:
            height = page.evaluate("document.body.scrollHeight")
        except Exception as error:
            reason = f"auction index scroll height unreadable: {type(error).__name__}"
            break

        if height == last_height and new_ids == 0:
            stable_scrolls += 1
        else:
            stable_scrolls = 0
            last_height = height

        if stable_scrolls >= 2:
            if ordered_timer_values and (
                order_verified or len(ordered_timer_values) == 1
            ):
                complete = True
                reason = watcher.END_SCROLL_STABLE
            else:
                reason = "auction index stable but timer order could not be verified"
            break

        try:
            page.mouse.wheel(0, SCROLL_PIXELS)
            page.wait_for_timeout(SCROLL_WAIT_MS)
        except Exception as error:
            reason = f"auction index scroll failed: {type(error).__name__}"
            break

    if not complete and not reason:
        reason = f"auction index safety limit {max_scrolls} scrolls reached"

    if not complete:
        coverage.mark_incomplete(reason or "auction index discovery incomplete")
        return AuctionIndexDiscoveryResult(
            [],
            coverage,
            False,
            FALLBACK_SCOPE_STATUS,
            len(all_row_ids),
            len(ordered_timer_values),
            sum(
                classification.lot is not None
                and classification.timer_minutes is None
                for classification in classifications.values()
            ),
            order_verified,
            threshold_crossed,
            reason,
        )

    coverage.record_page_success(
        AUCTION_INDEX_URL,
        all_row_ids,
        page_size=len(all_row_ids),
    )
    for item_url, status in pending_terminal.items():
        coverage.record_terminal(item_url, status)
    coverage.pagination_end_reason = reason
    setattr(coverage, "_auction_scope_complete", True)
    setattr(coverage, "auction_scope_status", PRIMARY_SCOPE_STATUS)

    lots = [
        classification.lot
        for classification in classifications.values()
        if classification.lot is not None
    ]
    return AuctionIndexDiscoveryResult(
        lots,
        coverage,
        True,
        PRIMARY_SCOPE_STATUS,
        len(all_row_ids),
        len(ordered_timer_values),
        sum(lot.minutes_to_end is None for lot in lots),
        order_verified or len(ordered_timer_values) == 1,
        threshold_crossed,
        reason,
    )


def _attach_primary_result(
    run_diagnostics: Optional[watcher.RunDiagnostics],
    result: AuctionIndexDiscoveryResult,
) -> None:
    if run_diagnostics is None:
        return
    run_diagnostics.auction_coverage = result.coverage
    run_diagnostics.live_auction_urls.clear()
    run_diagnostics.live_auction_urls.add(AUCTION_INDEX_URL)
    setattr(run_diagnostics, "auction_discovery_mode", PRIMARY_MODE)
    setattr(run_diagnostics, "auction_discovery_scope_status", result.scope_status)
    setattr(run_diagnostics, "auction_discovered_rows", result.rows_seen)
    setattr(run_diagnostics, "auction_timer_parsed", result.timers_parsed)
    setattr(run_diagnostics, "auction_timerless_eligible", result.timerless_eligible)
    setattr(run_diagnostics, "auction_fallback_used", False)


def _legacy_fallback(
    page,
    run_diagnostics: Optional[watcher.RunDiagnostics],
) -> list[watcher.Lot]:
    watcher.log("Discovery auction item-level non prouvée -> fallback legacy ventes live")
    if run_diagnostics is not None:
        run_diagnostics.auction_coverage = watcher.CoverageAudit(
            "AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS
        )
        run_diagnostics.live_auction_urls.clear()

    sales = _ORIGINAL_COLLECT_LIVE_AUCTION_URLS(page, run_diagnostics)
    if run_diagnostics is not None:
        run_diagnostics.record_live_sales(sales)
        setattr(run_diagnostics, "auction_discovery_mode", FALLBACK_MODE)
        setattr(
            run_diagnostics,
            "auction_discovery_scope_status",
            FALLBACK_SCOPE_STATUS,
        )
        setattr(run_diagnostics, "auction_discovered_rows", 0)
        setattr(run_diagnostics, "auction_timer_parsed", 0)
        setattr(run_diagnostics, "auction_timerless_eligible", 0)
        setattr(run_diagnostics, "auction_fallback_used", True)

    watcher.log(f"Fallback legacy: {len(sales)} vente(s) live détectée(s)")
    lots: dict[str, watcher.Lot] = {}
    for sale in sales:
        try:
            for lot in _ORIGINAL_COLLECT_LOTS_FROM_LISTING(
                page, sale, "auction", run_diagnostics
            ):
                lots.setdefault(lot.url, lot)
        except Exception as error:
            watcher.log(f"Fallback legacy erreur {type(error).__name__}: {sale}")
            if run_diagnostics is not None:
                run_diagnostics.auction_coverage.record_page_failure(
                    f"legacy fallback sale exception: {type(error).__name__}"
                )
    return list(lots.values())


def patched_collect_live_auction_urls(
    page,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
) -> list[str]:
    watcher.log(
        "Source auction primaire: /filtres/auctions, lots individuels, "
        "tri fin la plus proche"
    )
    return [AUCTION_INDEX_URL]


def patched_collect_lots_from_listing(
    page,
    url: str,
    source_type: str,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
    **kwargs,
) -> list[watcher.Lot]:
    if source_type != "auction" or url != AUCTION_INDEX_URL:
        return _ORIGINAL_COLLECT_LOTS_FROM_LISTING(
            page, url, source_type, run_diagnostics, **kwargs
        )

    result = discover_auction_index_lots(page)
    if result.complete:
        _attach_primary_result(run_diagnostics, result)
        watcher.log(
            f"Auction item-level: {result.rows_seen} lot(s) observé(s), "
            f"{result.timers_parsed} timer(s) lisible(s), "
            f"{len(result.lots)} candidat(s) Pokémon/carte/prix dans l'horizon"
        )
        watcher.log(f"Auction scope status: {PRIMARY_SCOPE_STATUS}")
        return result.lots

    watcher.log(f"Auction item-level incomplet: {result.reason}")
    return _legacy_fallback(page, run_diagnostics)


def patched_coverage_status(coverage: watcher.CoverageAudit) -> str:
    if (
        coverage.protocol == PRIMARY_PROTOCOL
        and getattr(coverage, "_auction_scope_complete", False)
    ):
        if coverage.incomplete_reasons or coverage.pages_failed:
            return watcher.COVERAGE_INCOMPLETE
        return watcher.COVERAGE_COMPLETE
    return _ORIGINAL_COVERAGE_STATUS_GETTER(coverage)


def patched_log_scan_coverage(diagnostics: watcher.RunDiagnostics) -> None:
    _ORIGINAL_LOG_SCAN_COVERAGE(diagnostics)
    mode = getattr(diagnostics, "auction_discovery_mode", "UNKNOWN")
    scope = getattr(diagnostics, "auction_discovery_scope_status", "UNKNOWN")
    rows = getattr(diagnostics, "auction_discovered_rows", 0)
    timer_parsed = getattr(diagnostics, "auction_timer_parsed", 0)
    timerless = getattr(diagnostics, "auction_timerless_eligible", 0)
    fallback = bool(getattr(diagnostics, "auction_fallback_used", False))

    watcher.log(f"auction discovery mode: {mode}")
    watcher.log(f"auction discovery scope status: {scope}")
    watcher.log(f"auction discovered rows: {rows}")
    watcher.log(f"auction timers parsed: {timer_parsed}")
    watcher.log(f"auction timerless eligible: {timerless}")
    watcher.log(f"auction legacy fallback used: {str(fallback).lower()}")

    watcher.write_github_output("auction_discovery_mode", mode)
    watcher.write_github_output("auction_scope_status", scope)
    watcher.write_github_output("auction_discovered_rows", rows)
    watcher.write_github_output("auction_timer_parsed", timer_parsed)
    watcher.write_github_output(
        "auction_ending_soon", diagnostics.auction_candidates_ending_soon
    )
    watcher.write_github_output("auction_fallback_used", str(fallback).lower())


def install_v4_auction_item_discovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    watcher.collect_live_auction_urls = patched_collect_live_auction_urls
    watcher.collect_lots_from_listing = patched_collect_lots_from_listing
    watcher.CoverageAudit.status = property(patched_coverage_status)
    watcher.log_scan_coverage = patched_log_scan_coverage
    _INSTALLED = True
