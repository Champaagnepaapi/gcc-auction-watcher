"""Strict Global-only bridges for exact external provider coordinates.

Live diagnostics proved a recurring provider nomenclature shape on already-exact
Japanese TCGdex coordinates: PokeTrace/PPT may add a card mechanic (`V`, `ex`,
`Mega ... ex`) and a literal TCGdex set-code prefix. This module accepts only that
bounded shape after exact full collector number, exact set coordinate and exact
language proof. It never makes fuzzy identity, never treats ASK as SOLD, and does
not alter notification/transaction capability.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_ppt_confirmation as ppt
import v4_multimarket_safety as safety


_MECHANIC_SUFFIXES = frozenset({"v", "vmax", "vstar", "ex", "gx"})
_INSTALLED = False
_ORIGINAL_PPT_MATCH_CANONICAL = ppt._match_canonical


def _norm_tokens(value: object) -> tuple[str, ...]:
    normalized = multimarket._normalize(value)
    return tuple(token for token in re.split(r"\s+", normalized) if token)


def _strip_japanese_annotation(value: object, language_code: object) -> str:
    raw = str(value or "").strip()
    if str(language_code or "").strip().casefold() not in {"ja", "jp"}:
        return raw
    return re.sub(r"\s*\(Japanese\)\s*$", "", raw, flags=re.IGNORECASE).strip()


def _strip_ppt_number_suffix(value: object, expected_number: object) -> str:
    raw = str(value or "").strip()
    left, right = multimarket._canonical_number_parts(expected_number)
    if not left or not right:
        return raw
    pattern = rf"\s*-\s*0*{re.escape(left)}\s*/\s*0*{re.escape(right)}\s*$"
    return re.sub(pattern, "", raw, flags=re.IGNORECASE).strip()


def mechanic_name_equivalent(
    canonical_name: object,
    provider_name: object,
    *,
    language_code: object = "",
    expected_number: object = "",
) -> bool:
    """Accept only exact canonical name plus a tightly bounded mechanic affix."""
    provider = _strip_japanese_annotation(provider_name, language_code)
    if expected_number:
        provider = _strip_ppt_number_suffix(provider, expected_number)
    target = _norm_tokens(canonical_name)
    observed = _norm_tokens(provider)
    if not target or not observed:
        return False
    if observed == target:
        return True
    if len(observed) == len(target) + 1:
        return observed[:-1] == target and observed[-1] in _MECHANIC_SUFFIXES
    if len(observed) == len(target) + 2:
        return (
            observed[0] == "mega"
            and observed[1:-1] == target
            and observed[-1] == "ex"
        )
    return False


def _full_number_exact(candidate_number: object, canonical_number: object) -> bool:
    cand_left, cand_right = multimarket._canonical_number_parts(candidate_number)
    card_left, card_right = multimarket._canonical_number_parts(canonical_number)
    return bool(
        cand_left
        and cand_right
        and card_left
        and card_right
        and cand_left == card_left
        and cand_right == card_right
    )


def _set_exact_or_catalog_prefix(
    canonical: multimarket.CanonicalCard, provider_set_name: object
) -> bool:
    raw = str(provider_set_name or "").strip()
    return bool(
        raw
        and (
            multimarket._normalize(raw) == multimarket._normalize(canonical.set_name)
            or safety._provider_set_id_prefix_matches(canonical, raw)
        )
    )


def _sensitive_dimensions_compatible(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    candidate: Mapping[str, object],
) -> bool:
    """Reuse V4 fail-closed dimension semantics with one catalog applicability rule.

    Global discovery sometimes labels a modern card `Unlimited`. That label must
    still be proved unless the exact TCGdex coordinate explicitly reports
    `firstEdition=false`; only in that case is the edition axis catalog-proved
    inapplicable. This never infers Unlimited from provider omission.
    """
    expected = dict(watcher.expected_commercial_dimensions(lot))
    if any(value == "__conflict__" for value in expected.values()):
        return False

    variants = canonical.variants if isinstance(canonical.variants, Mapping) else {}
    if expected.get("edition") == "unlimited" and variants.get("firstEdition") is False:
        expected.pop("edition", None)

    observed = safety._candidate_sensitive_dimensions(candidate)
    for dimension in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS:
        expected_value = expected.get(dimension)
        if not expected_value:
            continue
        if expected_value not in observed.get(dimension, set()):
            return False

    catalog_finish = safety._catalog_only_finish(canonical)
    for dimension in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS:
        values = observed.get(dimension, set())
        if not values or expected.get(dimension):
            continue
        if dimension == "finish" and len(values) == 1:
            if catalog_finish and next(iter(values)) == catalog_finish:
                continue
        return False

    if variants.get("firstEdition") is True and not expected.get("edition"):
        return False
    possible_finishes = sum(
        variants.get(key) is True for key in ("normal", "holo", "reverse")
    )
    if possible_finishes > 1 and not expected.get("finish"):
        return False
    return True


def global_candidate_exact_for_canonical(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    candidate: Mapping[str, object],
) -> bool:
    """Global PokeTrace exact gate with bounded mechanic nomenclature support."""
    if safety.hardened_candidate_exact_for_canonical(lot, canonical, candidate):
        return True
    if canonical.status != "EXACT":
        return False
    if str(candidate.get("productType") or "single").strip().casefold() != "single":
        return False
    if not _full_number_exact(candidate.get("cardNumber"), canonical.full_number):
        return False
    set_payload = candidate.get("set")
    provider_set_name = (
        str(set_payload.get("name") or "").strip()
        if isinstance(set_payload, Mapping)
        else ""
    )
    if not _set_exact_or_catalog_prefix(canonical, provider_set_name):
        return False
    if not multimarket._poketrace_language_market_is_exact(lot, candidate):
        return False
    if not mechanic_name_equivalent(
        canonical.name,
        candidate.get("name"),
        language_code=canonical.language_code,
    ):
        return False
    return _sensitive_dimensions_compatible(lot, canonical, candidate)


def _ppt_candidate_matches(
    identity,
    canonical: multimarket.CanonicalCard,
    row: Mapping[str, object],
    *,
    provider_set_id: str,
) -> bool:
    if not ppt._language_compatible(row):
        return False
    # A present conflicting catalog coordinate must never fall through.
    if ppt._norm(row.get("externalCatalogId")):
        return False
    row_number = row.get("cardNumber") or row.get("number")
    if not _full_number_exact(row_number, canonical.full_number):
        return False
    provider_set_name = row.get("setName") or row.get("set_name")
    if not _set_exact_or_catalog_prefix(canonical, provider_set_name):
        return False
    if provider_set_id:
        row_set_id = ppt._norm(row.get("setId") or row.get("set_id"))
        if row_set_id and row_set_id != ppt._norm(provider_set_id):
            return False
    if not mechanic_name_equivalent(
        canonical.name,
        row.get("name"),
        language_code=canonical.language_code,
        expected_number=canonical.full_number,
    ):
        return False
    return ppt._variant_compatible(identity, row)


def global_ppt_match_canonical(
    identity,
    canonical: multimarket.CanonicalCard,
    rows: Sequence[Mapping[str, object]],
    *,
    provider_set_id: str = "",
):
    """Extend PPT fallback with exact full-number + TCGdex-set-prefix proof."""
    status, row, proof = _ORIGINAL_PPT_MATCH_CANONICAL(
        identity, canonical, rows, provider_set_id=provider_set_id
    )
    if status != "CLEAN_NO_MATCH":
        return status, row, proof
    if canonical.status != "EXACT" or not canonical.set_id:
        return status, row, proof

    candidates = [
        candidate
        for candidate in ppt._unique_rows(rows)
        if _ppt_candidate_matches(
            identity,
            canonical,
            candidate,
            provider_set_id=provider_set_id,
        )
    ]
    if len(candidates) > 1:
        return "AMBIGUOUS", None, "TCGDEX_FULL_NUMBER_SET_PREFIX_MECHANIC_NAME"
    if len(candidates) == 1:
        return "EXACT", candidates[0], "TCGDEX_FULL_NUMBER_SET_PREFIX_MECHANIC_NAME"
    return status, row, proof


def install_global_provider_exact_bridge() -> None:
    """Install bridges only into the read-only Global confirmation process."""
    global _INSTALLED
    if _INSTALLED:
        return
    multimarket._candidate_exact_for_canonical = global_candidate_exact_for_canonical
    ppt._match_canonical = global_ppt_match_canonical
    _INSTALLED = True
