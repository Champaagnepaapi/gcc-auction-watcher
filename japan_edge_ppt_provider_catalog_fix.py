"""Observed-provider catalog correction for the Japan Edge PPT shadow.

Live diagnostics proved that PokemonPriceTracker exposes Japanese Pokemon Card
151 with numeric provider setId 23599, while `SV2a` is part of setName rather
than the API setId. PPT also omits a row-level language field for these results
although the request is explicitly scoped with `language=japanese`.

This patch keeps the underlying sidecar read-only/non-economic and changes only
provider identity proof:
- 151/2023 -> observed PPT setId 23599;
- VSTAR Universe remains unmapped/fail-closed until its numeric PPT setId is
  observed;
- every request remains `language=japanese`;
- a missing row-level language is acceptable only with the reviewed Japanese
  setId + exact collector number; an explicit non-Japanese row is rejected.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import japan_edge_ppt_exact_set_shadow as shadow

OBSERVED_JP_SET_ID_MAP: dict[tuple[str, int], str] = {
    ("151", 2023): "23599",
    ("pokemon card 151", 2023): "23599",
}

# Replace the provisional expansion-code mapping with provider IDs actually
# observed in the bounded live response. Unobserved sets stay fail-closed.
shadow.JP_SET_ID_MAP = dict(OBSERVED_JP_SET_ID_MAP)


def match_japanese_identity(
    identity: shadow.base.Identity,
    rows: Sequence[Mapping[str, object]],
    expected_set_id: str,
) -> shadow.PptMatch:
    if not shadow._language_is_japanese(identity.language):
        return shadow.PptMatch(
            "BLOCKED_LANGUAGE", reason="PHYSICAL_CARD_NOT_JAPANESE"
        )

    expected_id = shadow._norm(expected_set_id)
    expected_number = shadow._collector(identity.number)
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        declared_language = row.get("language")
        if declared_language not in (None, "") and not shadow._language_is_japanese(
            declared_language
        ):
            continue
        if shadow._norm(row.get("setId") or row.get("set_id")) != expected_id:
            continue
        if (
            shadow._collector(row.get("cardNumber") or row.get("number"))
            != expected_number
        ):
            continue
        candidates.append(row)

    if not candidates:
        return shadow.PptMatch(
            "CLEAN_NO_MATCH", reason="JP_PROVIDER_SET_ID_NUMBER_NOT_FOUND"
        )
    if len(candidates) > 1:
        return shadow.PptMatch(
            "AMBIGUOUS", reason="MULTIPLE_JP_PROVIDER_SET_ID_NUMBER_ROWS"
        )

    row = candidates[0]
    provider_blob = shadow._provider_identity_blob(row)
    for claim in shadow._sensitive_claims(identity):
        if claim not in provider_blob:
            return shadow.PptMatch(
                "MICROVARIANT_UNPROVEN",
                reason=f"MISSING_PROVIDER_CLAIM:{claim}",
            )
    return shadow.PptMatch(
        "EXACT",
        row=row,
        reason="JP_QUERY_SCOPE_PROVIDER_SET_ID_NUMBER_AND_VARIANT",
    )


# Runtime functions in the original sidecar resolve this global dynamically.
shadow.match_japanese_identity = match_japanese_identity


def main() -> None:
    shadow.main()


if __name__ == "__main__":
    main()
