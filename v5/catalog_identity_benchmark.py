from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from typing import Iterable, Optional

from .card_identity_catalog import MultilingualPokemonCardResolver, render_card_catalog_counters
from .ebay import RAW_CONDITION_ID, parse_ebay_item, resolve_card_identity
from .ebay_live_diagnostic import EbayLiveDiagnostic, MarketplaceAggregate
from .justtcg_identity import JustTCGIdentityResolver, render_justtcg_counters
from .poketrace_matching import (
    _card_number_parts,
    _normalize_card_name,
    _normalize_card_number,
    _set_similarity,
)


@dataclass
class BenchmarkCounters:
    records_seen: int = 0
    raw_records: int = 0
    identity_core_sufficient: int = 0
    tcgdex_exact: int = 0
    tcgdex_ambiguous: int = 0
    tcgdex_unresolved: int = 0
    justtcg_exact: int = 0
    justtcg_ambiguous: int = 0
    justtcg_unresolved: int = 0
    both_exact: int = 0
    exact_consensus: int = 0
    exact_enrichment_consensus: int = 0
    exact_disagreement: int = 0
    disagreement_name: int = 0
    disagreement_set: int = 0
    disagreement_number: int = 0
    tcgdex_only: int = 0
    justtcg_only: int = 0
    neither_exact: int = 0


def _number_compatible(left: object, right: object) -> tuple[bool, bool]:
    left_norm = _normalize_card_number(left)
    right_norm = _normalize_card_number(right)
    if not left_norm or not right_norm:
        return False, False
    if left_norm == right_norm:
        return True, False

    left_num, left_den = _card_number_parts(left)
    right_num, right_den = _card_number_parts(right)
    if not left_num or left_num != right_num:
        return False, False
    if left_den and right_den:
        return left_den == right_den, False
    # Same printed numerator, exactly one source adds the denominator. Treat as
    # compatible canonical enrichment, never as a hard disagreement.
    return True, bool(left_den) != bool(right_den)


def _core_compatibility(left, right) -> tuple[bool, bool, tuple[str, ...]]:
    failures = []
    if _normalize_card_name(left.card_name) != _normalize_card_name(right.card_name):
        failures.append("name")

    set_score = _set_similarity(left.set, right.set, None)
    if set_score < 0.86:
        failures.append("set")

    number_ok, number_enrichment = _number_compatible(
        left.card_number, right.card_number
    )
    if not number_ok:
        failures.append("number")

    return not failures, number_enrichment, tuple(failures)


def _fingerprint(item_ids: Iterable[str]) -> str:
    values = sorted(value for value in item_ids if value)
    if not values:
        return "EMPTY"
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()[:16]


def _discover_same_sample(client_id: str, client_secret: str, limit: int):
    diagnostic = EbayLiveDiagnostic(
        client_id,
        client_secret,
        result_limit=limit,
        marketplaces=("EBAY_US",),
    )
    token, oauth = diagnostic._application_token()
    if token is None:
        return oauth, MarketplaceAggregate("EBAY_US"), []
    aggregate, records = diagnostic._discover_marketplace("EBAY_US", token)
    diagnostic._enrich_unique_items(records, {"EBAY_US": aggregate}, token)
    return oauth, aggregate, records


def run_benchmark(
    *,
    client_id: str,
    client_secret: str,
    justtcg_api_key: str,
    limit: int = 20,
    tcgdex_resolver: Optional[MultilingualPokemonCardResolver] = None,
    justtcg_resolver: Optional[JustTCGIdentityResolver] = None,
) -> tuple[BenchmarkCounters, str, MultilingualPokemonCardResolver, JustTCGIdentityResolver, object, MarketplaceAggregate]:
    tcgdex = tcgdex_resolver or MultilingualPokemonCardResolver()
    justtcg = justtcg_resolver or JustTCGIdentityResolver(api_key=justtcg_api_key)
    counters = BenchmarkCounters()

    oauth, marketplace, records = _discover_same_sample(client_id, client_secret, limit)
    item_ids = []
    for record in records:
        if record.item_id:
            item_ids.append(record.item_id)
        counters.records_seen += 1
        if not record.get_item_success:
            continue
        try:
            listing = parse_ebay_item(record.enriched)
        except Exception:
            continue
        if listing.condition_id != RAW_CONDITION_ID:
            continue
        counters.raw_records += 1

        identity = resolve_card_identity(record.enriched).identity
        supplied = sum(bool(value) for value in (identity.card_name, identity.set, identity.card_number))
        if supplied >= 2:
            counters.identity_core_sufficient += 1

        if identity.set and identity.card_number:
            tcg = tcgdex._resolve_tcgdex(identity)
        else:
            tcg = None
        just = justtcg.resolve_identity(identity)

        tcg_exact = bool(tcg is not None and tcg.matched and not tcg.ambiguous)
        tcg_ambiguous = bool(tcg is not None and tcg.ambiguous)
        just_exact = bool(just.matched and not just.ambiguous)
        just_ambiguous = bool(just.ambiguous)

        counters.tcgdex_exact += int(tcg_exact)
        counters.tcgdex_ambiguous += int(tcg_ambiguous)
        counters.tcgdex_unresolved += int(not tcg_exact and not tcg_ambiguous)
        counters.justtcg_exact += int(just_exact)
        counters.justtcg_ambiguous += int(just_ambiguous)
        counters.justtcg_unresolved += int(not just_exact and not just_ambiguous)

        if tcg_exact and just_exact:
            counters.both_exact += 1
            compatible, enrichment, failures = _core_compatibility(
                tcg.identity, just.identity
            )
            if compatible:
                counters.exact_consensus += 1
                counters.exact_enrichment_consensus += int(enrichment)
            else:
                counters.exact_disagreement += 1
                counters.disagreement_name += int("name" in failures)
                counters.disagreement_set += int("set" in failures)
                counters.disagreement_number += int("number" in failures)
        elif tcg_exact:
            counters.tcgdex_only += 1
        elif just_exact:
            counters.justtcg_only += 1
        else:
            counters.neither_exact += 1

    return counters, _fingerprint(item_ids), tcgdex, justtcg, oauth, marketplace


