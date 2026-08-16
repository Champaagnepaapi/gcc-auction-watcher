from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

import v4_global_retrieval_hardening as v1
import v4_global_retrieval_hardening_v2 as retrieval_v2
import v4_global_retrieval_hardening_v3 as retrieval_v3
from v4_global_live_shadow import SourceStatus, _norm
from v4_global_magi_target_hardening import (
    TCGDEX_EN,
    TargetCatalogProof,
    _catalog_name_compatible,
    _set_aliases,
    magi_target_identity_check,
)
from v4_market_magi_bridge import magi_fixed_ask_to_observation


def _target_set_compatible(target: str, catalog: str) -> bool:
    aliases = _set_aliases(target)
    catalog_norm = _norm(catalog)
    if not aliases or not catalog_norm:
        return False
    if catalog_norm in aliases:
        return True
    wrapper = re.sub(r"^pokemon(?: tcg)? cards?\s+", "", catalog_norm).strip()
    return bool(wrapper) and wrapper in aliases


def _same_local_id(value: object, target_number: str) -> bool:
    raw = unicodedata.normalize("NFKC", str(value or "")).upper().replace(" ", "").lstrip("#")
    target_full = v1._number(target_number)
    if not raw or not target_full:
        return False
    if "/" in raw:
        return v1._number(raw) == target_full
    target_local = target_full.split("/", 1)[0]
    if raw.isdigit() and target_local.isdigit():
        return int(raw) == int(target_local)
    return raw.casefold() == target_local.casefold()


