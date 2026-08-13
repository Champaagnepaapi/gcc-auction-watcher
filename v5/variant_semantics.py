from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Optional

from .models import CardIdentity


FINISH_STANDARD = "standard"
FINISH_HOLO = "holofoil"
FINISH_REVERSE = "reverse_holofoil"

EDITION_FIRST = "first_edition"
EDITION_UNLIMITED = "unlimited"
EDITION_SHADOWLESS = "shadowless"


@dataclass(frozen=True)
class VariantSemantics:
    finish: Optional[str] = None
    edition: Optional[str] = None
    promo: Optional[bool] = None
    special_finish: Optional[str] = None
    explicit: bool = False


@dataclass(frozen=True)
class VariantCompatibility:
    compatible: bool
    exact: bool = False
    reason: Optional[str] = None
    finish_match: bool = False
    edition_match: bool = False
    promo_match: bool = False
    metadata_missing: bool = False


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?:^|\s){re.escape(value)}(?:$|\s)", text) for value in values)


def _finish_from_text(text: str) -> tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    # More specific finishes must be tested before generic holo.
    special_aliases = (
        ("cosmos_holo", ("cosmos holo", "cosmos holofoil")),
        ("galaxy_holo", ("galaxy holo", "galaxy holofoil")),
        ("cracked_ice_holo", ("cracked ice holo", "cracked ice holofoil")),
        ("stamped_holo", ("stamped holo", "stamped holofoil")),
        ("pokeball_reverse", ("pokeball reverse", "poke ball reverse")),
        ("masterball_reverse", ("masterball reverse", "master ball reverse")),
    )
    for canonical, aliases in special_aliases:
        if any(alias in text for alias in aliases):
            if "reverse" in canonical:
                return FINISH_REVERSE, canonical
            return FINISH_HOLO, canonical

    if _contains_any(
        text,
        (
            "reverse holo",
            "reverse holographic",
            "reverse holographique",
            "reverse holofoil",
            "reverse foil",
            "reverse",
        ),
    ):
        return FINISH_REVERSE, None
    if _contains_any(
        text,
        (
            "non holo",
            "non holographic",
            "non holographique",
            "non holofoil",
            "normal",
            "standard",
        ),
    ):
        return FINISH_STANDARD, None
    if _contains_any(
        text,
        ("holo", "holographic", "holographique", "holofoil", "foil"),
    ):
        return FINISH_HOLO, None
    return None, None


def _edition_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    if "shadowless" in text:
        return EDITION_SHADOWLESS
    if _contains_any(
        text,
        (
            "1st edition",
            "first edition",
            "1 edition",
            "1st ed",
            "1ere edition",
            "premiere edition",
            "1 auflage",
            "erste auflage",
            "1a edizione",
            "prima edizione",
            "1a edicion",
            "primera edicion",
        ),
    ):
        return EDITION_FIRST
    if _contains_any(
        text,
        (
            "unlimited",
            "unbegrenzt",
            "illimitee",
            "illimitata",
            "ilimitada",
        ),
    ):
        return EDITION_UNLIMITED
    return None


def _promo_from_text(text: str) -> Optional[bool]:
    if not text:
        return None
    if _contains_any(text, ("promo", "promotional", "black star promo")):
        return True
    return None


def semantics_from_text(value: object) -> VariantSemantics:
    text = _normalize(value)
    finish, special_finish = _finish_from_text(text)
    edition = _edition_from_text(text)
    promo = _promo_from_text(text)
    return VariantSemantics(
        finish=finish,
        edition=edition,
        promo=promo,
        special_finish=special_finish,
        explicit=bool(text),
    )


