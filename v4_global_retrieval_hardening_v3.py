from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

import japan_edge_hunter as japan
import v4_global_retrieval_hardening as v1
import v4_global_retrieval_hardening_v2 as v2
from v4_global_live_shadow import SourceStatus, _norm, _price_from_usd_text
from v4_market_comc_bridge import comc_fixed_offer
from v4_market_fanatics_bridge import fanatics_fixed_offer
from v4_market_magi_bridge import magi_fixed_ask_to_observation


SINGLE_CARD_RE = re.compile(r"(?<!\d)1\s*枚")
PSA10_RE = re.compile(r"(?<![A-Z0-9])PSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?(?![0-9])", re.I)
USD_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
MAGI_SET_CODE_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9.-]{1,10})/[^\]]+\]", re.I)
TCGDEX_BASE = "https://api.tcgdex.net/v2/ja"


@dataclass(frozen=True)
class JapaneseCatalogProof:
    status: str
    reason: str = ""
    card_id: str = ""
    set_id: str = ""
    name_ja: str = ""
    set_name_ja: str = ""
    local_id: str = ""
    official_count: str = ""


class TCGdexJapaneseProofResolver:
    """Small read-only catalog resolver used only by the global shadow lane.

    It never guesses a translation. A magi candidate receives catalog proof only
    when an exact set/localId endpoint or a unique full-number catalog result
    resolves deterministically.
    """

    def __init__(self, *, max_requests: int = 60, timeout: float = 8.0) -> None:
        self.max_requests = max(1, int(max_requests))
        self.timeout = max(1.0, float(timeout))
        self.requests_used = 0
        self.session = requests.Session()
        self.cache: dict[tuple[str, str], JapaneseCatalogProof] = {}

    def close(self) -> None:
        self.session.close()

    def _get(self, path: str, *, params: Optional[Mapping[str, object]] = None) -> tuple[int, object]:
        if self.requests_used >= self.max_requests:
            return 0, {"error": "budget_exhausted"}
        self.requests_used += 1
        try:
            response = self.session.get(
                f"{TCGDEX_BASE}/{path.lstrip('/')}",
                params=params,
                headers={"Accept": "application/json", "User-Agent": "gcc-auction-watcher-shadow/1"},
                timeout=self.timeout,
            )
            try:
                payload: object = response.json()
            except Exception:
                payload = {}
            return int(response.status_code), payload
        except Exception:
            return -1, {}

    @staticmethod
    def _detail_payload(payload: object) -> Optional[Mapping[str, Any]]:
        if isinstance(payload, Mapping):
            data = payload.get("data")
            if isinstance(data, Mapping):
                return data
            if payload.get("id"):
                return payload
        return None

    @staticmethod
    def _list_payload(payload: object) -> list[Mapping[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, Mapping)]
        if isinstance(payload, Mapping):
            data = payload.get("data")
            if isinstance(data, list):
                return [row for row in data if isinstance(row, Mapping)]
            for key in ("items", "cards", "sets", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, Mapping)]
        return []

    @staticmethod
    def _number_parts(identity: japan.Identity) -> tuple[str, str]:
        raw = japan.number(identity.number)
        if "/" not in raw:
            return raw, ""
        return tuple(raw.split("/", 1))  # type: ignore[return-value]

    @staticmethod
    def _local_variants(local: str) -> list[str]:
        output = [local]
        if local.isdigit():
            value = str(int(local))
            for candidate in (value, value.zfill(2), value.zfill(3)):
                if candidate not in output:
                    output.append(candidate)
        return output

    @staticmethod
    def _official(detail: Mapping[str, Any]) -> str:
        set_payload = detail.get("set")
        if not isinstance(set_payload, Mapping):
            return ""
        counts = set_payload.get("cardCount")
        if not isinstance(counts, Mapping):
            return ""
        value = counts.get("official")
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _catalog_card(detail: Mapping[str, Any], denominator: str) -> Optional[JapaneseCatalogProof]:
        card_id = str(detail.get("id") or "").strip()
        local_id = str(detail.get("localId") or "").strip()
        name = str(detail.get("name") or "").strip()
        set_payload = detail.get("set")
        if not isinstance(set_payload, Mapping):
            return None
        set_id = str(set_payload.get("id") or "").strip()
        set_name = str(set_payload.get("name") or "").strip()
        official = TCGdexJapaneseProofResolver._official(detail)
        if not all((card_id, local_id, name, set_id, set_name)):
            return None
        if denominator.isdigit():
            if not official or str(int(official)) != str(int(denominator)):
                return None
        return JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_JA_EXACT",
            card_id=card_id,
            set_id=set_id,
            name_ja=name,
            set_name_ja=set_name,
            local_id=local_id,
            official_count=official,
        )

    def _try_set_code(self, identity: japan.Identity, title: str) -> Optional[JapaneseCatalogProof]:
        match = MAGI_SET_CODE_RE.search(unicodedata.normalize("NFKC", title or ""))
        if not match:
            return None
        code = match.group(1).strip()
        local, denominator = self._number_parts(identity)
        for set_id in dict.fromkeys((code, code.casefold())):
            for q_local in self._local_variants(local):
                status, payload = self._get(f"sets/{quote(set_id, safe='')}/{quote(q_local, safe='')}")
                if status == 0:
                    return JapaneseCatalogProof("BUDGET", reason="TCGDEX_BUDGET_EXHAUSTED")
                if status == 404:
                    continue
                if status != 200:
                    if status in {-1, 429} or status >= 500:
                        return JapaneseCatalogProof("ERROR", reason=f"TCGDEX_HTTP_{status}")
                    continue
                detail = self._detail_payload(payload)
                if detail is None:
                    continue
                proof = self._catalog_card(detail, denominator)
                if proof is None:
                    continue
                candidate_local = japan.number(proof.local_id)
                target_local = japan.number(local)
                if candidate_local == target_local or (candidate_local.isdigit() and target_local.isdigit() and int(candidate_local) == int(target_local)):
                    return JapaneseCatalogProof(**{**proof.__dict__, "reason": "TCGDEX_JA_EXACT_SET_CODE_LOCALID"})
        return None

    def _resolve_numeric_denominator(self, identity: japan.Identity) -> JapaneseCatalogProof:
        local, denominator = self._number_parts(identity)
        status, payload = self._get("sets", params={"cardCount.official": f"eq:{int(denominator)}"})
        if status == 0:
            return JapaneseCatalogProof("BUDGET", reason="TCGDEX_BUDGET_EXHAUSTED")
        if status != 200:
            return JapaneseCatalogProof("ERROR", reason=f"TCGDEX_SETS_HTTP_{status}")
        sets = self._list_payload(payload)
        exact_sets: list[Mapping[str, Any]] = []
        for row in sets:
            counts = row.get("cardCount")
            if not isinstance(counts, Mapping):
                continue
            official = counts.get("official")
            try:
                same = int(str(official)) == int(denominator)
            except (TypeError, ValueError):
                same = False
            if same and str(row.get("id") or "").strip():
                exact_sets.append(row)
        if not exact_sets:
            return JapaneseCatalogProof("NO_MATCH", reason="TCGDEX_NO_SET_WITH_OFFICIAL_DENOMINATOR")
        if len(exact_sets) > 30:
            return JapaneseCatalogProof("AMBIGUOUS", reason="TCGDEX_TOO_MANY_DENOMINATOR_SETS")

        found: dict[str, JapaneseCatalogProof] = {}
        for set_row in exact_sets:
            set_id = str(set_row.get("id") or "").strip()
            for q_local in self._local_variants(local):
                status, card_payload = self._get(f"sets/{quote(set_id, safe='')}/{quote(q_local, safe='')}")
                if status == 0:
                    return JapaneseCatalogProof("BUDGET", reason="TCGDEX_BUDGET_EXHAUSTED")
                if status == 404:
                    continue
                if status != 200:
                    if status in {-1, 429} or status >= 500:
                        return JapaneseCatalogProof("ERROR", reason=f"TCGDEX_CARD_HTTP_{status}")
                    continue
                detail = self._detail_payload(card_payload)
                if detail is None:
                    continue
                proof = self._catalog_card(detail, denominator)
                if proof is None:
                    continue
                candidate_local = japan.number(proof.local_id)
                if candidate_local.isdigit() and local.isdigit() and int(candidate_local) != int(local):
                    continue
                found[proof.card_id] = proof
                break
        if len(found) == 1:
            proof = next(iter(found.values()))
            return JapaneseCatalogProof(**{**proof.__dict__, "reason": "TCGDEX_JA_UNIQUE_FULL_NUMBER"})
        if len(found) > 1:
            return JapaneseCatalogProof("AMBIGUOUS", reason="TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER")
        return JapaneseCatalogProof("NO_MATCH", reason="TCGDEX_NO_CARD_FOR_FULL_NUMBER")

    def _resolve_alphanumeric_denominator(self, identity: japan.Identity) -> JapaneseCatalogProof:
        local, denominator = self._number_parts(identity)
        raw = japan.number(identity.number)
        query_values = [raw]
        if local.isdigit():
            padded = f"{int(local):03d}/{denominator}"
            if padded not in query_values:
                query_values.append(padded)
        found: dict[str, JapaneseCatalogProof] = {}
        for value in query_values:
            status, payload = self._get("cards", params={"localId": f"eq:{value}"})
            if status == 0:
                return JapaneseCatalogProof("BUDGET", reason="TCGDEX_BUDGET_EXHAUSTED")
            if status != 200:
                return JapaneseCatalogProof("ERROR", reason=f"TCGDEX_CARDS_HTTP_{status}")
            briefs = self._list_payload(payload)
            if len(briefs) > 10:
                return JapaneseCatalogProof("AMBIGUOUS", reason="TCGDEX_TOO_MANY_ALPHANUMERIC_LOCALID")
            for brief in briefs:
                card_id = str(brief.get("id") or "").strip()
                if not card_id:
                    continue
                det_status, detail_payload = self._get(f"cards/{quote(card_id, safe='')}")
                if det_status == 0:
                    return JapaneseCatalogProof("BUDGET", reason="TCGDEX_BUDGET_EXHAUSTED")
                if det_status != 200:
                    continue
                detail = self._detail_payload(detail_payload)
                if detail is None:
                    continue
                proof = self._catalog_card(detail, denominator)
                if proof is None:
                    continue
                if japan.number(proof.local_id) != japan.number(value):
                    continue
                found[proof.card_id] = proof
        if len(found) == 1:
            proof = next(iter(found.values()))
            return JapaneseCatalogProof(**{**proof.__dict__, "reason": "TCGDEX_JA_UNIQUE_ALPHANUMERIC_LOCALID"})
        if len(found) > 1:
            return JapaneseCatalogProof("AMBIGUOUS", reason="TCGDEX_MULTIPLE_ALPHANUMERIC_LOCALID")
        return JapaneseCatalogProof("NO_MATCH", reason="TCGDEX_NO_ALPHANUMERIC_LOCALID")

    def resolve(self, identity: japan.Identity, *, title: str = "") -> JapaneseCatalogProof:
        cache_key = (japan.number(identity.number), title[:120])
        if cache_key in self.cache:
            return self.cache[cache_key]
        local, denominator = self._number_parts(identity)
        if not local or not denominator:
            result = JapaneseCatalogProof("NO_MATCH", reason="TCGDEX_INCOMPLETE_FULL_NUMBER")
            self.cache[cache_key] = result
            return result
        direct = self._try_set_code(identity, title)
        if direct is not None:
            self.cache[cache_key] = direct
            return direct
        if denominator.isdigit():
            result = self._resolve_numeric_denominator(identity)
        else:
            result = self._resolve_alphanumeric_denominator(identity)
        self.cache[cache_key] = result
        return result