def render_benchmark(
    counters: BenchmarkCounters,
    fingerprint: str,
    tcgdex: MultilingualPokemonCardResolver,
    justtcg: JustTCGIdentityResolver,
    oauth,
    marketplace: MarketplaceAggregate,
) -> str:
    lines = [
        "=== V5 SAME-SAMPLE IDENTITY BENCHMARK ===",
        "providers: TCGdex vs JustTCG; PokeTrace disabled/not instantiated",
        "persistence: aggregate-only / memory-only",
        f"sample fingerprint: {fingerprint}",
        f"eBay OAuth HTTP/status: {oauth.http_status}",
        f"eBay search results: {marketplace.results_received}",
        f"eBay getItem success: {marketplace.get_item_success}",
        f"records seen: {counters.records_seen}",
        f"RAW records: {counters.raw_records}",
        f"identity core sufficient: {counters.identity_core_sufficient}",
        f"TCGdex exact: {counters.tcgdex_exact}",
        f"TCGdex ambiguous: {counters.tcgdex_ambiguous}",
        f"TCGdex unresolved: {counters.tcgdex_unresolved}",
        f"JustTCG exact: {counters.justtcg_exact}",
        f"JustTCG ambiguous: {counters.justtcg_ambiguous}",
        f"JustTCG unresolved: {counters.justtcg_unresolved}",
        f"both exact: {counters.both_exact}",
        f"safe exact consensus: {counters.exact_consensus}",
        (
            "consensus with denominator/canonical enrichment: "
            f"{counters.exact_enrichment_consensus}"
        ),
        f"hard exact disagreement: {counters.exact_disagreement}",
        f"hard disagreement - name: {counters.disagreement_name}",
        f"hard disagreement - set: {counters.disagreement_set}",
        f"hard disagreement - number: {counters.disagreement_number}",
        f"TCGdex-only exact: {counters.tcgdex_only}",
        f"JustTCG-only exact: {counters.justtcg_only}",
        f"neither exact: {counters.neither_exact}",
        "PokeTrace live calls: 0",
        "purchases/bids/checkout/CardGrader: 0/0/0/0",
        "persisted eBay listing identifiers/titles/URLs/prices: 0",
        "",
        render_card_catalog_counters(tcgdex),
        "",
        render_justtcg_counters(justtcg),
    ]
    return "\n".join(lines)


def main() -> int:
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    justtcg_api_key = os.getenv("JUSTTCG_API_KEY", "").strip()
    if not client_id or not client_secret or not justtcg_api_key:
        print("benchmark credentials: MISSING", file=sys.stderr)
        return 2

    limit = int(os.getenv("V5_CATALOG_BENCHMARK_LIMIT", "20"))
    if not 1 <= limit <= 20:
        print("V5_CATALOG_BENCHMARK_LIMIT must be between 1 and 20", file=sys.stderr)
        return 2

    counters, fingerprint, tcgdex, justtcg, oauth, marketplace = run_benchmark(
        client_id=client_id,
        client_secret=client_secret,
        justtcg_api_key=justtcg_api_key,
        limit=limit,
    )
    print(render_benchmark(counters, fingerprint, tcgdex, justtcg, oauth, marketplace))
    return 0 if oauth.token_obtained and marketplace.http_status == "200" else 1


if __name__ == "__main__":
    raise SystemExit(main())
