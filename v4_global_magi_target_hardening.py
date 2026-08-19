from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

import japan_edge_hunter as japan
import v4_global_retrieval_hardening as v1
import v4_global_retrieval_hardening_v2 as v2
from v4_global_live_shadow import SourceStatus, _norm
from v4_market_magi_bridge import magi_fixed_ask_to_observation


TCGDEX_EN = "https://api.tcgdex.net/v2/en"
TCGDEX_JA = "https://api.tcgdex.net/v2/ja"
PSA10_RE = re.compile(r"(?<![A-Z0-9])PSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?(?![0-9])", re.I)
SINGLE_CARD_RE = re.compile(r"(?<!\d)1\s*枚")
MAGI_SET_CODE_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9.-]{1,10})/[^\]]+\]", re.I)


@dataclass(frozen=True)
class TargetCatalogProof:
    status: str
    reason: str
    set_id: str = ""
    set_name_en: str = ""
    set_name_ja: str = ""
    card_id_en: str = ""
    card_id_ja: str = ""
    card_name_en: str = ""
    card_name_ja: str = ""
    local_id_en: str = ""
    local_id_ja: str = ""
    official_count: str = ""


def _payload_object(payload: object) -> Optional[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    if isinstance(data, Mapping):
        return data
    return payload


def _payload_list(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, Mapping)]
    return []


def _set_aliases(value: str) -> set[str]:
    base = _norm(value)
    output = {base} if base else set()
    if base.endswith(" promotional"):
        output.add(base + " cards")
    if base.endswith(" promotional cards"):
        output.add(base.removesuffix(" cards"))
    if base.endswith(" ex"):
        output.add(base[:-3] + " ex")
    return {item for item in output if item}


def _number_parts(identity: japan.Identity) -> tuple[str, str]:
    value = v1._number(identity.number)
    if "/" not in value:
        return value, ""
    left, right = value.split("/", 1)
    return left, right


def _local_variants(identity: japan.Identity) -> list[str]:
    local, denominator = _number_parts(identity)
    values: list[str] = []
    if local:
        values.append(local)
        if local.isdigit():
            canonical = str(int(local))
            for value in (canonical, canonical.zfill(2), canonical.zfill(3)):
                if value not in values:
                    values.append(value)
    full = v1._number(identity.number)
    if full and full not in values:
        values.append(full)
    if local.isdigit() and denominator and re.search(r"[A-Za-z]", denominator):
        for left in (str(int(local)), str(int(local)).zfill(2), str(int(local)).zfill(3)):
            value = f"{left}/{denominator}"
            if value not in values:
                values.append(value)
    return values


def _catalog_name_compatible(target: str, catalog: str) -> bool:
    target_tokens = _norm(target).split()
    catalog_tokens = _norm(catalog).split()
    if not target_tokens or not catalog_tokens:
        return False
    if target_tokens == catalog_tokens:
        return True
    # Deterministic token subsequence only. This handles provider labels such as
    # `Dragonite` -> `Mega Dragonite ex` without allowing `Mew` -> `Mewtwo`.
    if len(target_tokens) <= len(catalog_tokens):
        for start in range(len(catalog_tokens) - len(target_tokens) + 1):
            if catalog_tokens[start : start + len(target_tokens)] == target_tokens:
                return True
    return False