def fanatics_title_identity_proof_v3(title: str, identity: japan.Identity) -> tuple[bool, str]:
    normalized_title = unicodedata.normalize("NFKC", str(title or "")).splitlines()[0].strip()
    full_ok, full_reason = v1._full_fraction_status(normalized_title, identity)
    if not full_ok:
        return False, full_reason
    if not PSA10_RE.search(normalized_title):
        return False, "psa10_unproven"
    if not v1.JAPANESE_RE.search(normalized_title):
        return False, "language_unproven"
    ok, proof = v2._fanatics_set_middle(normalized_title, identity)
    if not ok:
        return False, proof
    if not v1._contains_sensitive_claims(normalized_title, identity):
        return False, "sensitive_variant_unproven"
    return True, "EXACT_FANATICS_H1_SET_LOCAL_ID_PROOF"


def collect_fanatics_v3(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("fanatics")
    for seed in seeds:
        try:
            links, query_count = v2.fanatics_candidate_links_v2(page, seed, max_candidates, trace)
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
            ok, proof = fanatics_title_identity_proof_v3(title, seed.source_identity)
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
        "fanatics",
        "OK",
        "public Buy Now read-only; H1-scoped exact identity proof",
        searches,
        candidates,
        exact,
    ), trace


def _jp_text_contains(text: str, value: str) -> bool:
    haystack = unicodedata.normalize("NFKC", str(text or "")).casefold()
    needle = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return bool(needle) and needle in haystack


