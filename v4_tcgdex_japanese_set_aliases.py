from __future__ import annotations

import v4_tcgdex_generalized_coordinate_recovery as generalized


# Official source pin: tcgdex/cards-database
# af33c9ac882e2acfadffaf19e8083aa976d12983
# These are set-level namespace bridges only. Exact set/localId plus any supplied
# denominator remains mandatory in the generalized TCGdex resolver. Aliases that
# support numerator-only marketplace labels still revalidate the exact TCGdex
# set ID and official set count before returning an identity.
_ALIASES = (
    generalized.ExactSetAlias(
        "ja",
        "Night Wanderer",
        "SV6a",
        64,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex SV6a official Night Wanderer set / GCC Japanese romanized label",
    ),
    generalized.ExactSetAlias(
        "ja",
        "Glory of the Team Rocket",
        "SV10",
        98,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex SV10 official The Glory of Team Rocket set / GCC Japanese romanized label",
    ),
    # Fanatics Buy Now H1 uses only #localId for these Japanese cards. The
    # namespace bridges are source-pinned at the same immutable TCGdex commit;
    # the resolver must still read the exact set/localId endpoint and reproduce
    # the official set count, so no English->Japanese card-name translation is
    # guessed here.
    generalized.ExactSetAlias(
        "ja",
        "Scarlet & Violet 151",
        "SV2a",
        165,
        allow_localized_name_mismatch=True,
        provenance=(
            "TCGdex source pin data-asia/SV/SV2a.ts + SV2a/025.ts / "
            "Fanatics Japanese Scarlet & Violet 151 label"
        ),
    ),
    generalized.ExactSetAlias(
        "ja",
        "Web 1st Edition",
        "web1",
        48,
        allow_localized_name_mismatch=True,
        provenance=(
            "TCGdex source pin data-asia/web/web1.ts + web1/047.ts / "
            "Fanatics Japanese Web 1st Edition label"
        ),
    ),
    generalized.ExactSetAlias(
        "ja",
        "SV Glory Of The Rocket Gang",
        "SV10",
        98,
        allow_localized_name_mismatch=True,
        provenance=(
            "TCGdex source pin data-asia/SV/SV10.ts / "
            "Fanatics Japanese SV Glory Of The Rocket Gang label"
        ),
    ),
    generalized.ExactSetAlias(
        "ja",
        "Battle Partners",
        "SV9",
        100,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance=(
            "TCGdex source pin data-asia/SV/SV9.ts + SV9/102.ts + SV9/109.ts / GCC Battle Partners label"
        ),
    ),
    generalized.ExactSetAlias(
        "ja",
        "Inferno X",
        "M2",
        80,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex source pin data-asia/M/M2.ts + M2/111.ts / GCC romanized Inferno X label",
    ),
    generalized.ExactSetAlias(
        "ja",
        "Mega Symphonia",
        "M1S",
        63,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex source pin data-asia/M/M1S.ts + M1S/087.ts / GCC Mega Symphonia label",
    ),
    generalized.ExactSetAlias(
        "ja",
        "Mega Brave",
        "M1L",
        63,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex source pin data-asia/M/M1L.ts + M1L/064.ts / GCC Mega Brave label",
    ),
    generalized.ExactSetAlias(
        "ja",
        "Super Electric Breaker",
        "SV8",
        106,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex source pin data-asia/SV/SV8.ts + SV8/112.ts / GCC Super Electric Breaker label",
    ),
    generalized.ExactSetAlias(
        "ja",
        "S-P Promotional",
        "S-P",
        0,
        required_reference_suffix="S-P",
        allow_localized_name_mismatch=True,
        provenance="TCGdex source pin data-asia/S/S-P.ts + S-P/214.ts / GCC S-P promo label",
    ),
    generalized.ExactSetAlias(
        "ja",
        "SV-P Promos",
        "SV-P",
        0,
        required_reference_suffix="SV-P",
        allow_localized_name_mismatch=True,
        provenance="TCGdex source pin data-asia/SV/SV-P.ts + exact SV-P card files / GCC promo label",
    ),
)


def install_v4_tcgdex_japanese_set_aliases() -> None:
    """Register source-pinned Japanese set aliases, failing closed on conflict."""
    additions: list[generalized.ExactSetAlias] = []
    for alias in _ALIASES:
        key = generalized._alias_key(alias.language_code, alias.listing_set)
        existing = generalized._SET_ALIASES_BY_KEY.get(key)
        if existing is not None and existing != alias:
            raise RuntimeError(
                "Conflicting TCGdex exact set alias for "
                f"{alias.language_code}:{alias.listing_set}"
            )
        if existing is None:
            additions.append(alias)

    if not additions:
        return

    generalized._SET_ALIASES = (*generalized._SET_ALIASES, *additions)
    for alias in additions:
        generalized._SET_ALIASES_BY_KEY[
            generalized._alias_key(alias.language_code, alias.listing_set)
        ] = alias
