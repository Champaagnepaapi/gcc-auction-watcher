from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_global_retrieval_hardening as v1
import v4_global_retrieval_hardening_v2 as v2
from v4_global_live_shadow import SourceStatus, _comc_ask_price, _norm
from v4_market_comc_bridge import comc_fixed_offer


COMC_GRADED_INDEX = "https://www.comc.com/Cards/Pokemon%2CaGraded"
PSA10_RE = re.compile(r"(?<![A-Z0-9])PSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?(?![0-9])", re.I)
PLAYER_BASE_RE = re.compile(r"^(https://www\.comc\.com/Players/Pokemon/[^/]+/c\d+/Cards/Pokemon)", re.I)


def _player_base(url: str) -> Optional[str]:
    match = PLAYER_BASE_RE.match(str(url or "").split("?", 1)[0])
    return match.group(1) if match else None


def _exact_player_anchor(page: Any, name: str) -> Optional[str]:
    target = _norm(name)
    rows = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/Players/Pokemon/"]')).map(a => ({href:a.href,text:(a.innerText||a.textContent||'').trim()}))"""
    )
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        if _norm(row.get("text")) != target:
            continue
        base = _player_base(str(row.get("href") or ""))
        if base:
            return base
    return None


def resolve_comc_player_base(page: Any, name: str) -> tuple[Optional[str], str]:
    legacy = v1._comc_player_url(page, name)
    base = _player_base(legacy or "")
    if base:
        return base, "PLAYER_LINK_CATEGORY"

    page.goto(COMC_GRADED_INDEX, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(700)
    graded = _exact_player_anchor(page, name)
    if graded:
        return graded, "PLAYER_LINK_GRADED_INDEX"

    semantic = f"https://www.comc.com/Players/Pokemon/{quote(str(name or '').strip(), safe='')}"
    try:
        page.goto(semantic, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(500)
        canonical = _player_base(page.url)
        title = page.title()
    except Exception:
        canonical = None
        title = ""
    if canonical and _norm(name) in _norm(title):
        return canonical, "PLAYER_SEMANTIC_REDIRECT"
    return None, "PLAYER_UNRESOLVED"


def _page_url(base: str, page_number: int) -> str:
    suffix = "%2Csn%2CvText%2Ci100"
    if page_number > 1:
        suffix += f"%2Cp{page_number}"
    return base + suffix


def _table_rows(page: Any) -> list[Mapping[str, Any]]:
    rows = page.evaluate(
        r"""() => Array.from(document.querySelectorAll('tr')).map(tr => ({
          cells: Array.from(tr.querySelectorAll('th,td')).map(td => (td.innerText || td.textContent || '').replace(/\s+/g,' ').trim()),
          hrefs: Array.from(tr.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean)
        })).filter(row => row.cells.length >= 3)"""
    )
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _local_matches(field: str, identity: japan.Identity) -> bool:
    target = v1.target_local_id(identity)
    if target is None:
        return False
    normalized = unicodedata.normalize("NFKC", str(field or "")).upper().replace(" ", "").lstrip("#")
    if "/" in normalized:
        candidate = v1._number(normalized)
        return bool(candidate) and candidate == v1._number(identity.number)
    if normalized.isdigit() and target.isdigit():
        return int(normalized) == int(target)
    return normalized.casefold() == target.casefold()


def _has_exact_full_number(field: str, identity: japan.Identity) -> bool:
    normalized = unicodedata.normalize("NFKC", str(field or "")).upper().replace(" ", "").lstrip("#")
    if "/" not in normalized:
        return False
    candidate = v1._number(normalized)
    return bool(candidate) and candidate == v1._number(identity.number)


def _alpha_denominator(identity: japan.Identity) -> bool:
    value = v1._number(identity.number)
    return "/" in value and bool(re.search(r"[A-Za-z]", value.split("/", 1)[1]))


def comc_table_row_proof(cells: Sequence[str], identity: japan.Identity) -> tuple[bool, str]:
    if len(cells) < 3:
        return False, "row_schema_unproven"
    set_field = unicodedata.normalize("NFKC", str(cells[0] or ""))
    number_field = unicodedata.normalize("NFKC", str(cells[1] or ""))
    description = unicodedata.normalize("NFKC", str(cells[2] or ""))

    if "japanese" not in _norm(set_field):
        return False, "language_unproven"
    if not _local_matches(number_field, identity):
        return False, "collector_number_unproven"

    full_number = _has_exact_full_number(number_field, identity)
    if not full_number or not _alpha_denominator(identity):
        if _norm(identity.set_name) not in _norm(set_field):
            return False, "set_unproven"

    if not re.search(
        rf"(?<![A-Za-z0-9]){v1._source_name_pattern(identity.name)}(?![A-Za-z0-9])",
        description,
        re.I,
    ):
        return False, "card_name_unproven"
    if not PSA10_RE.search(description):
        return False, "psa10_unproven"
    if not v1._contains_sensitive_claims(f"{set_field}\n{description}", identity):
        return False, "sensitive_variant_unproven"
    return True, "COMC_EXACT_TABLE_ROW"


def _product_url(hrefs: Sequence[str]) -> Optional[str]:
    for href in hrefs:
        value = str(href or "").split("?", 1)[0].split("#", 1)[0]
        if "/Cards/Pokemon/" in value and "/Players/Pokemon/" not in value:
            return value
    return None


def _fixed_ask_from_product(page: Any, url: str) -> tuple[Optional[float], str]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(650)
        body = page.locator("body").inner_text(timeout=5000)
    except Exception as error:
        return None, f"product_page_error:{type(error).__name__}"
    upper = body.upper()
    if "0 RESULTS" in upper or "SOLD OUT" in upper:
        return None, "sold_out"
    price = _comc_ask_price(body)
    if price is None:
        return None, "fixed_all_sellers_price_unproven"
    if "ALL SELLERS" not in upper:
        return None, "all_sellers_section_unproven"
    return price, "COMC_FIXED_ALL_SELLERS"


def collect_comc_v4(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
    max_pages_per_player: int = 5,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("comc")

    for seed in seeds:
        player_base, player_proof = resolve_comc_player_base(page, seed.source_identity.name)
        if not player_base:
            trace.reject(seed, "player_url_unresolved")
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "player_proof": player_proof,
                    "player_base": "",
                }
            )
            continue

        exact_rows: list[tuple[str, str]] = []
        seen_products: set[str] = set()
        stop = False
        for page_number in range(1, max(1, max_pages_per_player) + 1):
            url = _page_url(player_base, page_number)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(650)
                table_rows = _table_rows(page)
                final_url = page.url
                title = page.title()
            except Exception as error:
                trace.reject(seed, f"page_error:{type(error).__name__}", url=url)
                searches += 1
                break
            searches += 1
            reasons: Counter[str] = Counter()
            matched_on_page = 0
            data_rows = 0
            for row in table_rows:
                cells = row.get("cells")
                hrefs = row.get("hrefs")
                if not isinstance(cells, list):
                    continue
                if cells and _norm(cells[0]) == "set name":
                    continue
                data_rows += 1
                ok, proof = comc_table_row_proof([str(x or "") for x in cells], seed.source_identity)
                if not ok:
                    reasons[proof] += 1
                    continue
                product = _product_url([str(x or "") for x in hrefs]) if isinstance(hrefs, list) else None
                if not product:
                    reasons["product_url_unproven"] += 1
                    continue
                if product in seen_products:
                    continue
                seen_products.add(product)
                exact_rows.append((product, " | ".join(str(x or "") for x in cells[:7])))
                matched_on_page += 1
                if len(exact_rows) >= max_candidates:
                    stop = True
                    break
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "player_proof": player_proof,
                    "player_base": player_base,
                    "page": page_number,
                    "url": url,
                    "final_url": str(final_url)[:500],
                    "title": str(title)[:200],
                    "rows_seen": data_rows,
                    "exact_rows": matched_on_page,
                    "row_reject_reasons": dict(reasons.most_common(8)),
                }
            )
            if stop:
                break
            if data_rows < 95:
                break

        trace.retrieved(seed, len(exact_rows))
        if not exact_rows:
            trace.reject(seed, "search_no_exact_psa10_row")
            continue

        for product_url, row_text in exact_rows:
            candidates += 1
            price, proof = _fixed_ask_from_product(page, product_url)
            if price is None:
                trace.reject(seed, proof, title=row_text, url=product_url)
                continue
            observation = comc_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=product_url,
                identity_proven=True,
                buyer_fee_rate=None,
                note=f"COMC Buy Now ASK; COMC_EXACT_TABLE_ROW + {proof}; buyer/logistics all-in intentionally unproven",
            )
            found[seed.identity.strict_key].append((observation, product_url, row_text[:500]))
            exact += 1
            trace.exact(seed)

    return found, SourceStatus(
        "comc",
        "OK",
        "public read-only; exhaustive bounded player pagination + exact PSA10 row + fixed All Sellers price",
        searches,
        candidates,
        exact,
    ), trace
