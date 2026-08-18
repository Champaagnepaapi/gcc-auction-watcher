from __future__ import annotations

from dataclasses import dataclass, replace
import os
import re
from typing import Mapping

import requests

import v4_canonical_multimarket as canonical


# Immutable upstream catalogue snapshot already used by the V4 TCGdex recovery
# line.  Runtime finish proof is fetched only from this exact commit: provider
# metadata can never choose or move the source of truth.
_SOURCE_COMMIT = "af33c9ac882e2acfadffaf19e8083aa976d12983"
_SOURCE_RAW_BASE = (
    "https://raw.githubusercontent.com/tcgdex/cards-database/"
    f"{_SOURCE_COMMIT}"
)
_SOURCE_ENABLED = os.getenv("V4_TCGDEX_SOURCE_FINISH_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
_SOURCE_TIMEOUT_SECONDS = max(
    0.5, float(os.getenv("V4_TCGDEX_SOURCE_FINISH_TIMEOUT", "3"))
)
_SOURCE_MAX_REQUESTS_PER_RUN = max(
    0, int(os.getenv("V4_TCGDEX_SOURCE_FINISH_MAX_REQUESTS_PER_RUN", "12"))
)

_ALLOWED_FINISH_KEYS = frozenset({"normal", "holo", "reverse"})
_SAFE_COORDINATE = re.compile(r"^[A-Za-z0-9._-]+$")
_SESSION = requests.Session()
_SOURCE_CACHE: dict[str, "SourcePinnedFinishProof | None"] = {}
_SOURCE_REQUESTS = 0
_ORIGINAL_RESOLVER = None


@dataclass(frozen=True)
class SourcePinnedFinishProof:
    finishes: tuple[str, ...]
    source_path: str
    source_commit: str = _SOURCE_COMMIT


def clear_source_finish_runtime_state() -> None:
    """Clear process-local proof cache/budget (mainly useful for tests)."""

    global _SOURCE_REQUESTS
    _SOURCE_CACHE.clear()
    _SOURCE_REQUESTS = 0


def _same_local_id(first: object, second: object) -> bool:
    first_left, _ = canonical._canonical_number_parts(first)
    second_left, _ = canonical._canonical_number_parts(second)
    return bool(first_left and second_left and first_left == second_left)


def _asia_series_for_set_id(set_id: object) -> str:
    """Return the deterministic cards-database era directory for an Asian set.

    Examples: S12a -> S, SV6a -> SV, SM12a -> SM, DPt4 -> DPt,
    S-P -> S.  Unknown/non-catalogue shapes return an empty string and therefore
    fail closed without a network request.
    """

    raw = str(set_id or "").strip()
    if not raw or not _SAFE_COORDINATE.fullmatch(raw):
        return ""
    match = re.match(r"^([A-Za-z]+)(?=\d|-)", raw)
    return match.group(1) if match else ""


def _candidate_local_ids(card: canonical.CanonicalCard) -> tuple[str, ...]:
    values: list[str] = []

    local = str(card.local_id or "").strip().lstrip("#")
    if local:
        values.append(local)

    full_left, _ = canonical._number_parts(card.full_number)
    if full_left:
        values.append(full_left)

    set_id = str(card.set_id or "").strip()
    card_id = str(card.card_id or "").strip()
    prefix = f"{set_id}-"
    if set_id and card_id.startswith(prefix):
        suffix = card_id[len(prefix) :].strip()
        if suffix:
            values.append(suffix)

    deduped: list[str] = []
    for value in values:
        if value in deduped or not _SAFE_COORDINATE.fullmatch(value):
            continue
        deduped.append(value)
    return tuple(deduped)


def _source_paths_for_card(card: canonical.CanonicalCard) -> tuple[str, ...]:
    if card.status != "EXACT":
        return ()
    if str(card.language_code or "").strip().casefold() not in {"ja", "jp"}:
        return ()

    set_id = str(card.set_id or "").strip()
    card_id = str(card.card_id or "").strip()
    local_id = str(card.local_id or "").strip().lstrip("#")
    series = _asia_series_for_set_id(set_id)
    if not (series and set_id and card_id and local_id):
        return ()

    expected_prefix = f"{set_id}-"
    if not card_id.startswith(expected_prefix):
        return ()
    if not _same_local_id(card_id[len(expected_prefix) :], local_id):
        return ()

    return tuple(
        f"data-asia/{series}/{set_id}/{candidate}.ts"
        for candidate in _candidate_local_ids(card)
    )


def _extract_variants_block(text: str) -> str:
    match = re.search(r"\bvariants\s*:\s*\[", text)
    if match is None:
        return ""

    start = text.find("[", match.start())
    if start < 0:
        return ""

    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "[":
            depth += 1
            continue
        if char == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return ""


def _parse_source_finish_proof(
    text: str,
    *,
    set_id: str,
    source_path: str,
) -> SourcePinnedFinishProof | None:
    # The path itself is derived from the already-proven exact TCGdex identity;
    # additionally require the source file to import that exact set.
    set_import = re.compile(
        rf"import\s+Set\s+from\s+['\"]\.\./{re.escape(set_id)}['\"]\s*;"
    )
    if set_import.search(text) is None:
        return None

    block = _extract_variants_block(text)
    if not block:
        return None

    observed = [
        value.strip().casefold()
        for value in re.findall(r"\btype\s*:\s*['\"]([^'\"]+)['\"]", block)
    ]
    if not observed or any(value not in _ALLOWED_FINISH_KEYS for value in observed):
        return None

    finishes = tuple(key for key in ("normal", "holo", "reverse") if key in observed)
    if not finishes:
        return None
    return SourcePinnedFinishProof(finishes=finishes, source_path=source_path)


def _fetch_source_proof(path: str, *, set_id: str) -> SourcePinnedFinishProof | None:
    global _SOURCE_REQUESTS
    if path in _SOURCE_CACHE:
        return _SOURCE_CACHE[path]
    if not _SOURCE_ENABLED or _SOURCE_REQUESTS >= _SOURCE_MAX_REQUESTS_PER_RUN:
        return None

    _SOURCE_REQUESTS += 1
    try:
        response = _SESSION.get(
            f"{_SOURCE_RAW_BASE}/{path}", timeout=_SOURCE_TIMEOUT_SECONDS
        )
    except requests.RequestException:
        _SOURCE_CACHE[path] = None
        return None
    except Exception:
        _SOURCE_CACHE[path] = None
        return None

    if int(getattr(response, "status_code", 0) or 0) != 200:
        _SOURCE_CACHE[path] = None
        return None
    text = str(getattr(response, "text", "") or "")
    # Card source files are tiny.  Refuse an unexpectedly large response rather
    # than parsing arbitrary content from a network intermediary.
    if not text or len(text) > 250_000:
        _SOURCE_CACHE[path] = None
        return None

    proof = _parse_source_finish_proof(text, set_id=set_id, source_path=path)
    _SOURCE_CACHE[path] = proof
    return proof


def source_pinned_finish_proof(
    card: canonical.CanonicalCard,
) -> SourcePinnedFinishProof | None:
    """Return immutable finish proof for an already exact Japanese TCGdex card.

    No provider field participates in lookup.  Missing source, timeouts, budget
    exhaustion, malformed source or non-exact identity all return no proof.
    """

    paths = _source_paths_for_card(card)
    if not paths:
        return None
    set_id = str(card.set_id or "").strip()
    for path in paths:
        proof = _fetch_source_proof(path, set_id=set_id)
        if proof is not None:
            return proof
    return None


def apply_source_pinned_finish(card: canonical.CanonicalCard) -> canonical.CanonicalCard:
    """Replace only REST normal/holo/reverse flags when pinned source proves them.

    This is a generic catalogue reconciliation layer, not a per-card exception.
    Exact language + card ID + set ID + localId choose an immutable upstream file;
    every non-finish flag from the REST response is preserved unchanged.
    """

    proof = source_pinned_finish_proof(card)
    if proof is None:
        return card

    variants = dict(card.variants) if isinstance(card.variants, Mapping) else {}
    desired = set(proof.finishes)
    changed = False
    for key in _ALLOWED_FINISH_KEYS:
        value = key in desired
        if variants.get(key) is not value:
            changed = True
        variants[key] = value
    if not changed:
        return card
    return replace(card, variants=variants)


def _resolve_with_source_pinned_finish(lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    return apply_source_pinned_finish(_ORIGINAL_RESOLVER(lot))


def install_v4_tcgdex_source_pinned_finish() -> None:
    """Install generic post-identity reconciliation against immutable TCGdex source."""

    global _ORIGINAL_RESOLVER
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_tcgdex_source_pinned_finish", False):
        return
    _ORIGINAL_RESOLVER = current
    _resolve_with_source_pinned_finish._v4_tcgdex_source_pinned_finish = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_source_pinned_finish