def _merge_semantics(*values: VariantSemantics) -> tuple[VariantSemantics, bool]:
    finish = None
    edition = None
    promo = None
    special_finish = None
    explicit = False
    conflict = False
    for value in values:
        explicit = explicit or value.explicit
        for current, incoming in (
            (finish, value.finish),
            (edition, value.edition),
            (special_finish, value.special_finish),
        ):
            if current and incoming and current != incoming:
                conflict = True
        if finish is None and value.finish:
            finish = value.finish
        if edition is None and value.edition:
            edition = value.edition
        if special_finish is None and value.special_finish:
            special_finish = value.special_finish
        if promo is not None and value.promo is not None and promo != value.promo:
            conflict = True
        if promo is None and value.promo is not None:
            promo = value.promo
    return (
        VariantSemantics(
            finish=finish,
            edition=edition,
            promo=promo,
            special_finish=special_finish,
            explicit=explicit,
        ),
        conflict,
    )


def semantics_from_identity(identity: CardIdentity) -> tuple[VariantSemantics, bool]:
    variant = semantics_from_text(identity.variant)
    # eBay's Parallel/Variety value "Standard" means no named parallel; it
    # does not prove a non-holographic physical finish. Keep explicit finish
    # and edition aspects authoritative instead of manufacturing a conflict.
    if (
        variant.finish == FINISH_STANDARD
        and _normalize(identity.variant) in {"normal", "standard"}
    ):
        variant = VariantSemantics(
            edition=variant.edition,
            promo=variant.promo,
            special_finish=variant.special_finish,
            explicit=variant.explicit,
        )
    values = [
        variant,
        semantics_from_text(identity.finish),
        semantics_from_text(identity.edition),
    ]
    # Promo is frequently represented by rarity or by the promo set itself,
    # rather than by Parallel/Variety. This is identity evidence, not a guess.
    parsed_rarity = semantics_from_text(identity.rarity)
    rarity = VariantSemantics(
        promo=parsed_rarity.promo,
        explicit=parsed_rarity.promo is not None,
    )
    parsed_set = semantics_from_text(identity.set)
    set_semantics = VariantSemantics(
        edition=parsed_set.edition,
        promo=parsed_set.promo,
        explicit=bool(parsed_set.edition or parsed_set.promo is not None),
    )
    values.extend((rarity, set_semantics))
    return _merge_semantics(*values)


def semantics_from_poketrace_candidate(candidate: Mapping[str, object]) -> VariantSemantics:
    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    parsed_rarity = semantics_from_text(candidate.get("rarity"))
    parsed_set = semantics_from_text(set_name)
    direct_promo = True if candidate.get("promo") is True else (False if candidate.get("promo") is False else None)
    values = (
        semantics_from_text(candidate.get("variant")),
        semantics_from_text(candidate.get("finish")),
        semantics_from_text(candidate.get("edition")),
        semantics_from_text(candidate.get("special_finish")),
        VariantSemantics(
            promo=direct_promo if direct_promo is not None else parsed_rarity.promo,
            explicit=direct_promo is not None or parsed_rarity.promo is not None,
        ),
        VariantSemantics(
            edition=parsed_set.edition,
            promo=parsed_set.promo,
            explicit=bool(parsed_set.edition or parsed_set.promo is not None),
        ),
    )
    return _merge_semantics(*values)[0]


