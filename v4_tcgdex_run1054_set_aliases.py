from __future__ import annotations

import v4_tcgdex_generalized_coordinate_recovery as generalized


# Official source pin: tcgdex/cards-database
# af33c9ac882e2acfadffaf19e8083aa976d12983
# Set-level aliases only; exact coordinate proof remains mandatory downstream.
_ALIASES = (
    generalized.ExactSetAlias(
        "fr", "SWSH Promo", "swshp", 307,
        provenance="TCGdex swshp / GCC French SWSH Promo label",
    ),
    generalized.ExactSetAlias(
        "ja", "VMAX Climax", "S8b", 184,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex S8b / GCC Japanese VMAX Climax label",
    ),
    generalized.ExactSetAlias(
        "ja", "Mega Dream ex", "M2a", 193,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex M2a / GCC Japanese Mega Dream ex label",
    ),
    generalized.ExactSetAlias(
        "ja", "Scarlet & Violet Promos", "SV-P", 0,
        required_reference_suffix="SV-P",
        allow_localized_name_mismatch=True,
        provenance="TCGdex SV-P / GCC Japanese Scarlet & Violet promo namespace",
    ),
    generalized.ExactSetAlias(
        "ja", "Ruler of the Black Flame", "SV3", 108,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex SV3 / GCC Japanese Ruler of the Black Flame label",
    ),
    generalized.ExactSetAlias(
        "ja", "M-P Promotional cards", "M-P", 0,
        required_reference_suffix="M-P",
        allow_localized_name_mismatch=True,
        provenance="TCGdex M-P / GCC Japanese Mega promo namespace",
    ),
    generalized.ExactSetAlias(
        "ja", "The Glory of Team Rocket", "SV10", 98,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex SV10 / GCC Japanese The Glory of Team Rocket label",
    ),
)


def install_v4_tcgdex_run1054_set_aliases() -> None:
    """Register reviewed run-1054 exact set aliases, fail-closed on conflict."""
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
