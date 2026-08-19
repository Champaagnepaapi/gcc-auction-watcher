from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_global_retrieval_hardening as v1
from v4_global_live_shadow import (
    COMC_POKEMON,
    FANATICS_MARKETPLACE,
    SourceStatus,
    _norm,
    _price_from_usd_text,
)
from v4_market_comc_bridge import comc_fixed_offer
from v4_market_fanatics_bridge import fanatics_fixed_offer
from v4_market_magi_bridge import magi_fixed_ask_to_observation


FANATICS_ROUTE_RE = re.compile(
    r"(?:https://www\.fanaticscollect\.com)?/(?P<kind>buy-now|fixed)/(?P<id>[0-9a-f-]{20,})(?:/[^\"'<>\s]*)?",
    re.I,
)
FANATICS_ERA_PREFIX_RE = re.compile(
    r"^(?:Scarlet\s*&\s*Violet|Sword\s*&\s*Shield|Sun\s*&\s*Moon|Black\s*&\s*White|Diamond\s*&\s*Pearl|Platinum|XY)\s+",
    re.I,
)
PSA10_RE = re.compile(r"\bPSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b", re.I)
POKEMON_RE = re.compile(r"\bPok[eé]mon\b|ポケモン", re.I)
USD_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")


@dataclass
class MarketTrace:
    market: str
    reject_reasons: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    query_pages: list[dict[str, Any]] = field(default_factory=list)
    per_identity: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _label(self, seed: Any) -> str:
        identity = seed.source_identity
        return f"{identity.name} | {identity.set_name} | {identity.number} | Japanese | PSA 10"

    def reject(self, seed: Any, reason: str, *, title: str = "", url: str = "") -> None:
        key = str(reason or "unknown").strip().casefold().replace(" ", "_")
        self.reject_reasons[key] += 1
        label = self._label(seed)
        bucket = self.per_identity.setdefault(label, {"exact": 0, "reject_reasons": {}, "retrieved": 0})
        local = bucket["reject_reasons"]
        local[key] = int(local.get(key, 0)) + 1
        examples = self.examples.setdefault(key, [])
        if len(examples) < 3:
            row = {"identity": label}
            if title:
                row["title"] = title[:300]
            if url:
                row["url"] = url[:500]
            examples.append(row)

    def retrieved(self, seed: Any, count: int) -> None:
        label = self._label(seed)
        bucket = self.per_identity.setdefault(label, {"exact": 0, "reject_reasons": {}, "retrieved": 0})
        bucket["retrieved"] += int(max(0, count))

    def exact(self, seed: Any) -> None:
        label = self._label(seed)
        bucket = self.per_identity.setdefault(label, {"exact": 0, "reject_reasons": {}, "retrieved": 0})
        bucket["exact"] += 1

    def export(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "reject_reasons": dict(self.reject_reasons.most_common()),
            "examples": self.examples,
            "query_pages": self.query_pages,
            "per_identity": self.per_identity,
        }


def _canonical_fanatics_url(value: str) -> Optional[str]:
    match = FANATICS_ROUTE_RE.search(str(value or ""))
    if not match:
        return None
    return f"https://www.fanaticscollect.com/{match.group('kind').lower()}/{match.group('id')}"


def _fanatics_set_middle(title: str, identity: japan.Identity) -> tuple[bool, str]:
    local_id = v1.target_local_id(identity)
    if local_id is None:
        return False, "local_id_unavailable"
    normalized = unicodedata.normalize("NFKC", str(title or "")).strip()
    pattern = re.compile(
        rf"^\s*\d{{4}}\s+Pokemon\s+Japanese\s+(?P<middle>.+?)\s+"
        rf"{v1._source_name_pattern(identity.name)}\s+#0*{re.escape(local_id)}\s+"
        rf"PSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b",
        re.I,
    )
    match = pattern.search(normalized)
    if not match:
        return False, "fanatics_title_schema_unproven"
    middle = " ".join(match.group("middle").split())
    middle = v1.FANATICS_SET_CODE_RE.sub("", middle).strip()
    middle = FANATICS_ERA_PREFIX_RE.sub("", middle).strip()
    middle = v1.FANATICS_RARITY_RE.sub("", middle).strip()
    middle = re.sub(r"^Pokemon\s+", "", middle, flags=re.I).strip()
    if _norm(middle) != _norm(identity.set_name):
        return False, "set_unproven"
    return True, "EXACT_SET_LOCAL_ID_PROOF_V2"


