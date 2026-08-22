"""Fanatics language proof for titles that omit an explicit EN/JA marker.

Language is never inferred from absence.  The fallback probes both supported
languages through the already-installed exact Fanatics/TCGdex resolver and may
accept a result only when one language has deterministic set-level proof while
the competing language is cleanly excluded (or resolves only through a
contradictory provider-set partition).  Ambiguity and provider errors remain
blocking.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import v4_canonical_multimarket as multimarket
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_cross_locale as cross_locale
import v4_global_marketplace_fanatics_native_v3 as v3


_MAX_LANGUAGE_PROOF_TITLES = 20
_language_proof_titles = 0
_ORIGINAL_RESOLVER: Optional[Callable[..., v1.FanaticsNativeResolution]] = None

_CLEAN_TCGDEX_NO_MATCH = "tcgdex_aucune identité tcgdex exacte"
_SET_EXACT_REASONS = {
    "FANATICS_H1_NATIVE_TCGDEX_EXACT",
    "FANATICS_TCGDEX_SET_EXACT",
    "FANATICS_TCGDEX_CROSS_LOCALE_SET_LOCALID_EXACT",
}


def _norm(value: object) -> str:
    return v1._norm(value)


def _set_level_proven(resolution: v1.FanaticsNativeResolution) -> bool:
    if resolution.status != "EXACT" or resolution.identity is None or resolution.coordinate is None:
        return False
    if resolution.reason in _SET_EXACT_REASONS:
        return True
    # Cross-locale generic recovery is normally name+localId based.  It can
    # count as set-level proof only when the provider partition and recovered
    # TCGdex set label are themselves exactly equal.
    if resolution.reason == "FANATICS_TCGDEX_CROSS_LOCALE_UNIQUE_NAME_LOCALID":
        return bool(
            resolution.coordinate.set_name
            and resolution.identity.set_name
            and _norm(resolution.coordinate.set_name) == _norm(resolution.identity.set_name)
        )
    return False


def _cleanly_excludes_language(resolution: v1.FanaticsNativeResolution) -> bool:
    if resolution.status == "NO_MATCH" and resolution.reason == _CLEAN_TCGDEX_NO_MATCH:
        return True
    # An exact card reached only by ignoring a contradictory provider set does
    # not compete with a set-exact language proof.
    if (
        resolution.status == "EXACT"
        and resolution.identity is not None
        and resolution.coordinate is not None
        and resolution.coordinate.set_name
        and resolution.identity.set_name
        and _norm(resolution.coordinate.set_name) != _norm(resolution.identity.set_name)
    ):
        return True
    return False


def _choose_language_resolution(
    original: v1.FanaticsNativeResolution,
    english: v1.FanaticsNativeResolution,
    japanese: v1.FanaticsNativeResolution,
) -> v1.FanaticsNativeResolution:
    proven = [
        result
        for result in (english, japanese)
        if _set_level_proven(result)
    ]
    if len(proven) > 1:
        return v1.FanaticsNativeResolution("AMBIGUOUS", "fanatics_language_multiple_set_exact")
    if not proven:
        return original

    winner = proven[0]
    loser = japanese if winner is english else english
    if loser.status in {"ERROR", "AMBIGUOUS"}:
        return v1.FanaticsNativeResolution(
            "AMBIGUOUS",
            "fanatics_language_competing_probe_unresolved",
            coordinate=winner.coordinate,
        )
    if not _cleanly_excludes_language(loser):
        return original

    return v1.FanaticsNativeResolution(
        "EXACT",
        "FANATICS_TCGDEX_LANGUAGE_UNIQUE_SET_EXACT",
        coordinate=winner.coordinate,
        identity=winner.identity,
    )


def _probe_title(title: str, language_label: str) -> str:
    # The marker is synthetic retrieval input only.  It is never itself used as
    # proof; final acceptance requires the two-language deterministic decision
    # above.  Appending keeps the provider H1 structure otherwise unchanged.
    return f"{title.strip()} {language_label}".strip()


def resolve_fanatics_native_identity_with_language_proof(
    title: str,
    *,
    proof_text: str = "",
    resolver: Callable[[Any], multimarket.CanonicalCard] = multimarket.resolve_tcgdex_card,
) -> v1.FanaticsNativeResolution:
    global _language_proof_titles
    assert _ORIGINAL_RESOLVER is not None

    original = _ORIGINAL_RESOLVER(title, proof_text=proof_text, resolver=resolver)
    if original.status != "NO_MATCH" or original.reason != "explicit_language_unproven":
        return original
    if _language_proof_titles >= _MAX_LANGUAGE_PROOF_TITLES:
        return v1.FanaticsNativeResolution("NO_MATCH", "fanatics_language_probe_budget_exhausted")

    _language_proof_titles += 1
    english = _ORIGINAL_RESOLVER(
        _probe_title(title, "English"),
        proof_text=proof_text,
        resolver=resolver,
    )
    japanese = _ORIGINAL_RESOLVER(
        _probe_title(title, "Japanese"),
        proof_text=proof_text,
        resolver=resolver,
    )
    return _choose_language_resolution(original, english, japanese)


def install_global_marketplace_fanatics_language_proof() -> None:
    global _ORIGINAL_RESOLVER, _language_proof_titles
    cross_locale.install_global_marketplace_fanatics_cross_locale()
    current = v3.resolve_fanatics_native_identity_v3
    if getattr(current, "_fanatics_language_proof_installed", False):
        v3.install_global_marketplace_fanatics_native_v3()
        return

    _ORIGINAL_RESOLVER = current
    _language_proof_titles = 0
    resolve_fanatics_native_identity_with_language_proof._fanatics_language_proof_installed = True  # type: ignore[attr-defined]
    v3.resolve_fanatics_native_identity_v3 = resolve_fanatics_native_identity_with_language_proof
    v3.install_global_marketplace_fanatics_native_v3()
