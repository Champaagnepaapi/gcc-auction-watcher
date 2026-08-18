from __future__ import annotations

import re
import unicodedata
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Mapping, Optional

import watcher
import v4_canonical_multimarket as multimarket


# Backport only deterministic provider-facing retrieval from the proven V5
# lineage. Identity remains TCGdex-first and all V4 acceptance, grader/grade,
# variant and economic gates stay authoritative after retrieval.
#
# PR #127 separated provider-facing collector-number formatting from local
# matching normalization because PokeTrace exposes padded surfaces such as
# 069/062 and 109/098. Keep that boundary intact here.
#
# Japanese GCC/TCGdex identities can also expose an exact localized TCGdex
# name. That localized name is acceptance-only provider metadata tied to the
# same card_id + set_id + localId; it must never replace the canonical provider
# search term. Live post-#127 retrieval returned Japanese PokeTrace candidates
# from canonical/romanized search names, while post-#128 localized-script search
# regressed those probes to zero candidates. Keep retrieval and acceptance
# aliases separate.


@dataclass(frozen=True)
class PokeTraceRetrievalContext:
    search_name: str
    card_number: str
    game: str
    language_code: str
    canonical_card_id: str = ""
    provider_name_aliases: tuple[str, ...] = ()


_ACTIVE_CONTEXT: ContextVar[Optional[PokeTraceRetrievalContext]] = ContextVar(
    "v4_poketrace_retrieval_context", default=None
)
_ORIGINAL_EVIDENCE = multimarket._poketrace_evidence
_ORIGINAL_PACED_GET = multimarket._paced_poketrace_get
_INSTALLED = False


_CARD_NUMBER_LABEL_PREFIX = re.compile(
    r"^(?:#\s*|no(?:\.|\s+)\s*|n[°º]\s*|number\s+)",
    flags=re.IGNORECASE,
)


def _normalize_card_number(value: object) -> str:
    """Canonical numeric-safe number comparison used after retrieval."""

    compact = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = _CARD_NUMBER_LABEL_PREFIX.sub("", compact)
    compact = re.sub(r"\s+", "", compact).lstrip("#")
    parts = compact.split("/", 1)

    def canonical(part: str) -> str:
        match = re.fullmatch(r"([A-Za-z]*)(0*\d+)([A-Za-z-]*)", part)
        if not match:
            return multimarket._normalize(part).replace(" ", "")
        prefix, digits, suffix = match.groups()
        return f"{prefix.casefold()}{int(digits)}{suffix.casefold()}"

    return "/".join(canonical(part) for part in parts)


def _provider_card_number(value: object) -> str:
    """Keep TCGdex's proven collector-number surface for provider retrieval.

    Safe cleanup removes only presentation labels/whitespace. Leading zeroes,
    alphanumeric prefixes/suffixes and denominator padding remain intact.
    """

    compact = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = _CARD_NUMBER_LABEL_PREFIX.sub("", compact)
    return re.sub(r"\s+", "", compact).lstrip("#")


def _exact_market_game(language_code: str) -> str:
    code = str(language_code or "").strip().casefold()
    if code == "en":
        return "pokemon"
    if code in {"ja", "jp"}:
        return "pokemon-japanese"
    return ""


def _exact_tcgdex_localized_name(
    canonical: multimarket.CanonicalCard,
    language_code: str,
) -> str:
    """Return only a same-card, same-set TCGdex localized provider alias.

    Any transport/problem, malformed detail, card/set/localId conflict or
    missing name disables the alias and leaves the original retrieval path.
    """

    card_id = str(canonical.card_id or "").strip()
    set_id = str(canonical.set_id or "").strip()
    local_id = str(canonical.local_id or "").strip()
    if not (language_code and card_id and set_id and local_id):
        return ""
    try:
        status, detail = multimarket._fetch_tcgdex_card_detail(language_code, card_id)
    except Exception:
        return ""
    if status != 200 or not isinstance(detail, Mapping):
        return ""
    if str(detail.get("id") or "").strip() not in {"", card_id}:
        return ""
    if not multimarket._same_card_number(detail.get("localId"), local_id):
        return ""
    set_payload = detail.get("set")
    if not isinstance(set_payload, Mapping):
        return ""
    if str(set_payload.get("id") or "").strip() != set_id:
        return ""
    return str(detail.get("name") or "").strip()