def magi_identity_check_v3(
    ask: japan.Ask,
    identity: japan.Identity,
    *,
    catalog: Optional[JapaneseCatalogProof] = None,
) -> tuple[bool, str]:
    title = japan.current_text(ask.title)
    text = japan.current_text("\n".join(x for x in (ask.title, ask.text) if x))
    if japan.has_any(title, japan.AUCTION):
        return False, "ongoing_auction"
    if japan.has_any(title, japan.MULTI):
        return False, "multi_item_listing"
    if not SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return False, "single_quantity_unproven"
    if identity.number not in japan.number_tokens(text):
        return False, "collector_number_unproven"
    if not PSA10_RE.search(unicodedata.normalize("NFKC", text)):
        return False, "psa10_unproven"
    if not japan.has_any(text, japan.JP):
        return False, "language_unproven"

    catalog = catalog or JapaneseCatalogProof("NO_MATCH", reason="CATALOG_NOT_RUN")
    if catalog.status == "EXACT":
        if not _jp_text_contains(text, catalog.name_ja):
            return False, "tcgdex_japanese_name_unproven"
        identity_reason = catalog.reason
    else:
        # Legacy exact textual proof remains a fail-closed fallback. No fuzzy
        # English/Japanese translation is accepted.
        if not (japan.contains(text, identity.set_name) or japan.contains(text, identity.name)):
            return False, f"card_or_set_unproven:{catalog.reason or catalog.status}"
        identity_reason = "LEGACY_EXACT_TEXT_PROOF"

    edition = japan.norm(identity.edition)
    if edition and (identity.year <= 2003 or edition not in {"unlimited", "standard"}) and not japan.contains(text, edition):
        return False, "edition_unproven"
    for raw in (identity.attribute, identity.variety):
        normalized = japan.norm(raw)
        if normalized and any(
            value in normalized
            for value in (
                "1st edition",
                "first edition",
                "shadowless",
                "incorrect texture",
                "error",
                "stamp",
                "stamped",
                "reverse",
                "master ball",
                "pokeball",
            )
        ) and not japan.contains(text, normalized):
            return False, "microvariant_unproven"
    return True, f"MAGI_SINGLE_PLUS_{identity_reason}"


