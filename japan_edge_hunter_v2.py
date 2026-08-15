"""Japan Edge Hunter V2 safety overlay.

Keeps the original read-only scanner isolated while fixing marketplace-page noise:
transaction-type checks use only text associated with the search result/listing
header, never unrelated recommendation/footer text from the detail page.

Also encodes the official Pokemon Card Game notice 005318 as a fail-closed
microvariant applicability rule for MEGA Dream ex MA cards. The notice proves
that both correctly and incorrectly surface-processed copies exist; it does not
prove which variant any individual copy is.
"""
from __future__ import annotations

from typing import Iterable, Optional
from datetime import datetime

import japan_edge_hunter as base

DETAIL_SEPARATOR = "---DETAIL---"
OFFICIAL_NOTICE_URL = "https://www.pokemon-card.com/info/005318.html"
OFFICIAL_NOTICE_ID = "005318"
OFFICIAL_SURFACE_ERROR_SET = "Mega Dream ex"
OFFICIAL_SURFACE_ERROR_RARITY = "Mega Attack Rare"
OFFICIAL_SURFACE_ERROR_NAMES = frozenset(
    base.norm(name)
    for name in (
        "Mega Charizard X ex",
        "Mega Froslass ex",
        "Mega Eelektross ex",
        "Mega Gardevoir ex",
        "Mega Diancie ex",
        "Mega Lucario ex",
        "Mega Hawlucha ex",
        "Mega Gengar ex",
        "Mega Scrafty ex",
        "Mega Dragonite ex",
    )
)


def _transaction_scope(ask: base.Ask) -> str:
    """Return only listing-associated text for auction/multi-item gates.

    Search-result text is captured from the DOM node associated with the exact
    item URL. Detail-page body text may contain recommendations, navigation or
    unrelated products and is therefore not transaction-type evidence.
    """
    search_text = (ask.text or "").split(DETAIL_SEPARATOR, 1)[0]
    return base.current_text("\n".join(x for x in (ask.title, search_text) if x))[:5000]


def _full_identity_scope(ask: base.Ask) -> str:
    return base.current_text("\n".join(x for x in (ask.title, ask.text) if x))


def _official_surface_error_applicable(ident: base.Identity) -> bool:
    return (
        base.norm(ident.set_name) == base.norm(OFFICIAL_SURFACE_ERROR_SET)
        and base.norm(ident.rarity) == base.norm(OFFICIAL_SURFACE_ERROR_RARITY)
        and base.norm(ident.name) in OFFICIAL_SURFACE_ERROR_NAMES
    )


def _surface_variant_from_identity(ident: base.Identity) -> str:
    text = base.norm(" ".join(x for x in (ident.attribute, ident.variety) if x))
    if any(token in text for token in ("incorrect texture", "surface processing error", "texture error")):
        return "INCORRECT_TEXTURE"
    if any(token in text for token in ("correct texture", "standard texture", "correct surface")):
        return "CORRECT_TEXTURE"
    return "UNPROVEN"


def _surface_variant_from_listing_text(text: str) -> str:
    normalized = base.norm(text)
    if any(
        token in normalized
        for token in (
            "ma-incorrect texture",
            "incorrect texture",
            "surface processing error",
            "texture error",
            "加工エラー",
            "表面加工エラー",
        )
    ):
        return "INCORRECT_TEXTURE"
    if any(token in normalized for token in ("correct texture", "standard texture", "correct surface")):
        return "CORRECT_TEXTURE"
    return "UNPROVEN"


def references(sales: Iterable[base.Sold], now: Optional[datetime] = None) -> list[base.Reference]:
    """Exclude officially affected families when GCC does not prove the variant.

    The official notice states that correct and erroneous surface processing both
    exist for the affected MA cards, so an unqualified GCC identity cannot safely
    anchor one exact market against the other.
    """
    safe_sales = []
    for sale in sales:
        if _official_surface_error_applicable(sale.identity):
            if _surface_variant_from_identity(sale.identity) == "UNPROVEN":
                continue
        safe_sales.append(sale)
    return _ORIGINAL_REFERENCES(safe_sales, now)


def identity_check(ask: base.Ask, ident: base.Identity) -> tuple[bool, str]:
    transaction_text = _transaction_scope(ask)
    text = _full_identity_scope(ask)

    if base.has_any(transaction_text, base.AUCTION):
        return False, "ongoing_auction"
    if base.has_any(transaction_text, base.MULTI):
        return False, "multi_item_listing"
    if ident.number not in base.number_tokens(text):
        return False, "collector_number_unproven"
    if not base.PSA10_RE.search(base.unicodedata.normalize("NFKC", text)):
        return False, "psa10_unproven"
    if not base.has_any(text, base.JP):
        return False, "language_unproven"
    if not (base.contains(text, ident.set_name) or base.contains(text, ident.name)):
        return False, "card_or_set_unproven"

    ed = base.norm(ident.edition)
    if ed and (ident.year <= 2003 or ed not in {"unlimited", "standard"}) and not base.contains(text, ed):
        return False, "edition_unproven"

    if _official_surface_error_applicable(ident):
        expected_surface = _surface_variant_from_identity(ident)
        observed_surface = _surface_variant_from_listing_text(text)
        if expected_surface == "UNPROVEN":
            return False, "official_surface_variant_unresolved"
        if observed_surface != expected_surface:
            return False, "official_surface_variant_unproven"

    for raw in (ident.attribute, ident.variety):
        token = base.norm(raw)
        if token and any(
            sensitive in token
            for sensitive in (
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
        ) and not base.contains(text, token):
            return False, "microvariant_unproven"
    return True, "strict_text_identity"


_ORIGINAL_REFERENCES = base.references
_ORIGINAL_IDENTITY_CHECK = base.identity_check


def install() -> None:
    base.references = references
    base.identity_check = identity_check


def main() -> None:
    install()
    base.main()


if __name__ == "__main__":
    main()
