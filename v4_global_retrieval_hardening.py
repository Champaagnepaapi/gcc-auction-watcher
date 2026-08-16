from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import japan_edge_hunter as japan
from v4_global_live_shadow import (
    FANATICS_MARKETPLACE,
    SourceStatus,
    _comc_ask_price,
    _comc_player_url,
    _norm,
    _number,
    _number_tokens,
    _price_from_usd_text,
    _sensitive_required,
)
from v4_market_comc_bridge import comc_fixed_offer
from v4_market_fanatics_bridge import fanatics_fixed_offer
from v4_market_magi_bridge import magi_fixed_ask_to_observation


FANATICS_SET_CODE_RE = re.compile(r"^(?:SV|SWSH|SM|XY|BW|HGSS|DP)[A-Z0-9-]*\s+", re.I)
FANATICS_RARITY_RE = re.compile(
    r"\s+(?:AR|SAR|SR|UR|CHR|CSR|RR|RRR|HR|SSR|PROMO|HOLORARE|HOLO|REVERSE)\s*$",
    re.I,
)
PSA10_RE = re.compile(r"\bPSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b", re.I)
JAPANESE_RE = re.compile(r"\b(?:JAPANESE|JAPAN|JPN)\b|日本語|日本版", re.I)


def target_local_id(identity: japan.Identity) -> Optional[str]:
    number = _number(identity.number)
    left = number.split("/", 1)[0]
    if not left.isdigit():
        return None
    return str(int(left))


def _full_fraction_status(text: str, identity: japan.Identity) -> tuple[bool, str]:
    tokens = _number_tokens(text)
    if not tokens:
        return True, "NO_FULL_FRACTION_EXPOSED"
    target = _number(identity.number)
    if target in tokens:
        return True, "FULL_FRACTION_EXACT"
    return False, "conflicting_full_fraction"


def _contains_sensitive_claims(text: str, identity: japan.Identity) -> bool:
    normalized = _norm(text)
    return all(_norm(claim) in normalized for claim in _sensitive_required(identity))


def _source_name_pattern(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(name or "")).strip()
    return re.escape(normalized).replace(r"\ ", r"\s+")


def fanatics_title_identity_proof(text: str, identity: japan.Identity) -> tuple[bool, str]:
    """Deterministic Fanatics fallback when the source exposes localId, not denominator.

    The proof binds localId to a parsed exact set field in the Fanatics title. If a
    full fraction is present anywhere, it must agree with the target.
    """
    full_ok, full_reason = _full_fraction_status(text, identity)
    if not full_ok:
        return False, full_reason
    local_id = target_local_id(identity)
    if local_id is None:
        return False, "local_id_unavailable"
    title = unicodedata.normalize("NFKC", str(text or "")).splitlines()[0].strip()
    if not title:
        return False, "empty_text"
    pattern = re.compile(
        rf"^\s*(?P<year>\d{{4}})\s+Pokemon\s+Japanese\s+"
        rf"(?P<middle>.+?)\s+{_source_name_pattern(identity.name)}\s+"
        rf"#0*{re.escape(local_id)}\s+PSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b",
        re.I,
    )
    match = pattern.search(title)
    if not match:
        if not PSA10_RE.search(title):
            return False, "psa10_unproven"
        if not JAPANESE_RE.search(title):
            return False, "language_unproven"
        if not re.search(rf"#0*{re.escape(local_id)}\b", title, re.I):
            return False, "local_id_unproven"
        return False, "fanatics_title_schema_unproven"

    middle = " ".join(match.group("middle").split())
    middle = FANATICS_SET_CODE_RE.sub("", middle).strip()
    middle = FANATICS_RARITY_RE.sub("", middle).strip()
    middle = re.sub(r"^Pokemon\s+", "", middle, flags=re.I).strip()
    if _norm(middle) != _norm(identity.set_name):
        return False, "set_unproven"
    if not _contains_sensitive_claims(text, identity):
        return False, "sensitive_variant_unproven"
    return True, "EXACT_SET_LOCAL_ID_PROOF"


