from __future__ import annotations

import unicodedata
from typing import Any, Sequence

import japan_edge_hunter as japan
import v4_global_retrieval_hardening as v1
import v4_global_retrieval_hardening_v2 as v2
import v4_global_retrieval_hardening_v3 as v3
from v4_global_live_shadow import SourceStatus
from v4_market_magi_bridge import magi_fixed_ask_to_observation
from v4_tcgdex_japanese_set_registry import (
    REGISTRY_VERSION,
    JapaneseSetRegistryEntry,
    resolve_japanese_set,
)


def _jp_equal(left: object, right: object) -> bool:
    a = unicodedata.normalize("NFKC", str(left or "")).replace(" ", "").casefold()
    b = unicodedata.normalize("NFKC", str(right or "")).replace(" ", "").casefold()
    return bool(a) and a == b


def _jp_contains(text: object, value: object) -> bool:
    haystack = unicodedata.normalize("NFKC", str(text or "")).replace(" ", "").casefold()
    needle = unicodedata.normalize("NFKC", str(value or "")).replace(" ", "").casefold()
    return bool(needle) and needle in haystack


def _denominator(identity: japan.Identity) -> str:
    value = japan.number(identity.number)
    if "/" not in value:
        return ""
    return value.split("/", 1)[1]


def _intrinsic_set_code(identity: japan.Identity, entry: JapaneseSetRegistryEntry) -> bool:
    denominator = _denominator(identity)
    if not denominator or denominator.isdigit():
        return False
    return denominator.casefold() == entry.set_id.casefold()


def _target_catalog_proof(
    resolver: v3.TCGdexJapaneseProofResolver,
    identity: japan.Identity,
    entry: JapaneseSetRegistryEntry,
) -> v3.JapaneseCatalogProof:
    # Force the resolver down the exact set/localId route using only the
    # versioned registry's set ID. Candidate text cannot choose a different set.
    synthetic_title = f"[{entry.set_id}/REGISTRY]"
    proof = resolver.resolve(identity, title=synthetic_title)
    if proof.status != "EXACT":
        return proof
    if proof.set_id.casefold() != entry.set_id.casefold():
        return v3.JapaneseCatalogProof("CONFLICT", reason="REGISTRY_TCGDEX_SET_ID_CONFLICT")
    if not _jp_equal(proof.set_name_ja, entry.ja_set_name):
        return v3.JapaneseCatalogProof("CONFLICT", reason="REGISTRY_TCGDEX_SET_NAME_CONFLICT")
    return v3.JapaneseCatalogProof(**{**proof.__dict__, "reason": "REGISTRY_TCGDEX_EXACT_SET_LOCALID"})


def magi_registry_identity_check(
    ask: japan.Ask,
    identity: japan.Identity,
    catalog: v3.JapaneseCatalogProof,
    entry: JapaneseSetRegistryEntry,
) -> tuple[bool, str]:
    title = japan.current_text(ask.title)
    text = japan.current_text("\n".join(x for x in (ask.title, ask.text) if x))

    if japan.has_any(title, japan.AUCTION):
        return False, "ongoing_auction"
    if japan.has_any(title, japan.MULTI):
        return False, "multi_item_listing"
    if not v3.SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return False, "single_quantity_unproven"

    target_number = v1._number(identity.number)
    observed_numbers = {v1._number(value) for value in japan.number_tokens(text)}
    if target_number not in observed_numbers:
        return False, "collector_number_unproven"
    if not v3.PSA10_RE.search(unicodedata.normalize("NFKC", text)):
        return False, "psa10_unproven"

    if catalog.status != "EXACT":
        return False, f"target_catalog_unproven:{catalog.reason or catalog.status}"
    if catalog.set_id.casefold() != entry.set_id.casefold():
        return False, "target_registry_set_conflict"
    if not catalog.name_ja or not _jp_contains(text, catalog.name_ja):
        return False, "target_japanese_card_name_unproven"

    title_code = v3.MAGI_SET_CODE_RE.search(unicodedata.normalize("NFKC", title))
    if title_code:
        if title_code.group(1).casefold() != entry.set_id.casefold():
            return False, "target_set_code_conflict"
    elif _intrinsic_set_code(identity, entry):
        # Promo-style printed numbers such as 020/M-P contain the exact set code
        # in the number itself, so requiring the Japanese set name in the title
        # would add no identity information and would discard legitimate listings.
        pass
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

    return True, "MAGI_VERSIONED_TCGDEX_JA_SET_EXACT"


def collect_magi_registry_hardened(
    page: Any,
    seeds: Sequence[Any],
    *,
    observed_at,
    max_candidates: int = 8,
):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("magi")
    resolver = v3.TCGdexJapaneseProofResolver(max_requests=max(30, len(seeds) * 8))

    try:
        for seed in seeds:
            entry, registry_reason = resolve_japanese_set(seed.source_identity.set_name, seed.source_identity.number)
            if entry is None:
                trace.reject(seed, registry_reason)
                trace.query_pages.append(
                    {
                        "identity": trace._label(seed),
                        "registry_version": REGISTRY_VERSION,
                        "registry_status": registry_reason,
                    }
                )
                continue

            catalog = _target_catalog_proof(resolver, seed.source_identity, entry)
            trace.query_pages.append(
                {
                    "identity": trace._label(seed),
                    "registry_version": REGISTRY_VERSION,
                    "registry_status": registry_reason,
                    "registry_set_id": entry.set_id,
                    "registry_ja_set_name": entry.ja_set_name,
                    "registry_provenance": entry.provenance_url,
                    "registry_provenance_sha": entry.provenance_merge_sha,
                    "target_catalog": {
                        "status": catalog.status,
                        "reason": catalog.reason,
                        "card_id": catalog.card_id,
                        "set_id": catalog.set_id,
                        "name_ja": catalog.name_ja,
                        "set_name_ja": catalog.set_name_ja,
                        "local_id": catalog.local_id,
                        "official_count": catalog.official_count,
                    },
                    "tcgdex_requests_used_total": resolver.requests_used,
                }
            )
            if catalog.status != "EXACT":
                trace.reject(seed, f"target_catalog_unproven:{catalog.reason or catalog.status}")
                continue

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

                ok, proof = magi_registry_identity_check(detailed, seed.source_identity, catalog, entry)
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
                    note=(
                        f"magi fixed ASK; {proof}; registry={REGISTRY_VERSION}; "
                        "buyer/logistics all-in intentionally unproven in global shadow"
                    ),
                )
                found[seed.identity.strict_key].append((observation, detailed.url, detailed.title))
                exact += 1
                trace.exact(seed)
    finally:
        resolver.close()

    return found, SourceStatus(
        "magi",
        "OK",
        (
            f"public read-only; versioned TCGdex Japanese set registry {REGISTRY_VERSION} + exact set/localId/name; "
            f"tcgdex_calls={resolver.requests_used}"
        ),
        searches,
        candidates,
        exact,
    ), trace