def collect_magi_v3(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("magi")
    resolver = TCGdexJapaneseProofResolver(max_requests=60)
    try:
        for seed in seeds:
            try:
                asks, query_count = v2.magi_candidates_v2(page, seed, max_candidates, trace)
                searches += query_count
            except Exception as error:
                trace.reject(seed, f"search_error:{type(error).__name__}")
                return found, SourceStatus("magi", "ERROR", type(error).__name__, searches, candidates, exact), trace
            trace.retrieved(seed, len(asks))
            catalog_cache: dict[str, JapaneseCatalogProof] = {}
            for ask in asks:
                candidates += 1
                try:
                    detailed = v1.magi_detail_only(page, ask)
                except Exception:
                    trace.reject(seed, "detail_error", title=ask.title, url=ask.url)
                    continue
                code_key = MAGI_SET_CODE_RE.search(detailed.title or "")
                key = code_key.group(1).casefold() if code_key else "__full_number__"
                if key not in catalog_cache:
                    catalog_cache[key] = resolver.resolve(seed.source_identity, title=detailed.title)
                catalog = catalog_cache[key]
                ok, proof = magi_identity_check_v3(detailed, seed.source_identity, catalog=catalog)
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
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "tcgdex_requests_used_total": resolver.requests_used,
                    "tcgdex_proofs": {
                        key: {"status": value.status, "reason": value.reason, "card_id": value.card_id, "set_id": value.set_id, "name_ja": value.name_ja}
                        for key, value in catalog_cache.items()
                    },
                }
            )
    finally:
        resolver.close()
    return found, SourceStatus(
        "magi",
        "OK",
        f"public read-only; title single-card proof + deterministic TCGdex JA catalog proof; tcgdex_calls={resolver.requests_used}",
        searches,
        candidates,
        exact,
    ), trace


