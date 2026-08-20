from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

import japan_edge_hunter as japan
import v4_global_comc_hardening as comc_v4
import v4_global_live_shadow as legacy
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_retrieval_hardening as retrieval_v1
import v4_global_retrieval_hardening_v2 as retrieval_v2
import v4_global_retrieval_hardening_v3 as retrieval_v3
from v4_global_comc_hardening_v2 import COMC_PSA10_INDEX
from v4_global_marketplace_discovery import (
    MarketplaceListing,
    cardova_inventory,
    gcc_listing_from_row,
    listing_from_observation,
)
from v4_market_comc_bridge import comc_fixed_offer
from v4_market_fanatics_bridge import fanatics_fixed_offer
from v4_market_magi_bridge import magi_fixed_ask_to_observation


FANATICS_BROWSE = "https://www.fanaticscollect.com/marketplace?type=FIXED"
MAGI_BROAD_QUERY = "PSA10 ポケモン"


@dataclass(frozen=True)
class ScanStatus:
    market: str
    status: str
    pages: int = 0
    candidates: int = 0
    exact: int = 0
    detail: str = ""
    complete: bool = False


def _rows(payload: object) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    value = payload.get("results")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def _has_next(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    info = payload.get("info")
    return bool(info.get("nextPage")) if isinstance(info, Mapping) else False


def scan_gcc_inventory(
    *,
    observed_at: datetime,
    max_pages_each: int = 100,
    session: Optional[requests.Session] = None,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    own = session is None
    client = session or requests.Session()
    output: list[MarketplaceListing] = []
    pages = candidates = 0
    complete = True
    try:
        for selling in ("FIXED_PRICE", "AUCTION"):
            exhausted = False
            for page_no in range(1, max(1, int(max_pages_each)) + 1):
                response = client.get(
                    legacy.GCC_API_URL,
                    params={
                        "sellingTypeGroup": selling,
                        "status": "ON_SALE",
                        "sortType": "ENDING_SOON" if selling == "AUCTION" else "MOST_RECENT",
                        "page": page_no,
                        "limit": 100,
                        "includeCounts": "true" if page_no == 1 else "false",
                    },
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
                rows = _rows(payload)
                pages += 1
                if not rows:
                    exhausted = True
                    break
                candidates += len(rows)
                for row in rows:
                    # The GCC response does not reliably echo sellingTypeGroup on
                    # each row. Preserve the authoritative request context so an
                    # AUCTION row can never fall through to the FIXED_ASK default.
                    typed_row = dict(row)
                    typed_row["sellingTypeGroup"] = selling
                    listing = gcc_listing_from_row(typed_row, observed_at=observed_at)
                    if listing is not None:
                        output.append(listing)
                if not _has_next(payload):
                    exhausted = True
                    break
            if not exhausted:
                complete = False
    except Exception as error:
        return output, ScanStatus(
            "gcc", "ERROR", pages, candidates, len(output), type(error).__name__, False
        )
    finally:
        if own:
            client.close()
    return output, ScanStatus(
        "gcc", "OK", pages, candidates, len(output), "public on-sale inventory", complete
    )


def load_cardova_files(
    *,
    observed_at: datetime,
    fixed_path: Optional[Path],
    auction_path: Optional[Path],
) -> tuple[list[MarketplaceListing], ScanStatus]:
    if fixed_path is None and auction_path is None:
        return [], ScanStatus(
            "cardova",
            "AUTH_SESSION_INPUT_REQUIRED",
            detail="sanitized fixed/auction JSON required; no session secret stored",
            complete=False,
        )
    fixed = auction = None
    try:
        if fixed_path is not None:
            fixed = json.loads(fixed_path.read_text(encoding="utf-8"))
        if auction_path is not None:
            auction = json.loads(auction_path.read_text(encoding="utf-8"))
    except Exception as error:
        return [], ScanStatus("cardova", "ERROR", detail=type(error).__name__, complete=False)
    if fixed is not None and not isinstance(fixed, Mapping):
        return [], ScanStatus("cardova", "ERROR", detail="fixed payload malformed", complete=False)
    if auction is not None and not isinstance(auction, Mapping):
        return [], ScanStatus("cardova", "ERROR", detail="auction payload malformed", complete=False)
    rows = cardova_inventory(fixed_payload=fixed, auction_payload=auction, observed_at=observed_at)
    return rows, ScanStatus(
        "cardova", "OK", candidates=len(rows), exact=len(rows), detail="sanitized structured inventory", complete=True
    )


def build_identity_catalog(
    *,
    observed_at: datetime,
    gcc_sold_pages: int = 30,
) -> tuple[list[legacy.Seed], dict[str, float], str]:
    """Use all safe GCC history identities as a retrieval catalog, never as scan targets."""
    diag = japan.Diagnostics()
    try:
        sales = japan.fetch_gcc(max_pages=max(1, gcc_sold_pages), diag=diag)
    except Exception as error:
        return [], {}, f"ERROR:{type(error).__name__}"
    seeds = legacy.build_seed_panel(sales, observed_at=observed_at, max_identities=max(1, len(sales)))
    fair = {seed.identity.strict_key: seed.fair_value.central_eur for seed in seeds}
    return seeds, fair, f"OK:{len(seeds)}"


def _fanatics_urls(page: Any, *, scroll_rounds: int) -> tuple[list[str], int]:
    page.goto(FANATICS_BROWSE, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(1200)
    found: list[str] = []
    rounds = 0
    stable = 0
    previous = 0
    for _ in range(max(1, int(scroll_rounds))):
        rounds += 1
        try:
            hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean)")
        except Exception:
            hrefs = []
        try:
            html = page.content()
        except Exception:
            html = ""
        for href in hrefs if isinstance(hrefs, list) else []:
            canonical = retrieval_v2._canonical_fanatics_url(str(href))
            if canonical and canonical not in found:
                found.append(canonical)
        for match in retrieval_v2.FANATICS_ROUTE_RE.finditer(html):
            canonical = retrieval_v2._canonical_fanatics_url(match.group(0))
            if canonical and canonical not in found:
                found.append(canonical)
        if len(found) == previous:
            stable += 1
        else:
            stable = 0
        previous = len(found)
        if stable >= 2:
            break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(850)
    return found, rounds


def _fanatics_candidate_seeds(text: str, seeds: Sequence[legacy.Seed]) -> list[legacy.Seed]:
    normalized = str(text or "")
    output: list[legacy.Seed] = []
    for seed in seeds:
        local = retrieval_v1.target_local_id(seed.source_identity)
        if local is None:
            continue
        if not re.search(rf"#0*{re.escape(local)}(?:\D|$)", normalized, re.I):
            continue
        output.append(seed)
    return output


def scan_fanatics_inventory(
    page: Any,
    seeds: Sequence[legacy.Seed],
    *,
    observed_at: datetime,
    max_detail_pages: int = 200,
    scroll_rounds: int = 20,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    try:
        urls, rounds = _fanatics_urls(page, scroll_rounds=scroll_rounds)
    except Exception as error:
        return [], ScanStatus("fanatics", "ERROR", detail=type(error).__name__, complete=False)
    output: list[MarketplaceListing] = []
    for url in urls[: max(1, int(max_detail_pages))]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(500)
            title = page.locator("h1").first.inner_text(timeout=4000).strip()
            body = page.locator("body").inner_text(timeout=5000)
        except Exception:
            continue
        upper = body.upper()
        if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
            continue
        before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.I)[0]
        price = legacy._price_from_usd_text(before_guide)
        if price is None:
            continue
        matches: list[legacy.Seed] = []
        proof_text = f"{title}\n{before_guide}"
        for seed in _fanatics_candidate_seeds(proof_text, seeds):
            ok, _reason = retrieval_v3.fanatics_title_identity_proof_v3(proof_text, seed.source_identity)
            if ok:
                matches.append(seed)
        if len(matches) != 1:
            continue
        seed = matches[0]
        observation = fanatics_fixed_offer(
            identity=seed.identity,
            price_usd=price,
            observed_at=observed_at,
            source_id=url,
            identity_proven=True,
            buyer_fee_rate=0.0,
            note="Fanatics marketplace-first Buy Now ASK; exact known coordinate; TCGdex revalidation required downstream",
        )
        output.append(listing_from_observation(observation, source_url=url, title=title))
    complete = len(urls) <= max(1, int(max_detail_pages))
    return output, ScanStatus(
        "fanatics",
        "OK",
        pages=rounds,
        candidates=len(urls),
        exact=len(output),
        detail="direct marketplace browse; no identity-targeted searches",
        complete=complete,
    )


def _magi_broad_rows(page: Any) -> list[japan.Ask]:
    provider = next(provider for provider in japan.PROVIDERS if provider.code == "magi")
    url = provider.search_url.format(q=quote(MAGI_BROAD_QUERY, safe=""))
    page.goto(url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(900)
    rows = page.evaluate(
        r"""() => Array.from(document.querySelectorAll('a[href]')).slice(0,1800).map(a=>{let n=a,t=(a.innerText||a.textContent||'').trim();for(let i=0;i<6&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(/[¥￥]|\d[\d,]*\s*円/.test(x)){t=x;break;}}return {href:a.href||'',anchor:(a.innerText||'').trim(),text:t};})"""
    )
    output: list[japan.Ask] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        item_url = japan.canonical_url(provider, str(row.get("href") or ""))
        snippet = str(row.get("text") or "")
        if not item_url or item_url in seen or japan.has_any(snippet, japan.AUCTION):
            continue
        price = japan.parse_yen(snippet)
        if price is None:
            continue
        title = str(row.get("anchor") or "").strip() or next((x.strip() for x in snippet.splitlines() if x.strip()), "")
        output.append(japan.Ask("magi", item_url, title[:500], price, snippet[:4000]))
        seen.add(item_url)
    return output


def scan_magi_inventory(
    page: Any,
    seeds: Sequence[legacy.Seed],
    *,
    observed_at: datetime,
    max_detail_pages: int = 200,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    try:
        asks = _magi_broad_rows(page)
    except Exception as error:
        return [], ScanStatus("magi", "ERROR", detail=type(error).__name__, complete=False)
    output: list[MarketplaceListing] = []
    for ask in asks[: max(1, int(max_detail_pages))]:
        try:
            detailed = retrieval_v1.magi_detail_only(page, ask)
        except Exception:
            detailed = ask
        available, _reason = magi_hardening.magi_listing_availability_check(page, detailed)
        if not available:
            continue
        observed_numbers = japan.number_tokens(japan.current_text(f"{detailed.title}\n{detailed.text}"))
        matches: list[legacy.Seed] = []
        for seed in seeds:
            if japan.number(seed.source_identity.number) not in observed_numbers:
                continue
            ok, _proof = japan.identity_check(detailed, seed.source_identity)
            if ok:
                matches.append(seed)
        if len(matches) != 1:
            continue
        seed = matches[0]
        observation = magi_fixed_ask_to_observation(
            identity=seed.identity,
            price_jpy=detailed.price_jpy,
            observed_at=observed_at,
            source_id=detailed.url,
            identity_proven=True,
            buyer_fee_rate=None,
            note="magi marketplace-first fixed ASK; exact known coordinate; buyer/logistics all-in unproven; TCGdex revalidation required downstream",
        )
        output.append(listing_from_observation(observation, source_url=detailed.url, title=detailed.title))
    return output, ScanStatus(
        "magi",
        "OK",
        pages=1,
        candidates=len(asks),
        exact=len(output),
        detail="broad Pokemon PSA10 inventory query; no per-card searches",
        complete=len(asks) <= max(1, int(max_detail_pages)),
    )


def _comc_page_url(page_number: int) -> str:
    if page_number <= 1:
        return COMC_PSA10_INDEX + "%2CvText%2Ci100"
    return COMC_PSA10_INDEX + f"%2CvText%2Ci100%2Cp{page_number}"


def scan_comc_inventory(
    page: Any,
    seeds: Sequence[legacy.Seed],
    *,
    observed_at: datetime,
    max_pages: int = 20,
    max_detail_pages: int = 200,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    output: list[MarketplaceListing] = []
    products: list[tuple[str, str, legacy.Seed]] = []
    seen: set[str] = set()
    pages = 0
    complete = True
    try:
        for page_number in range(1, max(1, int(max_pages)) + 1):
            page.goto(_comc_page_url(page_number), wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(650)
            rows = comc_v4._table_rows(page)
            pages += 1
            data = 0
            for row in rows:
                cells = row.get("cells")
                hrefs = row.get("hrefs")
                if not isinstance(cells, list) or (cells and legacy._norm(cells[0]) == "set name"):
                    continue
                data += 1
                cell_text = [str(value or "") for value in cells]
                matches: list[legacy.Seed] = []
                for seed in seeds:
                    ok, _proof = comc_v4.comc_table_row_proof(cell_text, seed.source_identity)
                    if ok:
                        matches.append(seed)
                if len(matches) != 1:
                    continue
                product = comc_v4._product_url([str(value or "") for value in hrefs]) if isinstance(hrefs, list) else None
                if not product or product in seen:
                    continue
                seen.add(product)
                products.append((product, " | ".join(cell_text[:7]), matches[0]))
            if data < 100:
                break
        else:
            complete = False
    except Exception as error:
        return output, ScanStatus("comc", "ERROR", pages, len(products), len(output), type(error).__name__, False)

    for product_url, row_text, seed in products[: max(1, int(max_detail_pages))]:
        price, proof = comc_v4._fixed_ask_from_product(page, product_url)
        if price is None:
            continue
        observation = comc_fixed_offer(
            identity=seed.identity,
            price_usd=price,
            observed_at=observed_at,
            source_id=product_url,
            identity_proven=True,
            buyer_fee_rate=None,
            note=f"COMC marketplace-first Buy Now ASK; {proof}; all-in intentionally unproven; TCGdex revalidation required downstream",
        )
        output.append(listing_from_observation(observation, source_url=product_url, title=row_text))
    if len(products) > max(1, int(max_detail_pages)):
        complete = False
    return output, ScanStatus(
        "comc",
        "OK",
        pages,
        len(products),
        len(output),
        "direct PSA10 Pokemon inventory table sweep; no player/card searches",
        complete,
    )