def variant_compatibility(
    identity: CardIdentity,
    candidate: Mapping[str, object],
) -> VariantCompatibility:
    expected, expected_conflict = semantics_from_identity(identity)
    actual = semantics_from_poketrace_candidate(candidate)
    if expected_conflict:
        return VariantCompatibility(False, reason="listing_variant_conflict")

    if expected.finish and actual.finish and expected.finish != actual.finish:
        return VariantCompatibility(False, reason="finish_conflict")
    if expected.special_finish and actual.special_finish and expected.special_finish != actual.special_finish:
        return VariantCompatibility(False, reason="special_finish_conflict")
    if expected.special_finish and not actual.special_finish:
        return VariantCompatibility(False, reason="candidate_special_finish_missing", metadata_missing=True)
    if actual.special_finish and not expected.special_finish:
        return VariantCompatibility(False, reason="listing_special_finish_missing", metadata_missing=True)
    if expected.finish and actual.finish is None:
        return VariantCompatibility(False, reason="candidate_finish_missing", metadata_missing=True)
    if actual.finish and expected.finish is None:
        return VariantCompatibility(False, reason="listing_finish_missing", metadata_missing=True)

    # Edition is price-sensitive. Never map a proven 1st-edition/shadowless card
    # to a candidate that explicitly says Unlimited, or vice versa.
    if expected.edition and actual.edition and expected.edition != actual.edition:
        return VariantCompatibility(False, reason="edition_conflict")

    # If one side explicitly carries a premium edition and the other side is
    # silent, exact identity is not proven. This stays blocking rather than
    # manufacturing a 1st-edition/shadowless match.
    premium_editions = {EDITION_FIRST, EDITION_SHADOWLESS}
    if expected.edition in premium_editions and actual.edition is None:
        return VariantCompatibility(False, reason="candidate_edition_missing", metadata_missing=True)
    if actual.edition in premium_editions and expected.edition is None:
        return VariantCompatibility(False, reason="listing_edition_missing", metadata_missing=True)

    # Promo may be proven by the shared promo set / rarity even when the eBay
    # Parallel/Variety field is empty. It is price-sensitive: positive evidence
    # on only one side is insufficient for an exact commercial-variant match.
    if expected.promo is True and actual.promo is False:
        return VariantCompatibility(False, reason="promo_conflict")
    if actual.promo is True and expected.promo is False:
        return VariantCompatibility(False, reason="promo_conflict")
    if expected.promo is True and actual.promo is None:
        return VariantCompatibility(
            False,
            reason="candidate_promo_missing",
            metadata_missing=True,
        )
    if actual.promo is True and expected.promo is None:
        return VariantCompatibility(
            False,
            reason="listing_promo_missing",
            metadata_missing=True,
        )

    finish_match = bool(expected.finish and actual.finish and expected.finish == actual.finish)
    edition_match = bool(expected.edition and actual.edition and expected.edition == actual.edition)
    promo_match = bool(expected.promo is True and actual.promo is True)

    comparable_dimensions = sum(
        1
        for expected_value, actual_value in (
            (expected.finish, actual.finish),
            (expected.edition, actual.edition),
            (expected.promo, actual.promo),
            (expected.special_finish, actual.special_finish),
        )
        if expected_value is not None and actual_value is not None
    )
    matched_dimensions = sum((finish_match, edition_match, promo_match))
    if expected.special_finish and actual.special_finish == expected.special_finish:
        matched_dimensions += 1

    return VariantCompatibility(
        compatible=True,
        exact=bool(comparable_dimensions and comparable_dimensions == matched_dimensions),
        finish_match=finish_match,
        edition_match=edition_match,
        promo_match=promo_match,
        metadata_missing=False,
    )


def tcgdex_variant_supports_identity(
    identity: CardIdentity,
    card: Mapping[str, object],
) -> Optional[bool]:
    """Return whether TCGdex says the requested finish/edition is possible.

    TCGdex variants describe *available* variants for the card, not the exact
    marketplace listing. Therefore this helper may reject an impossible finish,
    but it must never infer the listing's exact variant from availability alone.
    """

    variants = card.get("variants")
    if not isinstance(variants, Mapping):
        return None
    expected, conflict = semantics_from_identity(identity)
    if conflict:
        return False

    checks = []
    if expected.edition == EDITION_FIRST:
        value = variants.get("firstEdition")
        if isinstance(value, bool):
            checks.append(value)
    if expected.finish == FINISH_REVERSE:
        value = variants.get("reverse")
        if isinstance(value, bool):
            checks.append(value)
    elif expected.finish == FINISH_HOLO:
        value = variants.get("holo")
        if isinstance(value, bool):
            checks.append(value)
    elif expected.finish == FINISH_STANDARD:
        value = variants.get("normal")
        if isinstance(value, bool):
            checks.append(value)
    if expected.promo is True:
        value = variants.get("wPromo")
        if isinstance(value, bool):
            checks.append(value)

    if not checks:
        return None
    return all(checks)