def _retrieval_context(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
) -> Optional[PokeTraceRetrievalContext]:
    """Build the stable #127 retrieval context without extra network work."""

    language_code = str(canonical.language_code or "").strip().casefold()
    if not language_code:
        language_code = multimarket._language_code(lot)
    game = _exact_market_game(language_code)
    if not game:
        return None

    canonical_name = str(canonical.name or "").strip()
    card_number = _provider_card_number(
        canonical.full_number or canonical.local_id or lot.card_number
    )
    if not canonical_name or not card_number:
        return None

    return PokeTraceRetrievalContext(
        search_name=canonical_name,
        card_number=card_number,
        game=game,
        language_code=language_code,
        canonical_card_id=str(canonical.card_id or "").strip(),
    )


def _provider_retrieval_context(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
) -> Optional[PokeTraceRetrievalContext]:
    """Keep canonical retrieval and attach same-card TCGdex acceptance aliases."""

    context = _retrieval_context(lot, canonical)
    if context is None or context.language_code != "ja":
        return context
    localized = _exact_tcgdex_localized_name(canonical, context.language_code)
    if not localized or multimarket._normalize(localized) == multimarket._normalize(
        context.search_name
    ):
        return context
    return PokeTraceRetrievalContext(
        search_name=context.search_name,
        card_number=context.card_number,
        game=context.game,
        language_code=context.language_code,
        canonical_card_id=context.canonical_card_id,
        provider_name_aliases=(localized,),
    )


def exact_provider_name_alias_matches(
    canonical: multimarket.CanonicalCard,
    candidate_name: object,
) -> bool:
    """True only for an alias attached to this exact active TCGdex card."""

    context = _ACTIVE_CONTEXT.get()
    if context is None:
        return False
    if not context.canonical_card_id or context.canonical_card_id != str(
        canonical.card_id or ""
    ).strip():
        return False
    observed = multimarket._normalize(candidate_name)
    return bool(
        observed
        and any(
            observed == multimarket._normalize(alias)
            for alias in context.provider_name_aliases
            if alias
        )
    )


def _structured_paced_get(
    budget: multimarket.RequestBudget,
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
):
    """Inject only structured provider retrieval fields on `/cards` calls."""

    context = _ACTIVE_CONTEXT.get()
    if context is None or not url.rstrip("/").endswith("/cards"):
        return _ORIGINAL_PACED_GET(budget, url, params=params)

    structured = dict(params or {})
    structured["search"] = context.search_name
    structured["card_number"] = context.card_number
    structured["game"] = context.game
    # Keep V4's market/result cap/product_type untouched. Exact acceptance still
    # runs afterward through the production fail-closed gate.
    return _ORIGINAL_PACED_GET(budget, url, params=structured)


def _structured_poketrace_evidence(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
    budget: multimarket.RequestBudget,
    now,
):
    # V4's exact graded PokeTrace gate currently supports only EN and JA market
    # records. Do not spend a provider request on FR/DE/etc. only to reject the
    # returned record later on language. Fallback APR/eBay behavior is unchanged.
    context = _provider_retrieval_context(lot, canonical)
    if context is None:
        language_code = str(canonical.language_code or "").strip().casefold()
        if not language_code:
            language_code = multimarket._language_code(lot)
        return watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(lot),
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=(
                "PokeTrace exact-market non applicable pour cette langue/coordonnée "
                f"({language_code or 'unknown'}); fallback externe conservé"
            ),
            fetched_at=now,
        )

    token = _ACTIVE_CONTEXT.set(context)
    try:
        return _ORIGINAL_EVIDENCE(lot, canonical, budget, now)
    finally:
        _ACTIVE_CONTEXT.reset(token)


def install_v4_poketrace_market_retrieval() -> None:
    """Install structured EN/JA PokeTrace retrieval, idempotently."""

    global _INSTALLED
    if _INSTALLED:
        return
    multimarket._paced_poketrace_get = _structured_paced_get
    multimarket._poketrace_evidence = _structured_poketrace_evidence
    _INSTALLED = True
