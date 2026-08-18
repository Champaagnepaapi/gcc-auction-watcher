from __future__ import annotations

import re
import unicodedata
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Mapping, Optional

import watcher
import v4_canonical_multimarket as multimarket


# Backport only the proven market-retrieval contract from the current V5
# PokeTrace provider. Identity remains TCGdex-first and all V4 acceptance,
# grader/grade, variant and economic gates stay in v4_canonical_multimarket.
#
# V4 previously queried `/cards` with one unstructured string such as
# "Lapras 177/172" and no language/game discriminator. That is especially
# harmful for Japanese cards because PokeTrace separates `pokemon` from
# `pokemon-japanese`. V5 already solved this by sending card_number + game as
# structured retrieval filters. This module recovers that behavior without
# letting PokeTrace become an identity resolver.


@dataclass(frozen=True)
class PokeTraceRetrievalContext:
    search_name: str
    card_number: str
    game: str
    language_code: str


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
    """Use the same safe structured-number normalization as V5 PokeTrace."""

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


def _exact_market_game(language_code: str) -> str:
    code = str(language_code or "").strip().casefold()
    if code == "en":
        return "pokemon"
    if code in {"ja", "jp"}:
        return "pokemon-japanese"
    return ""


def _retrieval_context(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
) -> Optional[PokeTraceRetrievalContext]:
    language_code = str(canonical.language_code or "").strip().casefold()
    if not language_code:
        language_code = multimarket._language_code(lot)
    game = _exact_market_game(language_code)
    if not game:
        return None

    search_name = str(canonical.name or "").strip()
    card_number = _normalize_card_number(
        canonical.full_number or canonical.local_id or lot.card_number
    )
    if not search_name or not card_number:
        return None
    return PokeTraceRetrievalContext(
        search_name=search_name,
        card_number=card_number,
        game=game,
        language_code=language_code,
    )


def _structured_paced_get(
    budget: multimarket.RequestBudget,
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
):
    """Inject only V5-proven structured retrieval fields on `/cards` calls."""

    context = _ACTIVE_CONTEXT.get()
    if context is None or not url.rstrip("/").endswith("/cards"):
        return _ORIGINAL_PACED_GET(budget, url, params=params)

    structured = dict(params or {})
    structured["search"] = context.search_name
    structured["card_number"] = context.card_number
    structured["game"] = context.game
    # Keep V4's existing market, result cap and product_type exactly as supplied
    # by the canonical provider. These fields only improve retrieval; exact
    # acceptance still runs afterward through `_candidate_exact_for_canonical`.
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
    context = _retrieval_context(lot, canonical)
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