def _fanatics_queries(seed: Any) -> list[str]:
    identity = seed.source_identity
    local_id = target_local_id(identity)
    raw = [
        f"{identity.name} {identity.number} {identity.set_name} Japanese PSA 10",
    ]
    if local_id is not None:
        raw.extend(
            [
                f"{identity.name} #{local_id} {identity.set_name} Japanese PSA 10",
                f"{identity.name} #{local_id} Japanese PSA 10",
            ]
        )
    output: list[str] = []
    for value in raw:
        value = " ".join(value.split())
        if value and value not in output:
            output.append(value)
    return output


def fanatics_candidate_links_hardened(page: Any, seed: Any, max_candidates: int) -> tuple[list[str], int]:
    output: list[str] = []
    searches = 0
    for query in _fanatics_queries(seed):
        page.goto(FANATICS_MARKETPLACE.format(query=quote(query, safe="")), wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(900)
        searches += 1
        links = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href*="/buy-now/"]')).map(a => a.href).filter(Boolean)"""
        )
        for link in links if isinstance(links, list) else []:
            value = str(link).split("#", 1)[0].split("?", 1)[0]
            if value and value not in output:
                output.append(value)
            if len(output) >= max_candidates:
                return output, searches
    return output, searches


def collect_fanatics_hardened(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    for seed in seeds:
        try:
            links, query_count = fanatics_candidate_links_hardened(page, seed, max_candidates)
            searches += query_count
        except Exception as error:
            return found, SourceStatus("fanatics", "ERROR", type(error).__name__, searches, candidates, exact)
        for url in links:
            candidates += 1
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(650)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                continue
            upper = body.upper()
            if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
                continue
            before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.I)[0]
            price = _price_from_usd_text(before_guide)
            if price is None:
                continue
            ok, proof = fanatics_title_identity_proof(f"{title}\n{before_guide}", seed.source_identity)
            if not ok:
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
    return found, SourceStatus(
        "fanatics",
        "OK",
        "public Buy Now read-only; exact set+localId fallback when denominator absent",
        searches,
        candidates,
        exact,
    )


def _magi_search_urls(identity: japan.Identity) -> list[str]:
    provider = next(provider for provider in japan.PROVIDERS if provider.code == "magi")
    queries = [f"{identity.number} PSA10 ポケモン", f"{identity.number} PSA10"]
    return [provider.search_url.format(q=quote(query, safe="")) for query in queries]


