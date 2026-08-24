"""Immutable TCGdex-source fallback for explicit numeric Magi coordinates.

This recovery is used only after the normal Japanese TCGdex REST proof returns a
transient/provider error or exhausts its bounded budget.  The Magi provider must
already expose an exact set code plus numeric ``local/official`` coordinate.
The immutable cards-database pin must then prove all of:

- exact set file and set id;
- exact Japanese set name;
- exact official card count matching the printed denominator;
- exact card file for the printed local id;
- that card file imports the same exact set;
- exact Japanese card name from that pinned card file.

No fuzzy matching, translation, current market metadata or per-card exception is
used.  Clean REST NO_MATCH results are never overridden by this fallback.
"""
from __future__ import annotations

import os
import re
from typing import Callable, Optional

import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as retrieval_v3
import v4_tcgdex_source_pinned_finish as source_finish


_SOURCE_MAX_REQUESTS_PER_RUN = max(
    0, int(os.getenv("GLOBAL_MAGI_STANDARD_SOURCE_MAX_REQUESTS", "32"))
)
_SOURCE_REQUESTS = 0
_SOURCE_TEXT_CACHE: dict[str, Optional[str]] = {}
_ORIGINAL_PROOF = None
_INSTALLED = False


def clear_standard_source_runtime_state() -> None:
    global _SOURCE_REQUESTS
    _SOURCE_REQUESTS = 0
    _SOURCE_TEXT_CACHE.clear()


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


def _set_source_proof(text: str, *, set_code: str, denominator: str) -> tuple[str, str]:
    id_match = re.search(r"\bid\s*:\s*['\"]([^'\"]+)['\"]", text)
    if id_match is None or id_match.group(1).strip() != set_code:
        return "", ""
    name_match = re.search(
        r"\bname\s*:\s*\{.*?\bja\s*:\s*['\"]([^'\"]+)['\"]",
        text,
        re.DOTALL,
    )
    count_match = re.search(r"\bofficial\s*:\s*(\d+)", text)
    if name_match is None or count_match is None:
        return "", ""
    try:
        if int(count_match.group(1)) != int(denominator):
            return "", ""
    except (TypeError, ValueError):
        return "", ""
    return name_match.group(1).strip(), str(int(count_match.group(1)))


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


def _local_candidates(local: str) -> tuple[str, ...]:
    if not local.isdigit():
        return ()
    value = str(int(local))
    return tuple(dict.fromkeys((value, value.zfill(2), value.zfill(3), value.zfill(4))))


def source_pinned_standard_proof(
    *,
    full_number: str,
    set_code: str,
    source_text_get: Callable[[str], Optional[str]] = _source_text,
) -> Optional[retrieval_v3.JapaneseCatalogProof]:
    """Prove one explicit numeric Magi coordinate from the immutable source pin."""
    raw_number = str(full_number or "").strip()
    exact_set = str(set_code or "").strip()
    if "/" not in raw_number or not native._SET_ID_RE.fullmatch(exact_set):
        return None
    local, denominator = raw_number.split("/", 1)
    if not local.isdigit() or not denominator.isdigit():
        return None

    series = source_finish._asia_series_for_set_id(exact_set)
    if not series:
        return None
    set_path = f"data-asia/{series}/{exact_set}.ts"
    set_text = source_text_get(set_path)
    if not set_text:
        return None
    set_name_ja, official_count = _set_source_proof(
        set_text,
        set_code=exact_set,
        denominator=denominator,
    )
    if not set_name_ja or not official_count:
        return None

    for source_local in _local_candidates(local):
        card_path = f"data-asia/{series}/{exact_set}/{source_local}.ts"
        card_text = source_text_get(card_path)
        if not card_text:
            continue
        name_ja = _card_name_ja(card_text, set_code=exact_set)
        if not name_ja:
            continue
        return retrieval_v3.JapaneseCatalogProof(
            status="EXACT",
            reason="TCGDEX_SOURCE_PINNED_STANDARD_COORDINATE_EXACT",
            card_id=f"{exact_set}-{source_local}",
            set_id=exact_set,
            name_ja=name_ja,
            set_name_ja=set_name_ja,
            local_id=source_local,
            official_count=official_count,
        )
    return None


def _transient_or_budget(proof: retrieval_v3.JapaneseCatalogProof) -> bool:
    if proof.status == "BUDGET":
        return True
    if proof.status != "ERROR":
        return False
    return bool(re.search(r"HTTP_(?:-1|429|5\d\d)(?:$|\D)", str(proof.reason or "")))


def _proof_with_standard_source_fallback(resolver, *, full_number, set_code, cache):
    assert _ORIGINAL_PROOF is not None
    original = _ORIGINAL_PROOF(
        resolver,
        full_number=full_number,
        set_code=set_code,
        cache=cache,
    )
    if not _transient_or_budget(original):
        return original
    recovered = source_pinned_standard_proof(
        full_number=full_number,
        set_code=set_code,
    )
    if recovered is None:
        return original
    cache[(str(set_code).casefold(), str(full_number).upper())] = recovered
    return recovered


def install_global_marketplace_magi_standard_source_proof() -> None:
    """Install transient-only immutable fallback inside the Global Magi process."""
    global _ORIGINAL_PROOF, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_PROOF = native._proof_for_coordinate
    native._proof_for_coordinate = _proof_with_standard_source_fallback
    _INSTALLED = True