class TargetTCGdexResolver:
    def __init__(self, *, max_requests: int = 30, timeout: float = 8.0) -> None:
        self.max_requests = max(1, int(max_requests))
        self.timeout = max(1.0, float(timeout))
        self.requests_used = 0
        self.session = requests.Session()
        self.cache: dict[str, TargetCatalogProof] = {}

    def close(self) -> None:
        self.session.close()

    def _get(self, base: str, path: str, *, params: Optional[Mapping[str, object]] = None) -> tuple[int, object]:
        if self.requests_used >= self.max_requests:
            return 0, {"error": "budget_exhausted"}
        self.requests_used += 1
        try:
            response = self.session.get(
                f"{base}/{path.lstrip('/')}",
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
    def _set_count(set_payload: Mapping[str, Any]) -> str:
        counts = set_payload.get("cardCount")
        if not isinstance(counts, Mapping):
            return ""
        value = counts.get("official")
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _card_set(detail: Mapping[str, Any]) -> Mapping[str, Any]:
        value = detail.get("set")
        return value if isinstance(value, Mapping) else {}

    def _resolve_set(self, identity: japan.Identity) -> tuple[Optional[Mapping[str, Any]], str]:
        status, payload = self._get(TCGDEX_EN, "sets", params={"name": identity.set_name})
        if status == 0:
            return None, "TCGDEX_BUDGET_EXHAUSTED"
        if status != 200:
            return None, f"TCGDEX_EN_SETS_HTTP_{status}"
        aliases = _set_aliases(identity.set_name)
        rows = [row for row in _payload_list(payload) if _norm(row.get("name")) in aliases]
        if len(rows) != 1:
            return None, "TCGDEX_TARGET_SET_NOT_UNIQUE"
        return rows[0], ""

    def _resolve_card_in_set(
        self,
        base: str,
        set_id: str,
        identity: japan.Identity,
    ) -> tuple[Optional[Mapping[str, Any]], str]:
        errors: list[str] = []
        for local in _local_variants(identity):
            status, payload = self._get(base, f"sets/{quote(set_id, safe='')}/{quote(local, safe='')}")
            if status == 0:
                return None, "TCGDEX_BUDGET_EXHAUSTED"
            if status == 404:
                continue
            if status != 200:
                errors.append(f"HTTP_{status}")
                continue
            detail = _payload_object(payload)
            if detail and str(detail.get("id") or "").strip():
                return detail, ""
        return None, "TCGDEX_TARGET_CARD_NOT_FOUND" + (":" + ",".join(errors) if errors else "")

    def resolve(self, identity: japan.Identity) -> TargetCatalogProof:
        key = "|".join((_norm(identity.set_name), v1._number(identity.number), _norm(identity.name)))
        if key in self.cache:
            return self.cache[key]

        set_row, reason = self._resolve_set(identity)
        if set_row is None:
            proof = TargetCatalogProof("NO_MATCH", reason)
            self.cache[key] = proof
            return proof
        set_id = str(set_row.get("id") or "").strip()
        set_name_en = str(set_row.get("name") or "").strip()
        if not set_id:
            proof = TargetCatalogProof("NO_MATCH", "TCGDEX_TARGET_SET_ID_MISSING")
            self.cache[key] = proof
            return proof

        en_card, reason = self._resolve_card_in_set(TCGDEX_EN, set_id, identity)
        if en_card is None:
            proof = TargetCatalogProof("NO_MATCH", reason, set_id=set_id, set_name_en=set_name_en)
            self.cache[key] = proof
            return proof
        en_name = str(en_card.get("name") or "").strip()
        if not _catalog_name_compatible(identity.name, en_name):
            proof = TargetCatalogProof(
                "CONFLICT",
                "TCGDEX_TARGET_EN_NAME_CONFLICT",
                set_id=set_id,
                set_name_en=set_name_en,
                card_id_en=str(en_card.get("id") or ""),
                card_name_en=en_name,
                local_id_en=str(en_card.get("localId") or ""),
            )
            self.cache[key] = proof
            return proof

        ja_card, reason = self._resolve_card_in_set(TCGDEX_JA, set_id, identity)
        if ja_card is None:
            proof = TargetCatalogProof(
                "NO_MATCH",
                reason,
                set_id=set_id,
                set_name_en=set_name_en,
                card_id_en=str(en_card.get("id") or ""),
                card_name_en=en_name,
                local_id_en=str(en_card.get("localId") or ""),
            )
            self.cache[key] = proof
            return proof

        ja_set = self._card_set(ja_card)
        ja_set_id = str(ja_set.get("id") or "").strip()
        if ja_set_id.casefold() != set_id.casefold():
            proof = TargetCatalogProof("CONFLICT", "TCGDEX_CROSS_LANGUAGE_SET_ID_CONFLICT", set_id=set_id)
            self.cache[key] = proof
            return proof

        _, denominator = _number_parts(identity)
        official = self._set_count(ja_set)
        if denominator.isdigit():
            try:
                denominator_ok = official and int(official) == int(denominator)
            except ValueError:
                denominator_ok = False
            if not denominator_ok:
                proof = TargetCatalogProof("CONFLICT", "TCGDEX_OFFICIAL_COUNT_CONFLICT", set_id=set_id)
                self.cache[key] = proof
                return proof

        proof = TargetCatalogProof(
            "EXACT",
            "TCGDEX_TARGET_SET_LOCALID_CROSS_LANGUAGE",
            set_id=set_id,
            set_name_en=set_name_en,
            set_name_ja=str(ja_set.get("name") or "").strip(),
            card_id_en=str(en_card.get("id") or ""),
            card_id_ja=str(ja_card.get("id") or ""),
            card_name_en=en_name,
            card_name_ja=str(ja_card.get("name") or "").strip(),
            local_id_en=str(en_card.get("localId") or ""),
            local_id_ja=str(ja_card.get("localId") or ""),
            official_count=official,
        )
        self.cache[key] = proof
        return proof


def _jp_contains(text: str, value: str) -> bool:
    haystack = unicodedata.normalize("NFKC", str(text or "")).casefold()
    needle = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return bool(needle) and needle in haystack


def magi_target_identity_check(
    ask: japan.Ask,
    identity: japan.Identity,
    catalog: TargetCatalogProof,
) -> tuple[bool, str]:
    title = japan.current_text(ask.title)
    text = japan.current_text("\n".join(x for x in (ask.title, ask.text) if x))
    if japan.has_any(title, japan.AUCTION):
        return False, "ongoing_auction"
    if japan.has_any(title, japan.MULTI):
        return False, "multi_item_listing"
    if not SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return False, "single_quantity_unproven"
    if v1._number(identity.number) not in {v1._number(value) for value in japan.number_tokens(text)}:
        return False, "collector_number_unproven"
    if not PSA10_RE.search(unicodedata.normalize("NFKC", text)):
        return False, "psa10_unproven"
    if catalog.status != "EXACT":
        return False, f"target_catalog_unproven:{catalog.reason}"
    if not catalog.card_name_ja or not _jp_contains(text, catalog.card_name_ja):
        return False, "target_japanese_card_name_unproven"

    title_code = MAGI_SET_CODE_RE.search(unicodedata.normalize("NFKC", title))
    if title_code:
        if title_code.group(1).casefold() != catalog.set_id.casefold():
            return False, "target_set_code_conflict"
    elif not catalog.set_name_ja or not _jp_contains(text, catalog.set_name_ja):
        return False, "target_japanese_set_unproven"

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
    return True, "MAGI_TARGET_TCGDEX_CROSS_LANGUAGE_EXACT"


def collect_magi_target_hardened(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("magi")
    resolver = TargetTCGdexResolver(max_requests=max(30, len(seeds) * 10))
    try:
        for seed in seeds:
            catalog = resolver.resolve(seed.source_identity)
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "target_catalog": {
                        "status": catalog.status,
                        "reason": catalog.reason,
                        "set_id": catalog.set_id,
                        "set_name_en": catalog.set_name_en,
                        "set_name_ja": catalog.set_name_ja,
                        "card_name_en": catalog.card_name_en,
                        "card_name_ja": catalog.card_name_ja,
                        "local_id_en": catalog.local_id_en,
                        "local_id_ja": catalog.local_id_ja,
                    },
                    "tcgdex_requests_used_total": resolver.requests_used,
                }
            )
            try:
                asks, query_count = v2.magi_candidates_v2(page, seed, max_candidates, trace)
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
                ok, proof = magi_target_identity_check(detailed, seed.source_identity, catalog)
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
    finally:
        resolver.close()
    return found, SourceStatus(
        "magi",
        "OK",
        f"public read-only; target set+localId TCGdex EN->JA proof; tcgdex_calls={resolver.requests_used}",
        searches,
        candidates,
        exact,
    ), trace