def magi_candidates_hardened(page: Any, identity: japan.Identity, max_candidates: int) -> tuple[list[japan.Ask], int]:
    provider = next(provider for provider in japan.PROVIDERS if provider.code == "magi")
    target_number = japan.number(identity.number)
    output: list[japan.Ask] = []
    seen: set[str] = set()
    searches = 0
    for search_url in _magi_search_urls(identity):
        page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(700)
        searches += 1
        rows = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('a[href]')).slice(0,1200).map(a=>{let n=a,t=(a.innerText||a.textContent||'').trim();for(let i=0;i<6&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(/[¥￥]|\d[\d,]*\s*円/.test(x)){t=x;break;}}return {href:a.href||'',anchor:(a.innerText||'').trim(),text:t};})"""
        )
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            url = japan.canonical_url(provider, str(row.get("href") or ""))
            snippet = str(row.get("text") or "")
            title = str(row.get("anchor") or "").strip() or next((x.strip() for x in snippet.splitlines() if x.strip()), "")
            if not url or url in seen:
                continue
            # Critical change: target-number filtering happens BEFORE the candidate cap.
            if target_number not in japan.number_tokens(f"{title}\n{snippet}"):
                continue
            if japan.has_any(snippet, japan.AUCTION):
                continue
            price = japan.parse_yen(snippet)
            if price is None:
                continue
            output.append(japan.Ask("magi", url, title[:500], price, snippet[:4000]))
            seen.add(url)
            if len(output) >= max_candidates:
                return output, searches
    return output, searches


def magi_detail_only(page: Any, ask: japan.Ask) -> japan.Ask:
    page.goto(ask.url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(500)
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    try:
        title = page.title().strip() or ask.title
    except Exception:
        title = ask.title
    # Do not concatenate broad search-result snippets into identity evidence.
    return japan.Ask(ask.provider, ask.url, title[:500], ask.price_jpy, japan.current_text(body)[:30000])


def collect_magi_hardened(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    for seed in seeds:
        try:
            asks, query_count = magi_candidates_hardened(page, seed.source_identity, max_candidates)
            searches += query_count
        except Exception as error:
            return found, SourceStatus("magi", "ERROR", type(error).__name__, searches, candidates, exact)
        for ask in asks:
            candidates += 1
            try:
                detailed = magi_detail_only(page, ask)
            except Exception:
                continue
            ok, proof = japan.identity_check(detailed, seed.source_identity)
            if not ok:
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
    return found, SourceStatus(
        "magi",
        "OK",
        "public read-only; exact full-number prefilter before cap; detail-only identity evidence",
        searches,
        candidates,
        exact,
    )


def _comc_set_field_exact(text: str, set_name: str) -> bool:
    target = re.escape(unicodedata.normalize("NFKC", str(set_name or "")).strip())
    if not target:
        return False
    # COMC rows delimit set names with '-', pipes/newlines, and often append [set-code].
    pattern = re.compile(
        rf"(?:^|\s[-|]\s|\n)\s*{target}\s*(?:\[[^\]]+\])?\s*(?=$|\s[-|]\s|\n)",
        re.I,
    )
    return bool(pattern.search(unicodedata.normalize("NFKC", str(text or ""))))


def comc_row_candidate_proof(text: str, identity: japan.Identity) -> tuple[bool, str]:
    full_ok, full_reason = _full_fraction_status(text, identity)
    if not full_ok:
        return False, full_reason
    local_id = target_local_id(identity)
    if local_id is None:
        return False, "local_id_unavailable"
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    if not JAPANESE_RE.search(normalized):
        return False, "language_unproven"
    if not _comc_set_field_exact(normalized, identity.set_name):
        return False, "set_unproven"
    name_pattern = _source_name_pattern(identity.name)
    if not re.search(rf"#0*{re.escape(local_id)}\s+{name_pattern}(?:\b|\s|$)", normalized, re.I):
        return False, "card_name_or_local_id_unproven"
    return True, "COMC_EXACT_SET_LOCAL_ID_CANDIDATE"


def comc_detail_identity_proof(text: str, identity: japan.Identity) -> tuple[bool, str]:
    ok, reason = comc_row_candidate_proof(text, identity)
    if not ok:
        return False, reason
    if not PSA10_RE.search(unicodedata.normalize("NFKC", str(text or ""))):
        return False, "psa10_unproven"
    if not _contains_sensitive_claims(text, identity):
        return False, "sensitive_variant_unproven"
    return True, "EXACT_SET_LOCAL_ID_PROOF"


def comc_candidate_rows_hardened(page: Any, seed: Any, max_candidates: int) -> list[tuple[str, str]]:
    player_url = _comc_player_url(page, seed.source_identity.name)
    if not player_url:
        return []
    page.goto(player_url, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(800)
    rows = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/Cards/Pokemon/"]')).map(a => {let n=a;let t='';for(let i=0;i<6&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(x.length>t.length)t=x;}return {href:a.href,text:t};})"""
    )
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "")
        ok, _proof = comc_row_candidate_proof(text, seed.source_identity)
        if not ok:
            continue
        url = str(row.get("href") or "").split("?", 1)[0].split("#", 1)[0]
        if url and url not in seen:
            output.append((url, text[:6000]))
            seen.add(url)
        if len(output) >= max_candidates:
            break
    return output


def collect_comc_hardened(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    for seed in seeds:
        try:
            rows = comc_candidate_rows_hardened(page, seed, max_candidates)
            searches += 1
        except Exception as error:
            return found, SourceStatus("comc", "ERROR", type(error).__name__, searches, candidates, exact)
        for url, row_text in rows:
            candidates += 1
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(600)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                continue
            upper = body.upper()
            if "SOLD OUT" in upper or "0 RESULTS" in upper:
                continue
            price = _comc_ask_price(body)
            if price is None:
                continue
            evidence_text = f"{row_text}\n{title}\n{body[:6000]}"
            ok, proof = comc_detail_identity_proof(evidence_text, seed.source_identity)
            if not ok:
                continue
            observation = comc_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=None,
                note=f"COMC Buy Now ASK; {proof}; buyer/logistics all-in intentionally unproven in global shadow",
            )
            found[seed.identity.strict_key].append((observation, url, title))
            exact += 1
    return found, SourceStatus(
        "comc",
        "OK",
        "public read-only; exact COMC set-field+localId proof when denominator absent",
        searches,
        candidates,
        exact,
    )
