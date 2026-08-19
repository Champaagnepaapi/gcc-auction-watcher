from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Mapping, Optional, Sequence

import v4_global_comc_hardening as v4
import v4_global_retrieval_hardening_v2 as retrieval_v2
from v4_global_live_shadow import SourceStatus, _norm
from v4_market_comc_bridge import comc_fixed_offer


COMC_PSA10_INDEX = "https://www.comc.com/Cards/Pokemon%2CaGraded%2CrPSA%2Cg10"
COMC_PSA10_SUFFIX = "%2CaGraded%2CrPSA%2Cg10"
PLAYER_COUNT_RE = re.compile(r"\s*\([0-9][0-9,]*\)\s*$")

# Retrieval-only escape hatch for COMC player facets that are not exposed on the
# global category/graded indexes. The route is an exact public COMC set page and
# cannot prove commercial identity by itself: every emitted observation still
# has to pass the strict Japanese + set + number + card-name + PSA10 row gate.
#
# Provenance checked 2026-08-16:
# https://www.comc.com/Cards/Pokemon/2023/Pokemon_Scarlet__Violet_-_Raging_Surf_sv3a_-_Base_-_Japanese
COMC_EXACT_SET_RETRIEVAL_ROUTES = {
    ("raging surf", "japanese", 2023): (
        "https://www.comc.com/Cards/Pokemon/2023/"
        "Pokemon_Scarlet__Violet_-_Raging_Surf_sv3a_-_Base_-_Japanese"
    ),
}


def _retrieval_player_label(text: str) -> str:
    """Normalize a COMC player label for retrieval only.

    COMC may render player facets as ``Groudon (3)``. Removing only that trailing
    numeric count is deterministic and cannot prove card identity; the strict
    table-row proof remains mandatory before any observation is emitted.
    """
    raw = unicodedata.normalize("NFKC", str(text or "")).strip()
    return _norm(PLAYER_COUNT_RE.sub("", raw))


def _counted_player_anchor(page: Any, name: str) -> Optional[str]:
    target = _norm(name)
    rows = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/Players/Pokemon/"]')).map(a => ({href:a.href,text:(a.innerText||a.textContent||'').trim()}))"""
    )
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        if _retrieval_player_label(str(row.get("text") or "")) != target:
            continue
        base = v4._player_base(str(row.get("href") or ""))
        if base:
            return base
    return None


def _exact_set_retrieval_url(identity: Any) -> Optional[str]:
    try:
        year = int(identity.year)
    except (TypeError, ValueError, AttributeError):
        return None
    key = (
        _norm(getattr(identity, "set_name", "")),
        _norm(getattr(identity, "language", "")),
        year,
    )
    return COMC_EXACT_SET_RETRIEVAL_ROUTES.get(key)