def fanatics_title_identity_proof_v2(text: str, identity: japan.Identity) -> tuple[bool, str]:
    full_ok, full_reason = v1._full_fraction_status(text, identity)
    if not full_ok:
        return False, full_reason
    title = unicodedata.normalize("NFKC", str(text or "")).splitlines()[0].strip()
    if not PSA10_RE.search(title):
        return False, "psa10_unproven"
    if not v1.JAPANESE_RE.search(title):
        return False, "language_unproven"
    ok, proof = _fanatics_set_middle(title, identity)
    if not ok:
        return False, proof
    if not v1._contains_sensitive_claims(text, identity):
        return False, "sensitive_variant_unproven"
    return True, proof


def _fanatics_queries(seed: Any) -> list[str]:
    identity = seed.source_identity
    local_id = v1.target_local_id(identity)
    raw = [
        f"{identity.name} {identity.number} {identity.set_name} Japanese PSA 10",
        f"{identity.name} {identity.set_name} PSA 10",
    ]
    if local_id is not None:
        raw.extend(
            [
                f"{identity.name} #{local_id} {identity.set_name} Japanese PSA 10",
                f"{identity.name} #{local_id} PSA 10",
                f"{identity.name} #{local_id}",
            ]
        )
    output: list[str] = []
    for value in raw:
        value = " ".join(value.split())
        if value and value not in output:
            output.append(value)
    return output


def fanatics_candidate_links_v2(page: Any, seed: Any, max_candidates: int, trace: MarketTrace) -> tuple[list[str], int]:
    output: list[str] = []
    searches = 0
    for query in _fanatics_queries(seed):
        url = FANATICS_MARKETPLACE.format(query=quote(query, safe=""))
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(1200)
        searches += 1
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            final_url = page.url
        except Exception:
            final_url = url
        try:
            hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean)")
        except Exception:
            hrefs = []
        try:
            html = page.content()
        except Exception:
            html = ""
        anchor_urls = []
        for href in hrefs if isinstance(hrefs, list) else []:
            canonical = _canonical_fanatics_url(str(href))
            if canonical and canonical not in anchor_urls:
                anchor_urls.append(canonical)
        embedded_urls = []
        for match in FANATICS_ROUTE_RE.finditer(html):
            canonical = _canonical_fanatics_url(match.group(0))
            if canonical and canonical not in embedded_urls:
                embedded_urls.append(canonical)
        trace.query_pages.append(
            {
                "identity": trace._label(seed),
                "query": query,
                "final_url": str(final_url)[:500],
                "title": str(title)[:200],
                "all_anchor_count": len(hrefs) if isinstance(hrefs, list) else 0,
                "fanatics_anchor_routes": len(anchor_urls),
                "fanatics_embedded_routes": len(embedded_urls),
                "sample_routes": (anchor_urls + [x for x in embedded_urls if x not in anchor_urls])[:5],
            }
        )
        for candidate in anchor_urls + embedded_urls:
            if candidate not in output:
                output.append(candidate)
            if len(output) >= max_candidates:
                return output, searches
    if not output:
        trace.reject(seed, "search_no_candidates")
    return output, searches


def collect_fanatics_v2(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = MarketTrace("fanatics")
    for seed in seeds:
        try:
            links, query_count = fanatics_candidate_links_v2(page, seed, max_candidates, trace)
            searches += query_count
        except Exception as error:
            trace.reject(seed, f"search_error:{type(error).__name__}")
            return found, SourceStatus("fanatics", "ERROR", type(error).__name__, searches, candidates, exact), trace
        trace.retrieved(seed, len(links))
        for url in links:
            candidates += 1
            title = ""
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(650)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                trace.reject(seed, "page_error", title=title, url=url)
                continue
            upper = body.upper()
            if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
                trace.reject(seed, "unavailable_or_sold", title=title, url=url)
                continue
            before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.I)[0]
            price = _price_from_usd_text(before_guide)
            if price is None:
                trace.reject(seed, "price_unproven", title=title, url=url)
                continue
            ok, proof = fanatics_title_identity_proof_v2(f"{title}\n{before_guide}", seed.source_identity)
            if not ok:
                trace.reject(seed, proof, title=title, url=url)
                continue
            observation = fanatics_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=0.0,
                note=f"Fanatics Buy Now ASK; {proof}; vault acquisition basis; tax/payment/shipping excluded",
            )
            found[seed.identity.strict_key].append((observation, url, title))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "fanatics", "OK", "public Buy Now read-only; anchors+embedded routes; exact set+localId proof v2", searches, candidates, exact
    ), trace