def _comc_text_view_url(player_url: str) -> str:
    base = str(player_url or "").rstrip("/")
    return base if "%2CvText" in base or ",vText" in base else base + "%2Csn%2CvText"


def _contains_token(text: str, target: str) -> bool:
    haystack = _norm(text)
    needle = _norm(target)
    return bool(needle) and bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack, re.I))


def _intrinsic_set_code(identity: japan.Identity) -> bool:
    value = str(identity.number or "")
    if "/" not in value:
        return False
    denominator = value.split("/", 1)[1]
    return bool(re.search(r"[A-Za-z]", denominator))


def _local_id_matches_text(text: str, identity: japan.Identity) -> bool:
    local = v1.target_local_id(identity)
    if local is None:
        return False
    normalized = unicodedata.normalize("NFKC", text or "")
    if local.isdigit():
        return bool(re.search(rf"(?<![A-Za-z0-9])#?0*{re.escape(str(int(local)))}(?![A-Za-z0-9])", normalized, re.I))
    return bool(re.search(rf"(?<![A-Za-z0-9])#?{re.escape(local)}(?![A-Za-z0-9])", normalized, re.I))


def _full_number_matches_text(text: str, identity: japan.Identity) -> bool:
    return japan.number(identity.number) in japan.number_tokens(text)


def _comc_identity_block_proof(text: str, identity: japan.Identity) -> tuple[bool, str, Optional[float]]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    if "japanese" not in _norm(normalized):
        return False, "language_unproven", None
    if not PSA10_RE.search(normalized):
        return False, "psa10_unproven", None
    if not re.search(rf"(?<![A-Za-z0-9]){v1._source_name_pattern(identity.name)}(?![A-Za-z0-9])", normalized, re.I):
        return False, "card_name_unproven", None

    full_exact = _full_number_matches_text(normalized, identity)
    if not full_exact and not _local_id_matches_text(normalized, identity):
        return False, "local_id_unproven", None
    if not full_exact:
        if not _contains_token(normalized, identity.set_name):
            return False, "set_unproven", None
    elif not _contains_token(normalized, identity.set_name) and not _intrinsic_set_code(identity):
        # Numeric denominator listings need the exact set name when the provider
        # only proves the same full number textually.
        return False, "set_unproven", None

    if not v1._contains_sensitive_claims(normalized, identity):
        return False, "sensitive_variant_unproven", None

    prices: list[float] = []
    for match in USD_RE.finditer(normalized):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if value > 0 and value not in prices:
            prices.append(value)
    if not prices:
        return False, "price_unproven", None
    if len(prices) != 1:
        return False, "ambiguous_price_block", None
    return True, "COMC_DOM_BLOCK_EXACT", prices[0]


def _comc_dom_blocks(page: Any, identity: japan.Identity) -> list[Mapping[str, str]]:
    local = v1.target_local_id(identity) or ""
    target_full = japan.number(identity.number)
    return page.evaluate(
        r"""({localId, fullNumber}) => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          const local = String(localId || '');
          const full = String(fullNumber || '').toUpperCase();
          const localRe = local && /^\d+$/.test(local)
            ? new RegExp('(?:^|[^A-Za-z0-9])#?0*' + String(parseInt(local,10)) + '(?![A-Za-z0-9])', 'i')
            : (local ? new RegExp('(?:^|[^A-Za-z0-9])#?' + esc(local) + '(?![A-Za-z0-9])', 'i') : null);
          const qualifies = text => {
            if (!text || text.length < 15 || text.length > 2200) return false;
            const upper = text.toUpperCase();
            if (!/JAPANESE/i.test(text)) return false;
            if (!/PSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?/i.test(text)) return false;
            if (!/\$\s*[0-9]/.test(text)) return false;
            if (full && upper.includes(full)) return true;
            return !!(localRe && localRe.test(text));
          };
          const selectors = 'tr, li, article, section, div';
          const raw = [];
          for (const el of document.querySelectorAll(selectors)) {
            const text = clean(el.innerText || el.textContent || '');
            if (!qualifies(text)) continue;
            let childAlso = false;
            for (const child of el.children || []) {
              const childText = clean(child.innerText || child.textContent || '');
              if (qualifies(childText)) { childAlso = true; break; }
            }
            if (childAlso) continue;
            const a = el.querySelector('a[href]');
            raw.push({text, href: a ? a.href : ''});
          }
          raw.sort((a,b) => a.text.length - b.text.length);
          const out = [], seen = new Set();
          for (const row of raw) {
            const key = row.text.toLowerCase();
            if (seen.has(key)) continue;
            seen.add(key);
            out.push(row);
            if (out.length >= 60) break;
          }
          return out;
        }""",
        {"localId": local, "fullNumber": target_full},
    )


