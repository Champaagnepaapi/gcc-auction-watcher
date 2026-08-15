"""Exact active-ask context for final fixed V4 opportunities.

Active listings are ASK evidence only. They never become SOLD comparables, never
create an opportunity, and never change fair value or max_recommended. The first
production adapter is eBay Buy-It-Now because Cardmarket/TCGplayer data in V4 are
RAW-card markets and must not masquerade as exact graded-slab asks.

Positive active asks are cached briefly by the same strict commercial identity
used by the SOLD external cache. A second GCC listing of the exact same card /
grader / grade / language / variant can therefore reuse one eBay lookup without
mixing identities. Negative/no-match results are deliberately not cached.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus, urljoin

import watcher


@dataclass(frozen=True)
class ActiveAskEvidence:
    source: str
    price: float
    url: str
    title: str
    gap_pct: float
    gcc_is_cheapest: bool


_ORIGINAL_PROCESS = None
_ORIGINAL_NOTIFY = None
_INSTALLED = False
_ACTIVE_ASK_CACHE_STATE_KEY = "v4_exact_active_ask_cache"
_ACTIVE_ASK_CACHE_SCHEMA_VERSION = 1


def _enabled() -> bool:
    return os.getenv("V4_EXACT_ACTIVE_ASK_ENABLED", "true").strip().lower() in {
        "1", "true", "yes"
    }


def _max_cards() -> int:
    try:
        return max(0, int(os.getenv("V4_ACTIVE_ASK_MAX_CARDS_PER_RUN", "2")))
    except ValueError:
        return 2


def _cache_ttl_minutes() -> int:
    try:
        return max(5, int(os.getenv("V4_ACTIVE_ASK_CACHE_TTL_MINUTES", "30")))
    except ValueError:
        return 30


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def _money_eur(text: str) -> Optional[float]:
    match = watcher.EBAY_MONEY_RE.search(text or "")
    if not match:
        return None
    raw = match.group(1).replace("\u00a0", " ").replace("'", "").strip()
    raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _grader_grade_from_text(text: str) -> tuple[str, Optional[float]]:
    blob = text or ""
    aliases = {
        "BECKETT": "BGS",
        "BGS": "BGS",
        "PSA": "PSA",
        "PCA": "PCA",
        "CGC": "CGC",
        "CCC": "CCC",
        "CA": "CA",
        "SGC": "SGC",
        "SGS": "SGS",
        "SFG": "SFG",
        "PG": "PG",
        "SCA": "SCA",
        "TCC": "TCC",
    }
    for token, canonical in aliases.items():
        match = re.search(
            rf"\b{re.escape(token)}\s*(?:GRADE\s*)?(10|[1-9](?:[.,]5)?)\b",
            blob,
            re.I,
        )
        if match:
            try:
                return canonical, float(match.group(1).replace(",", "."))
            except ValueError:
                return canonical, None
    return "", None


def _query_for_lot(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    core = str(identity.get("core") or lot.title or "").strip()
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    grader = (lot.grader or "").strip().upper()
    grade = watcher._target_grade(lot)
    pieces = ["Pokemon", core, reference, grader]
    if grade is not None:
        pieces.append(f"{grade:g}")
    return " ".join(piece for piece in pieces if piece)


def build_ebay_active_url(lot: watcher.Lot) -> str:
    query = quote_plus(_query_for_lot(lot))
    # Buy-It-Now only, sorted by lowest price + shipping. No SOLD/Completed flag.
    return f"{watcher.EBAY_BASE}/sch/i.html?_nkw={query}&LH_BIN=1&_ipg=120&_sop=15"


def _exact_active_ask_candidate(lot: watcher.Lot, title: str, text: str) -> bool:
    score, _reason = watcher.ebay_result_match_score(lot, title)
    if score < 50:
        return False
    grader, grade = _grader_grade_from_text(title + "\n" + text)
    if not grader or grade is None:
        return False
    comparable = watcher.ComparableSale(
        price=1.0,
        source="ebay",
        grader=grader,
        grade=grade,
        context=title + "\n" + text,
        exact_card=True,
        match_score=score,
        identity_provenance="active_ask_identity_gate_only",
    )
    return watcher.external_comparable_is_exact(lot, comparable)


def _evidence_for_lot(
    lot: watcher.Lot,
    *,
    source: str,
    price: float,
    url: str,
    title: str,
) -> ActiveAskEvidence:
    gcc_price = float(lot.current_price or 0.0)
    gcc_is_cheapest = gcc_price > 0 and gcc_price <= price
    gap_pct = ((price - gcc_price) / price * 100.0) if gcc_is_cheapest else 0.0
    return ActiveAskEvidence(
        source=source,
        price=price,
        url=url,
        title=title,
        gap_pct=round(max(0.0, gap_pct), 1),
        gcc_is_cheapest=gcc_is_cheapest,
    )


def scrape_lowest_exact_ebay_ask(page, lot: watcher.Lot) -> Optional[ActiveAskEvidence]:
    if not watcher.commercial_identity_is_sufficient(lot):
        return None
    url = build_ebay_active_url(lot)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=watcher.EBAY_NAV_TIMEOUT)
        page.wait_for_timeout(min(watcher.EBAY_PAGE_WAIT_MS, 1000))
        body = page.locator("body").inner_text(timeout=2500)
    except Exception as exc:
        watcher.log(f"Active ASK eBay indisponible: {type(exc).__name__} | {lot.url}")
        return None
    lower = (body or "").lower()
    if "captcha" in lower or "too many requests" in lower or "access denied" in lower:
        watcher.log(f"Active ASK eBay bloqué/anti-bot | {lot.url}")
        return None

    cards = page.locator("li.s-item")
    raw_count = min(cards.count(), 120)
    best: Optional[tuple[float, str, str]] = None
    for index in range(raw_count):
        card = cards.nth(index)
        try:
            text = card.inner_text(timeout=1000)
        except Exception:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        title = lines[0]
        if title.lower() in {"shop on ebay", "explorer sur ebay"} and len(lines) > 1:
            title = lines[1]
        if not _exact_active_ask_candidate(lot, title, text):
            continue
        price = _money_eur(text)
        if price is None:
            continue
        href = ""
        try:
            href = card.locator("a.s-item__link").first.get_attribute("href") or ""
        except Exception:
            pass
        if not href:
            try:
                href = card.locator("a").first.get_attribute("href") or ""
            except Exception:
                pass
        href = urljoin(watcher.EBAY_BASE, href) if href else url
        if best is None or price < best[0]:
            best = (price, href, title)

    if best is None:
        return None
    ask_price, ask_url, ask_title = best
    return _evidence_for_lot(
        lot,
        source="eBay BIN",
        price=ask_price,
        url=ask_url,
        title=ask_title,
    )


def _active_ask_cache(state: dict) -> dict:
    cache = state.get(_ACTIVE_ASK_CACHE_STATE_KEY)
    if not isinstance(cache, dict) or cache.get("schema_version") != _ACTIVE_ASK_CACHE_SCHEMA_VERSION:
        cache = {"schema_version": _ACTIVE_ASK_CACHE_SCHEMA_VERSION, "entries": {}}
        state[_ACTIVE_ASK_CACHE_STATE_KEY] = cache
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        cache["entries"] = {}
    return cache


def _cached_active_ask(
    state: dict,
    lot: watcher.Lot,
    now: datetime,
) -> Optional[ActiveAskEvidence]:
    if not watcher.commercial_identity_is_sufficient(lot):
        return None
    identity_key = watcher.external_commercial_identity_key(lot)
    cache = state.get(_ACTIVE_ASK_CACHE_STATE_KEY)
    if not isinstance(cache, dict) or cache.get("schema_version") != _ACTIVE_ASK_CACHE_SCHEMA_VERSION:
        return None
    entries = cache.get("entries")
    payload = entries.get(identity_key) if isinstance(entries, dict) else None
    if not isinstance(payload, dict):
        return None
    fetched_at = _parse_datetime(payload.get("fetched_at"))
    if fetched_at is None:
        return None
    if _aware(now) - fetched_at >= timedelta(minutes=_cache_ttl_minutes()):
        return None
    try:
        price = float(payload["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return _evidence_for_lot(
        lot,
        source=str(payload.get("source") or "eBay BIN"),
        price=price,
        url=str(payload.get("url") or ""),
        title=str(payload.get("title") or ""),
    )


def _store_active_ask(
    state: dict,
    lot: watcher.Lot,
    evidence: ActiveAskEvidence,
    now: datetime,
) -> None:
    if not watcher.commercial_identity_is_sufficient(lot) or evidence.price <= 0:
        return
    identity_key = watcher.external_commercial_identity_key(lot)
    cache = _active_ask_cache(state)
    cache["entries"][identity_key] = {
        "fetched_at": _aware(now).isoformat(),
        "source": evidence.source,
        "price": evidence.price,
        "url": evidence.url,
        "title": evidence.title,
    }


def _process_with_active_ask(
    page,
    candidates,
    state,
    budgets,
    diagnostics,
    run_now,
):
    opportunities = _ORIGINAL_PROCESS(
        page, candidates, state, budgets, diagnostics, run_now
    )
    if not _enabled() or _max_cards() <= 0:
        return opportunities

    fixed = [op for op in opportunities if op.lot.source_type == "fixed"]
    fixed.sort(key=lambda op: op.discount_pct, reverse=True)
    network_lookups = 0
    for op in fixed:
        if not watcher.commercial_identity_is_sufficient(op.lot):
            continue

        evidence = _cached_active_ask(state, op.lot, run_now)
        if evidence is not None:
            watcher.log(f"Active ASK exact: cache identité HIT | {op.lot.title}")
        else:
            if network_lookups >= _max_cards():
                continue
            network_lookups += 1
            try:
                evidence = scrape_lowest_exact_ebay_ask(page, op.lot)
            except Exception as exc:
                watcher.log(f"Active ASK exact: erreur isolée {type(exc).__name__} | {op.lot.url}")
                continue
            if evidence is not None:
                _store_active_ask(state, op.lot, evidence, run_now)

        if evidence is not None:
            setattr(op, "exact_active_ask", evidence)
            relation = (
                f"GCC {evidence.gap_pct:.1f}% sous l'ASK eBay exact"
                if evidence.gcc_is_cheapest
                else "eBay a un ASK exact moins cher que GCC"
            )
            watcher.log(f"Active ASK exact: {relation} | {op.lot.title}")
    return opportunities


def _ask_block(op: watcher.Opportunity) -> str:
    evidence = getattr(op, "exact_active_ask", None)
    if not isinstance(evidence, ActiveAskEvidence):
        return ""
    if evidence.gcc_is_cheapest:
        headline = f"Position active : GCC est {evidence.gap_pct:.1f}% sous l'ASK eBay exact"
    else:
        headline = "Position active : un ASK eBay exact est moins cher que GCC"
    return (
        f"{headline}\n"
        f"ASK eBay BIN : {evidence.price:.2f} € — ASK, PAS UNE VENTE\n"
        f"{evidence.url}"
    )


def _inject_before_listing_url(data: object, block: str, listing_url: str) -> object:
    if not block:
        return data
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return data
        rewritten = _inject_before_listing_url(text, block, listing_url)
        return rewritten.encode("utf-8") if isinstance(rewritten, str) else data
    if not isinstance(data, str):
        return data
    marker = listing_url if listing_url and listing_url in data else ""
    if marker:
        return data.replace(marker, block + "\n\n" + marker, 1)
    return data.rstrip() + "\n\n" + block


def _notify_with_active_ask(op: watcher.Opportunity, decision: watcher.NotificationDecision) -> None:
    block = _ask_block(op)
    if not block or not watcher.NTFY_TOPIC:
        return _ORIGINAL_NOTIFY(op, decision)
    original_post = watcher.requests.post

    def post_with_ask(url, *args, **kwargs):
        kwargs["data"] = _inject_before_listing_url(
            kwargs.get("data"), block, op.lot.url
        )
        return original_post(url, *args, **kwargs)

    watcher.requests.post = post_with_ask
    try:
        return _ORIGINAL_NOTIFY(op, decision)
    finally:
        watcher.requests.post = original_post


def install_v4_exact_active_ask_position() -> None:
    global _ORIGINAL_PROCESS, _ORIGINAL_NOTIFY, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_PROCESS = watcher.process_external_market_candidates
    _ORIGINAL_NOTIFY = watcher.notify
    watcher.process_external_market_candidates = _process_with_active_ask
    watcher.notify = _notify_with_active_ask
    _INSTALLED = True
    watcher.log(
        "Exact active ASK: eBay BIN context enabled for final fixed opportunities; "
        "strict identity cache enabled; ASK never treated as SOLD or valuation evidence"
    )
