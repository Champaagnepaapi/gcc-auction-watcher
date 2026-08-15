from __future__ import annotations

from . import cmapi_sold_identity_uniqueness as uniqueness
from . import neon_cmapi_ingest as core
from . import neon_cmapi_ingest_v2 as v2


_ORIGINAL_MATCH = core._sale_offer_matches_card
_RESOLVER = uniqueness.TCGdexSoldUniquenessResolver()


def _smart_sale_offer_matches_card(card, offer) -> bool:
    # Signed/autographed slabs are a different commercial variant and must not
    # become normal unsigned comparables even if macro identity is unique.
    if uniqueness.is_signed_or_autographed(offer.get("title")):
        return False
    if _ORIGINAL_MATCH(card, offer):
        return True
    return uniqueness.catalog_rescue_matches(card, offer, _RESOLVER)


def main() -> int:
    core._sale_offer_matches_card = _smart_sale_offer_matches_card
    try:
        return v2.main()
    finally:
        core._sale_offer_matches_card = _ORIGINAL_MATCH


if __name__ == "__main__":
    raise SystemExit(main())