class SameCardIdTargetBridge:
    """Bind a Japanese TCGdex candidate to the target through the same card ID."""

    def __init__(self, *, max_requests: int = 40, timeout: float = 8.0) -> None:
        self.max_requests = max(1, int(max_requests))
        self.timeout = max(1.0, float(timeout))
        self.requests_used = 0
        self.session = requests.Session()
        self.cache: dict[str, TargetCatalogProof] = {}

    def close(self) -> None:
        self.session.close()

    def _get(self, card_id: str) -> tuple[int, object]:
        if self.requests_used >= self.max_requests:
            return 0, {"error": "budget_exhausted"}
        self.requests_used += 1
        try:
            response = self.session.get(
                f"{TCGDEX_EN}/cards/{quote(card_id, safe='')}",
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
    def _payload_object(payload: object) -> Optional[Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            return None
        data = payload.get("data")
        if isinstance(data, Mapping):
            return data
        return payload

    def resolve(
        self,
        identity,
        ja_catalog: retrieval_v3.JapaneseCatalogProof,
    ) -> TargetCatalogProof:
        cache_key = "|".join(
            (
                _norm(identity.name),
                _norm(identity.set_name),
                v1._number(identity.number),
                ja_catalog.card_id.casefold(),
            )
        )
        if cache_key in self.cache:
            return self.cache[cache_key]

        if ja_catalog.status != "EXACT":
            result = TargetCatalogProof(ja_catalog.status, ja_catalog.reason or "TCGDEX_JA_TARGET_UNPROVEN")
            self.cache[cache_key] = result
            return result

        if not all(
            (
                ja_catalog.card_id,
                ja_catalog.set_id,
                ja_catalog.name_ja,
                ja_catalog.set_name_ja,
                ja_catalog.local_id,
            )
        ):
            result = TargetCatalogProof("NO_MATCH", "TCGDEX_JA_TARGET_METADATA_INCOMPLETE")
            self.cache[cache_key] = result
            return result
        if not _same_local_id(ja_catalog.local_id, identity.number):
            result = TargetCatalogProof("CONFLICT", "TCGDEX_JA_TARGET_LOCAL_ID_CONFLICT")
            self.cache[cache_key] = result
            return result

        status, payload = self._get(ja_catalog.card_id)
        if status == 0:
            result = TargetCatalogProof("ERROR", "TCGDEX_EN_SAME_CARD_ID_BUDGET_EXHAUSTED")
            self.cache[cache_key] = result
            return result
        if status == 404:
            result = TargetCatalogProof("NO_MATCH", "TCGDEX_EN_SAME_CARD_ID_NOT_FOUND")
            self.cache[cache_key] = result
            return result
        if status != 200:
            result = TargetCatalogProof("ERROR", f"TCGDEX_EN_SAME_CARD_ID_HTTP_{status}")
            self.cache[cache_key] = result
            return result

        en_card = self._payload_object(payload)
        if en_card is None:
            result = TargetCatalogProof("ERROR", "TCGDEX_EN_SAME_CARD_ID_PAYLOAD_INVALID")
            self.cache[cache_key] = result
            return result

        en_card_id = str(en_card.get("id") or "").strip()
        en_name = str(en_card.get("name") or "").strip()
        en_local = str(en_card.get("localId") or "").strip()
        en_set = en_card.get("set")
        en_set = en_set if isinstance(en_set, Mapping) else {}
        en_set_id = str(en_set.get("id") or "").strip()
        en_set_name = str(en_set.get("name") or "").strip()

        if en_card_id.casefold() != ja_catalog.card_id.casefold():
            reason = "TCGDEX_CROSS_LANGUAGE_CARD_ID_CONFLICT"
        elif en_set_id.casefold() != ja_catalog.set_id.casefold():
            reason = "TCGDEX_CROSS_LANGUAGE_SET_ID_CONFLICT"
        elif not _same_local_id(en_local, identity.number):
            reason = "TCGDEX_TARGET_EN_LOCAL_ID_CONFLICT"
        elif not _catalog_name_compatible(identity.name, en_name):
            reason = "TCGDEX_TARGET_EN_NAME_CONFLICT"
        elif not _target_set_compatible(identity.set_name, en_set_name):
            reason = "TCGDEX_TARGET_EN_SET_CONFLICT"
        else:
            result = TargetCatalogProof(
                "EXACT",
                "TCGDEX_SAME_CARD_ID_JA_EN_TARGET_EXACT",
                set_id=ja_catalog.set_id,
                set_name_en=en_set_name,
                set_name_ja=ja_catalog.set_name_ja,
                card_id_en=en_card_id,
                card_id_ja=ja_catalog.card_id,
                card_name_en=en_name,
                card_name_ja=ja_catalog.name_ja,
                local_id_en=en_local,
                local_id_ja=ja_catalog.local_id,
                official_count=ja_catalog.official_count,
            )
            self.cache[cache_key] = result
            return result

        result = TargetCatalogProof("CONFLICT", reason)
        self.cache[cache_key] = result
        return result


def collect_magi_target_hardened_v2(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = retrieval_v2.MarketTrace("magi")
    ja_resolver = retrieval_v3.TCGdexJapaneseProofResolver(max_requests=max(60, len(seeds) * 16))
    bridge = SameCardIdTargetBridge(max_requests=max(20, len(seeds) * 8))

    try:
        for seed in seeds:
            try:
                asks, query_count = retrieval_v2.magi_candidates_v2(page, seed, max_candidates, trace)
                searches += query_count
            except Exception as error:
                trace.reject(seed, f"search_error:{type(error).__name__}")
                return found, SourceStatus("magi", "ERROR", type(error).__name__, searches, candidates, exact), trace

            trace.retrieved(seed, len(asks))
            ja_cache: dict[str, retrieval_v3.JapaneseCatalogProof] = {}
            target_cache: dict[str, TargetCatalogProof] = {}

            for ask in asks:
                candidates += 1
                try:
                    detailed = v1.magi_detail_only(page, ask)
                except Exception:
                    trace.reject(seed, "detail_error", title=ask.title, url=ask.url)
                    continue

                code_match = retrieval_v3.MAGI_SET_CODE_RE.search(unicodedata.normalize("NFKC", detailed.title or ""))
                proof_key = code_match.group(1).casefold() if code_match else "__full_number__"
                if proof_key not in ja_cache:
                    ja_cache[proof_key] = ja_resolver.resolve(seed.source_identity, title=detailed.title)
                if proof_key not in target_cache:
                    target_cache[proof_key] = bridge.resolve(seed.source_identity, ja_cache[proof_key])
                target_catalog = target_cache[proof_key]

                ok, proof = magi_target_identity_check(detailed, seed.source_identity, target_catalog)
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
                    "tcgdex_ja_requests_used_total": ja_resolver.requests_used,
                    "tcgdex_en_bridge_requests_used_total": bridge.requests_used,
                    "tcgdex_candidate_proofs": {
                        key: {
                            "ja_status": ja_cache[key].status,
                            "ja_reason": ja_cache[key].reason,
                            "ja_card_id": ja_cache[key].card_id,
                            "ja_set_id": ja_cache[key].set_id,
                            "ja_name": ja_cache[key].name_ja,
                            "target_status": target_cache[key].status,
                            "target_reason": target_cache[key].reason,
                            "target_name_en": target_cache[key].card_name_en,
                            "target_set_en": target_cache[key].set_name_en,
                        }
                        for key in ja_cache
                    },
                }
            )
    finally:
        bridge.close()
        ja_resolver.close()

    return found, SourceStatus(
        "magi",
        "OK",
        (
            "public read-only; Japanese full-number/set-code proof + same TCGdex card ID "
            f"English target proof; ja_calls={ja_resolver.requests_used}; en_bridge_calls={bridge.requests_used}"
        ),
        searches,
        candidates,
        exact,
    ), trace