def _comc_table_rows(page: Any) -> list[Mapping[str, Any]]:
    return page.evaluate(
        r"""() => Array.from(document.querySelectorAll('tr')).map(tr => ({
          cells: Array.from(tr.querySelectorAll('th,td')).map(td => (td.innerText || td.textContent || '').replace(/\s+/g,' ').trim()),
          href: (tr.querySelector('a[href]') || {}).href || ''
        })).filter(row => row.cells.length >= 3)"""
    )


def _comc_row_text(row: Mapping[str, Any]) -> str:
    cells = row.get("cells")
    if not isinstance(cells, list):
        return ""
    return " | ".join(str(cell or "").strip() for cell in cells if str(cell or "").strip())


def collect_comc_v3(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("comc")
    for seed in seeds:
        player_url = v1._comc_player_url(page, seed.source_identity.name)
        if not player_url:
            trace.reject(seed, "player_url_unresolved")
            trace.query_pages.append({"identity": trace._label(seed), "player_url": "", "rows_seen": 0})
            searches += 1
            continue
        url = _comc_text_view_url(player_url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(900)
            title = page.title()
            final_url = page.url
            table_rows = _comc_table_rows(page)
            blocks = _comc_dom_blocks(page, seed.source_identity)
        except Exception as error:
            trace.reject(seed, f"page_error:{type(error).__name__}", url=url)
            searches += 1
            continue
        searches += 1

        candidates_for_seed: list[tuple[str, str, float]] = []
        reasons: Counter[str] = Counter()
        seen_text: set[str] = set()
        structured_rows = 0
        for row in table_rows:
            text = _comc_row_text(row)
            if not text:
                continue
            structured_rows += 1
            ok, proof, price = _comc_identity_block_proof(text, seed.source_identity)
            if not ok:
                reasons[proof] += 1
                continue
            assert price is not None
            key = unicodedata.normalize("NFKC", text).casefold()
            if key in seen_text:
                continue
            seen_text.add(key)
            href = str(row.get("href") or url)
            candidates_for_seed.append((href, text, price))
            if len(candidates_for_seed) >= max_candidates:
                break

        if len(candidates_for_seed) < max_candidates:
            for block in blocks:
                text = str(block.get("text") or "")
                if not text:
                    continue
                key = unicodedata.normalize("NFKC", text).casefold()
                if key in seen_text:
                    continue
                ok, proof, price = _comc_identity_block_proof(text, seed.source_identity)
                if not ok:
                    reasons[proof] += 1
                    continue
                assert price is not None
                seen_text.add(key)
                href = str(block.get("href") or url)
                candidates_for_seed.append((href, text, price))
                if len(candidates_for_seed) >= max_candidates:
                    break

        trace.query_pages.append(
            {
                "identity": trace._label(seed),
                "player_url": player_url,
                "text_view_url": url,
                "final_url": str(final_url)[:500],
                "title": str(title)[:200],
                "table_rows_seen": structured_rows,
                "dom_blocks_seen": len(blocks),
                "candidate_rows": len(candidates_for_seed),
                "row_reject_reasons": dict(reasons.most_common(8)),
                "sample_blocks": [str(row.get("text") or "")[:350] for row in blocks[:3]],
            }
        )
        trace.retrieved(seed, len(candidates_for_seed))
        if not candidates_for_seed:
            trace.reject(seed, "search_no_actionable_psa10_candidate")
            continue
        for source_url, row_text, price in candidates_for_seed:
            candidates += 1
            observation = comc_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=source_url,
                identity_proven=True,
                buyer_fee_rate=None,
                note="COMC Buy Now ASK; same DOM row/block proves set/language/number/name/PSA10/price; buyer/logistics all-in unproven",
            )
            found[seed.identity.strict_key].append((observation, source_url, row_text[:500]))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "comc",
        "OK",
        "public read-only; table/minimal-DOM block binds exact identity, grade and ask price",
        searches,
        candidates,
        exact,
    ), trace
