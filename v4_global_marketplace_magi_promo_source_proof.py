"""Pinned-source recovery for exact Magi Japanese S-P promo coordinates.

Measured Magi listings expose coordinates such as ``324/S-P``. The live TCGdex
Japanese REST resolver currently treats these as an alphanumeric localId, while
the immutable cards-database pin stores the same card at
``data-asia/S/S-P/324.ts``.

This layer is intentionally narrow. For ``S-P`` only, it checks the immutable
source *before* spending REST budget, requires numeric localId + denominator
``S-P``, requires the pinned card file to import that exact set, and extracts
the Japanese card name from the same file. The normal Magi resolver still
performs provider-name proof and same-card Latin projection afterwards. No
fuzzy match, translation or provider market metadata participates.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as retrieval_v3
import v4_tcgdex_source_pinned_finish as source_finish


_SOURCE_MAX_REQUESTS_PER_RUN = 8
_SOURCE_REQUESTS = 0
_SOURCE_TEXT_CACHE: dict[str, Optional[str]] = {}
_ORIGINAL_PROOF = None
_INSTALLED = False


def _source_text(path: str) -> Optional[str]:
    global _SOURCE_REQUESTS
    if path in _SOURCE_TEXT_CACHE:
        return _SOURCE_TEXT_CACHE[path]
    if _SOURCE_REQUESTS >= _SOURCE_MAX_REQUESTS_PER_RUN:
        return None
    _SOURCE_REQUESTS += 1
    try:
        response = source_finish._SESSION.get(
            f"{source_finish._SOURCE_RAW_BASE}/{path}",
            timeout=source_finish._SOURCE_TIMEOUT_SECONDS,
        )
    except Exception:
        _SOURCE_TEXT_CACHE[path] = None
        return None
    if int(getattr(response, "status_code", 0) or 0) != 200:
        _SOURCE_TEXT_CACHE[path] = None
        return None
    text = str(getattr(response, "text", "") or "")
    if not text or len(text) > 250_000:
        _SOURCE_TEXT_CACHE[path] = None
        return None
    _SOURCE_TEXT_CACHE[path] = text
    return text


def _card_name_ja(text: str, *, set_code: str) -> str:
    set_import = re.compile(
        rf"^\s*import\s+Set\s+from\s+['\"]\.\./{re.escape(set_code)}['\"]\s*;?\s*$",
        re.MULTILINE,
    )
    if set_import.search(text) is None:
        return ""
    head = text.split("illustrator:", 1)[0]
    match = re.search(
        r"\bname\s*:\s*\{\s*ja\s*:\s*['\"]([^'\"]+)['\"]",
        head,
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def source_pinned_s_p_proof(
    *,
    full_number: str,
    set_code: str,
    source_text_get: Callable[[str], Optional[str]] = _source_text,
) -> Optional[retrieval_v3.JapaneseCatalogProof]:
    """Return exact immutable proof only for a numeric ``local/S-P`` coordinate."""
    if str(set_code or "").strip().casefold() != "s-p" or "/" not in str(full_number or ""):
        return None
    local, denominator = str(full_number).strip().upper().split("/", 1)
    if not local.isdigit() or denominator.casefold() != "s-p":
        return None
    numeric = str(int(local))
    if not numeric or int(numeric) <= 0:
        return None

    candidates = tuple(dict.fromkeys((numeric, numeric.zfill(3))))
    for source_local in candidates:
        path = f"data-asia/S/S-P/{source_local}.ts"
        text = source_text_get(path)
        if not text:
            continue
        name_ja = _card_name_ja(text, set_code="S-P")
        if not name_ja:
            continue
        return retrieval_v3.JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_SOURCE_PINNED_S_P_PROMO_EXACT",
            card_id=f"S-P-{source_local}",
            set_id="S-P",
            name_ja=name_ja,
            set_name_ja="S-P",
            local_id=source_local,
            official_count="",
        )
    return None


def _proof_with_pinned_s_p(resolver, *, full_number, set_code, cache):
    assert _ORIGINAL_PROOF is not None
    # The provider coordinate itself selects S-P exactly. Probe the immutable
    # source first so known REST namespace gaps do not consume the shared JA
    # request budget and starve normal cards later in the Magi sweep.
    if str(set_code or "").strip().casefold() == "s-p":
        recovered = source_pinned_s_p_proof(full_number=full_number, set_code=set_code)
        if recovered is not None:
            cache[(str(set_code).casefold(), str(full_number).upper())] = recovered
            return recovered
    return _ORIGINAL_PROOF(
        resolver,
        full_number=full_number,
        set_code=set_code,
        cache=cache,
    )


def install_global_marketplace_magi_promo_source_proof() -> None:
    """Install the measured S-P recovery inside the Global Magi process only."""
    global _ORIGINAL_PROOF, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_PROOF = native._proof_for_coordinate
    native._proof_for_coordinate = _proof_with_pinned_s_p
    _INSTALLED = True