def resolve_comc_player_base_v2(page: Any, identity: Any) -> tuple[Optional[str], str]:
    name = str(getattr(identity, "name", "") or "").strip()
    base, proof = v4.resolve_comc_player_base(page, name)
    if base:
        return base, proof

    # Retrieval-only fallbacks. Exact commercial identity is still proven later
    # from set/language/localId/card-name/PSA10 fields in the COMC row.
    for index_url, reason in (
        (COMC_PSA10_INDEX, "PLAYER_LINK_PSA10_INDEX_COUNT_STRIPPED"),
        (v4.COMC_GRADED_INDEX, "PLAYER_LINK_GRADED_INDEX_COUNT_STRIPPED"),
        ("https://www.comc.com/Cards/Pokemon", "PLAYER_LINK_CATEGORY_COUNT_STRIPPED"),
    ):
        try:
            page.goto(index_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(650)
            candidate = _counted_player_anchor(page, name)
        except Exception:
            candidate = None
        if candidate:
            return candidate, reason

    exact_set_url = _exact_set_retrieval_url(identity)
    if exact_set_url:
        try:
            page.goto(exact_set_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(650)
            candidate = _counted_player_anchor(page, name)
        except Exception:
            candidate = None
        if candidate:
            return candidate, "PLAYER_LINK_EXACT_SET_ROUTE_COUNT_STRIPPED"

    return None, "PLAYER_UNRESOLVED"


def _graded_page_url(base: str, sort_mode: str, page_number: int = 1) -> str:
    mode = sort_mode if sort_mode in v4.COMC_SORT_MODES else "sn"
    suffix = f"%2C{mode}%2CvText%2Ci100{COMC_PSA10_SUFFIX}"
    if page_number > 1:
        suffix += f"%2Cp{page_number}"
    return base + suffix


def _query_plan(base: str, sort_modes: Sequence[str]) -> list[tuple[str, str, str]]:
    modes = tuple(dict.fromkeys(mode for mode in sort_modes if mode in v4.COMC_SORT_MODES))
    output: list[tuple[str, str, str]] = []
    # COMC supports explicit graded/grader/grade filters. Query them first so a
    # PSA10 row cannot be pushed outside the first 100 results by raw inventory.
    for mode in modes:
        output.append((mode, "PSA10_FILTER", _graded_page_url(base, mode, 1)))
    # Broad pages remain as a bounded fallback/diagnostic if COMC changes filter
    # behavior. They do not weaken the exact row gate.
    for mode in modes:
        output.append((mode, "BROAD_FALLBACK", v4._page_url(base, mode, 1)))
    return output


def collect_comc_v5(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
    sort_modes: Sequence[str] = v4.COMC_SORT_MODES,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = retrieval_v2.MarketTrace("comc")

    for seed in seeds:
        player_base, player_proof = resolve_comc_player_base_v2(page, seed.source_identity)
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
        targetish_examples: list[str] = []
        for sort_mode, query_scope, url in _query_plan(player_base, sort_modes):
            if len(exact_rows) >= max_candidates:
                break
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(650)
                table_rows = v4._table_rows(page)
                final_url = page.url
                title = page.title()
            except Exception as error:
                trace.reject(seed, f"page_error:{type(error).__name__}", url=url)
                searches += 1
                continue
            searches += 1
            reasons: Counter[str] = Counter()
            matched_on_page = 0
            data_rows = 0
            targetish_on_page = 0
            for row in table_rows:
                cells = row.get("cells")
                hrefs = row.get("hrefs")
                if not isinstance(cells, list):
                    continue
                if cells and _norm(cells[0]) == "set name":
                    continue
                cell_text = [str(x or "") for x in cells]
                data_rows += 1
                if v4._set_and_name_proven(cell_text, seed.source_identity):
                    targetish_on_page += 1
                    if len(targetish_examples) < 6:
                        targetish_examples.append(" | ".join(cell_text[:7])[:500])
                ok, proof = v4.comc_table_row_proof(cell_text, seed.source_identity)
                if not ok:
                    reasons[proof] += 1
                    continue
                product = v4._product_url([str(x or "") for x in hrefs]) if isinstance(hrefs, list) else None
                if not product:
                    reasons["product_url_unproven"] += 1
                    continue
                if product in seen_products:
                    continue
                seen_products.add(product)
                exact_rows.append((product, " | ".join(cell_text[:7])))
                matched_on_page += 1
                if len(exact_rows) >= max_candidates:
                    break
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "player_proof": player_proof,
                    "player_base": player_base,
                    "query_scope": query_scope,
                    "sort_mode": sort_mode,
                    "page": 1,
                    "url": url,
                    "final_url": str(final_url)[:500],
                    "title": str(title)[:200],
                    "rows_seen": data_rows,
                    "targetish_rows": targetish_on_page,
                    "exact_rows": matched_on_page,
                    "row_reject_reasons": dict(reasons.most_common(8)),
                }
            )

        trace.retrieved(seed, len(exact_rows))
        if targetish_examples:
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "targetish_examples": targetish_examples,
                    "note": "Exact card/set/language rows seen before grade/actionability gate; PSA10 filter is retrieval-only and exact row proof remains mandatory.",
                }
            )
        if not exact_rows:
            trace.reject(seed, "search_no_exact_psa10_row")
            continue

        for product_url, row_text in exact_rows:
            candidates += 1
            price, proof = v4._fixed_ask_from_product(page, product_url)
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
        "public read-only; PSA10-filter-first player sweep + bounded broad fallback + exact table-row proof",
        searches,
        candidates,
        exact,
    ), trace
