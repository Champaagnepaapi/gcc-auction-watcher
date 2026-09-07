"""Recover Fanatics language only from explicit provider evidence.

Some current Fanatics Buy Now H1 projections omit the language token even when
that same public product surface exposes it in breadcrumb/body text or in the
provider URL slug.  This layer accepts only explicit ``Pokemon Japanese`` /
``Pokemon English`` or ``Language: ...`` evidence.  It never infers language
from absence, card names, sets or TCGdex translations.

After that explicit provider proof, the existing Fanatics v3 resolver must still
return one exact TCGdex-compatible commercial identity.  All set/name/number,
grade and microvariant gates therefore remain unchanged.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import v4_canonical_multimarket as multimarket
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_native_v3 as v3


_INSTALLED = False
_ORIGINAL_RESOLVER: Optional[Callable[..., v1.FanaticsNativeResolution]] = None

_LANGUAGE_PATTERNS = (
    re.compile(r"\bPok[eé]mon[\s_-]+(?P<language>Japanese|English|JPN|ENG)\b", re.I),
    re.compile(r"\b(?:Card\s+)?Language\s*:?\s*(?P<language>Japanese|English|JPN|ENG)\b", re.I),
)


def _provider_language(proof_text: str) -> tuple[str, str] | None:
    found: set[tuple[str, str]] = set()
    for pattern in _LANGUAGE_PATTERNS:
        for match in pattern.finditer(str(proof_text or "")):
            normalized = v3._normalize_lang(match.group("language"))
            if normalized is not None:
                found.add(normalized)
    if len(found) != 1:
        return None
    return next(iter(found))


def _probe_title(title: str, label: str) -> str:
    return f"{str(title or '').strip()} {label}".strip()


def resolve_fanatics_native_identity_with_provider_language(
    title: str,
    *,
    proof_text: str = "",
    resolver: Callable[[object], multimarket.CanonicalCard] = multimarket.resolve_tcgdex_card,
) -> v1.FanaticsNativeResolution:
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(title, proof_text=proof_text, resolver=resolver)
    if original.status != "NO_MATCH" or original.reason != "explicit_language_unproven":
        return original

    language = _provider_language(proof_text)
    if language is None:
        return original

    recovered = _ORIGINAL_RESOLVER(
        _probe_title(title, language[1]),
        proof_text=proof_text,
        resolver=resolver,
    )
    if recovered.status != "EXACT" or recovered.identity is None:
        # Preserve blocking ERROR/AMBIGUOUS semantics from the exact resolver;
        # otherwise keep the original missing-language no-match.
        return recovered if recovered.status in {"ERROR", "AMBIGUOUS"} else original
    if recovered.identity.language != language[0]:
        return v1.FanaticsNativeResolution(
            "AMBIGUOUS",
            "fanatics_provider_language_conflict",
            coordinate=recovered.coordinate,
        )
    return v1.FanaticsNativeResolution(
        "EXACT",
        "FANATICS_PROVIDER_TEXT_LANGUAGE_TCGDEX_EXACT",
        coordinate=recovered.coordinate,
        identity=recovered.identity,
    )


def install_global_marketplace_fanatics_provider_language() -> None:
    global _INSTALLED, _ORIGINAL_RESOLVER
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = v3.resolve_fanatics_native_identity_v3
    v3.resolve_fanatics_native_identity_v3 = resolve_fanatics_native_identity_with_provider_language
    _INSTALLED = True
