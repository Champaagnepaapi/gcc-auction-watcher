"""Disambiguate Magi full numbers only by an exact Japanese catalog name.

Some numeric ``local/official`` coordinates exist in multiple Japanese TCGdex
sets. The normal global-uniqueness resolver correctly blocks them. This recovery
runs only after that exact ``TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER`` result and
re-enumerates the same coordinate candidates through the scan-scoped recovery
resolver. It accepts a card only when exactly one candidate's exact Japanese
TCGdex card name occurs in the bounded current Magi product evidence.

Set enumeration, localId, official denominator and card payload validation reuse
the same TCGdex resolver primitives. With CachedRecoveryResolver, the set list
and coordinate responses already read by the first pass are cache hits, so this
extra identity axis does not expand the normal recovery budget in the common
case. No fuzzy matching, translation, rarity inference or per-card exception is
used.
"""
from __future__ import annotations

from typing import Mapping
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_magi_detail_coordinate as detail_coordinate
import v4_global_marketplace_magi_japanese_native_identity as japanese_native
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_recovery_budget as recovery_budget
import v4_global_retrieval_hardening_v3 as retrieval_v3
import v4_tcgdex_generalized_coordinate_recovery as generalized
from v4_global_market_core import CommercialIdentity


_EXPECTED_REASON = "target_catalog_unproven:TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER"
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _candidate_proofs(
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    *,
    local: str,
    denominator: str,
) -> tuple[retrieval_v3.JapaneseCatalogProof, ...]:
    """Reproduce the resolver's exact numeric-coordinate candidate set."""
    status, payload = resolver._get(
        "sets",
        params={"cardCount.official": f"eq:{int(denominator)}"},
    )
    if status != 200:
        return ()

    exact_sets: list[Mapping[str, object]] = []
    for row in resolver._list_payload(payload):
        counts = row.get("cardCount")
        if not isinstance(counts, Mapping):
            continue
        try:
            same = int(str(counts.get("official"))) == int(denominator)
        except (TypeError, ValueError):
            same = False
        if same and str(row.get("id") or "").strip():
            exact_sets.append(row)
    if not exact_sets or len(exact_sets) > 30:
        return ()

    found: dict[str, retrieval_v3.JapaneseCatalogProof] = {}
    for set_row in exact_sets:
        set_id = str(set_row.get("id") or "").strip()
        for q_local in resolver._local_variants(local):
            card_status, card_payload = resolver._get(
                f"sets/{quote(set_id, safe='')}/{quote(q_local, safe='')}"
            )
            if card_status == 0:
                return ()
            if card_status == 404:
                continue
            if card_status != 200:
                # Transient/provider errors cannot produce a deterministic
                # candidate universe, so fail closed rather than partially
                # disambiguating it.
                return ()
            detail = resolver._detail_payload(card_payload)
            if detail is None:
                continue
            proof = resolver._catalog_card(detail, denominator)
            if proof is None:
                continue
            if not generalized._same_local_id(proof.local_id, local):
                continue
            found[proof.card_id] = proof
            break
    return tuple(found.values())


def recover_unique_name_among_full_number_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
) -> native.MagiNativeResolution:
    if original.status != "AMBIGUOUS" or original.reason != _EXPECTED_REASON:
        return original

    evidence = detail_coordinate._current_product_evidence(ask)
    full_number, _reason = detail_coordinate._full_number_from_evidence(evidence)
    if not full_number or "/" not in full_number:
        return original
    local, denominator = full_number.split("/", 1)
    if not local.isdigit() or not denominator.isdigit():
        return original

    candidates = _candidate_proofs(
        resolver,
        local=local,
        denominator=denominator,
    )
    if len(candidates) < 2:
        # This recovery is specifically an independent disambiguation axis over
        # a previously-proved multiple-candidate universe. If that universe can
        # no longer be reconstructed exactly, preserve the original ambiguity.
        return original

    matching = [
        proof
        for proof in candidates
        if proof.name_ja and magi_hardening._jp_contains(evidence, proof.name_ja)
    ]
    if len(matching) != 1:
        return original
    proof = matching[0]

    if not all((proof.card_id, proof.set_id, proof.local_id, proof.name_ja, proof.official_count)):
        return original
    if not generalized._same_local_id(proof.local_id, local):
        return original
    try:
        denominator_ok = int(proof.official_count) == int(denominator)
    except (TypeError, ValueError):
        denominator_ok = False
    if not denominator_ok:
        return original

    set_label = japanese_native._resolver_set_label(proof, full_number=full_number)
    if not set_label:
        return original
    identity = CommercialIdentity(
        name=str(proof.name_ja).strip(),
        set_name=set_label,
        number=full_number,
        language="ja",
        grader="PSA",
        grade="10",
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return original

    return native.MagiNativeResolution(
        "EXACT",
        "MAGI_NATIVE_TCGDEX_JA_UNIQUE_EXACT_NAME_AMONG_FULL_NUMBER",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _resolve_with_unique_name_among_full_number(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    resolver = recovery_budget.active_recovery_resolver(kwargs["resolver"])
    return recover_unique_name_among_full_number_resolution(
        ask,
        original,
        resolver=resolver,
    )


def install_global_marketplace_magi_unique_name_among_full_number() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_unique_name_among_full_number
    _INSTALLED = True