def _magi_search_urls_v2(identity: japan.Identity) -> list[str]:
    provider = next(provider for provider in japan.PROVIDERS if provider.code == "magi")
    queries = [
        f"{identity.number} PSA10 ポケモン",
        f"{identity.name} {identity.number} PSA10 ポケモン",
        f"{identity.set_name} {identity.number} PSA10 ポケモン",
        f"{identity.number} PSA10",
    ]
    output = []
    for query in queries:
        url = provider.search_url.format(q=quote(" ".join(query.split()), safe=""))
        if url not in output:
            output.append(url)
    return output


def magi_candidates_v2(page: Any, seed: Any, max_candidates: int, trace: MarketTrace) -> tuple[list[japan.Ask], int]:
    identity = seed.source_identity
    provider = next(provider for provider in japan.PROVIDERS if provider.code == "magi")
    target_number = japan.number(identity.number)
    strong: list[japan.Ask] = []
    weak: list[japan.Ask] = []
    seen: set[str] = set()
    searches = 0
    for search_url in _magi_search_urls_v2(identity):
        page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(700)
        searches += 1
        rows = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('a[href]')).slice(0,1200).map(a=>{let n=a,t=(a.innerText||a.textContent||'').trim();for(let i=0;i<6&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(/[¥￥]|\d[\d,]*\s*円/.test(x)){t=x;break;}}return {href:a.href||'',anchor:(a.innerText||'').trim(),text:t};})"""
        )
        matched_number = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            url = japan.canonical_url(provider, str(row.get("href") or ""))
            snippet = str(row.get("text") or "")
            title = str(row.get("anchor") or "").strip() or next((x.strip() for x in snippet.splitlines() if x.strip()), "")
            if not url or url in seen:
                continue
            if target_number not in japan.number_tokens(f"{title}\n{snippet}"):
                continue
            matched_number += 1
            if japan.has_any(snippet, japan.AUCTION):
                continue
            price = japan.parse_yen(snippet)
            if price is None:
                continue
            ask = japan.Ask("magi", url, title[:500], price, snippet[:4000])
            pokemon_like = bool(POKEMON_RE.search(f"{title}\n{snippet}"))
            psa10_like = bool(PSA10_RE.search(unicodedata.normalize("NFKC", f"{title}\n{snippet}")))
            (strong if pokemon_like and psa10_like else weak).append(ask)
            seen.add(url)
        trace.query_pages.append(
            {
                "identity": trace._label(seed),
                "query_url": search_url[:500],
                "rows_seen": len(rows) if isinstance(rows, list) else 0,
                "full_number_rows": matched_number,
                "strong_total_so_far": len(strong),
                "weak_total_so_far": len(weak),
            }
        )
    ordered = strong + weak
    if not ordered:
        trace.reject(seed, "search_no_candidates")
    return ordered[:max_candidates], searches


def collect_magi_v2(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = MarketTrace("magi")
    for seed in seeds:
        try:
            asks, query_count = magi_candidates_v2(page, seed, max_candidates, trace)
            searches += query_count
        except Exception as error:
            trace.reject(seed, f"search_error:{type(error).__name__}")
            return found, SourceStatus("magi", "ERROR", type(error).__name__, searches, candidates, exact), trace
        trace.retrieved(seed, len(asks))
        for ask in asks:
            candidates += 1
            try:
                detailed = v1.magi_detail_only(page, ask)
            except Exception:
                trace.reject(seed, "detail_error", title=ask.title, url=ask.url)
                continue
            ok, proof = japan.identity_check(detailed, seed.source_identity)
            if not ok:
                trace.reject(seed, proof, title=detailed.title, url=detailed.url)
                continue
            observation = magi_fixed_ask_to_observation(
                identity=seed.identity,
                price_jpy=detailed.price_jpy,
                observed_at=observed_at,
                source_id=detailed.url,
                identity_proven=True,
                buyer_fee_rate=None,
                note=f"magi fixed ASK; {proof}; buyer/logistics all-in intentionally unproven in global shadow",
            )
            found[seed.identity.strict_key].append((observation, detailed.url, detailed.title))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "magi", "OK", "public read-only; Pokemon/PSA10 priority before cap + detail exact gate", searches, candidates, exact
    ), trace


def _comc_direct_player_url(name: str) -> str:
    return f"{COMC_POKEMON}/Players/Pokemon/{quote(str(name or '').strip(), safe='')}"


def _comc_metadata_line_exact(text: str, identity: japan.Identity) -> bool:
    local_id = v1.target_local_id(identity)
    if local_id is None:
        return False
    target_set = re.escape(unicodedata.normalize("NFKC", str(identity.set_name or "")).strip())
    if not target_set:
        return False
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    pattern = re.compile(
        rf"(?:^|\n)[^\n]*-\s*{target_set}\s*(?:\[[^\]]+\])?\s*-\s*(?:\[[^\]]+\]\s*-\s*)*Japanese\s+#0*{re.escape(local_id)}\b",
        re.I,
    )
    return bool(pattern.search(normalized))


def _comc_name_exact(text: str, identity: japan.Identity) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return bool(re.search(rf"(?<![A-Za-z0-9]){v1._source_name_pattern(identity.name)}(?![A-Za-z0-9])", normalized, re.I))


def comc_row_candidate_proof_v2(text: str, identity: japan.Identity) -> tuple[bool, str]:
    full_ok, full_reason = v1._full_fraction_status(text, identity)
    if not full_ok:
        return False, full_reason
    if not _comc_metadata_line_exact(text, identity):
        return False, "set_language_localid_unproven"
    if not _comc_name_exact(text, identity):
        return False, "card_name_unproven"
    return True, "COMC_EXACT_METADATA_LOCAL_ID_CANDIDATE_V2"


def comc_psa10_price_from_row(text: str) -> Optional[float]:
    lines = [line.strip() for line in unicodedata.normalize("NFKC", str(text or "")).splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not PSA10_RE.search(line):
            continue
        window = "\n".join(lines[index : index + 4])
        match = USD_RE.search(window)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def comc_candidate_rows_v2(page: Any, seed: Any, max_candidates: int, trace: MarketTrace) -> list[tuple[str, str, float]]:
    player_url = v1._comc_player_url(page, seed.source_identity.name)
    if not player_url:
        player_url = _comc_direct_player_url(seed.source_identity.name)
    page.goto(player_url, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(900)
    try:
        final_url = page.url
        title = page.title()
    except Exception:
        final_url, title = player_url, ""
    rows = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/Cards/Pokemon/"]')).map(a => {let n=a;let chosen=(a.innerText||a.textContent||'').trim();for(let i=0;i<7&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(/\$\s*\d/.test(x)){chosen=x;break;}}return {href:a.href,text:chosen};})"""
    )
    output: list[tuple[str, str, float]] = []
    seen: set[str] = set()
    proof_counts: Counter[str] = Counter()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "")
        ok, proof = comc_row_candidate_proof_v2(text, seed.source_identity)
        if not ok:
            proof_counts[proof] += 1
            continue
        price = comc_psa10_price_from_row(text)
        if price is None:
            proof_counts["psa10_price_unproven"] += 1
            continue
        url = str(row.get("href") or "").split("?", 1)[0].split("#", 1)[0]
        if url and url not in seen:
            output.append((url, text[:6000], price))
            seen.add(url)
        if len(output) >= max_candidates:
            break
    trace.query_pages.append(
        {
            "identity": trace._label(seed),
            "player_url": player_url[:500],
            "final_url": str(final_url)[:500],
            "title": str(title)[:200],
            "rows_seen": len(rows) if isinstance(rows, list) else 0,
            "candidate_rows": len(output),
            "row_reject_reasons": dict(proof_counts.most_common(8)),
        }
    )
    if not output:
        trace.reject(seed, "search_no_actionable_psa10_candidate")
    return output


def collect_comc_v2(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = MarketTrace("comc")
    for seed in seeds:
        try:
            rows = comc_candidate_rows_v2(page, seed, max_candidates, trace)
            searches += 1
        except Exception as error:
            trace.reject(seed, f"search_error:{type(error).__name__}")
            return found, SourceStatus("comc", "ERROR", type(error).__name__, searches, candidates, exact), trace
        trace.retrieved(seed, len(rows))
        for url, row_text, price in rows:
            candidates += 1
            if not v1._contains_sensitive_claims(row_text, seed.source_identity):
                trace.reject(seed, "sensitive_variant_unproven", url=url)
                continue
            observation = comc_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=None,
                note="COMC Buy Now ASK; exact metadata line + PSA10 row price; buyer/logistics all-in intentionally unproven",
            )
            found[seed.identity.strict_key].append((observation, url, row_text.splitlines()[0] if row_text else ""))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "comc", "OK", "public read-only; direct player fallback + exact metadata/localId + PSA10 row price", searches, candidates, exact
    ), trace


def traces_to_json(*traces: MarketTrace) -> list[dict[str, Any]]:
    return [trace.export() for trace in traces]
