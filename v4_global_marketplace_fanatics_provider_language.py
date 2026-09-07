"""Recover Fanatics language only from explicit provider evidence.

Some current Fanatics Buy Now H1 projections omit the long language token even
when that same public product surface exposes it in breadcrumb/body text, in the
provider URL slug, or as the short H1 language codes ``EN`` / ``JP``. This layer
accepts only explicit provider evidence. It never infers language from absence,
card names, sets or TCGdex translations.

After that explicit provider proof, the existing Fanatics v3 resolver must still
return one exact TCGdex-compatible commercial identity. All set/name/number,
grade and microvariant gates therefore remain unchanged.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any, Callable, Optional, Sequence

import v4_canonical_multimarket as multimarket
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_native_v3 as v3


_INSTALLED = False
_ORIGINAL_RESOLVER: Optional[Callable[..., v1.FanaticsNativeResolution]] = None
_FANATICS_DIAGNOSTICS_MAX = 60
_fanatics_diagnostics_count = 0

_LANGUAGE_PATTERNS = (
    re.compile(r"\bPok[eé]mon[\s_-]+(?P<language>Japanese|English|JPN|ENG)\b", re.I),
    re.compile(r"\b(?:Card\s+)?Language\s*:?\s*(?P<language>Japanese|English|JPN|ENG)\b", re.I),
)

# Current Fanatics H1s also use PSA-style short language fields, for example
# ``... DRI EN #193/182 ... PSA 10`` and ``... Promos JP #098/SV-P ... PSA 10``.
# EN/JP are accepted only inside an H1-like Pokemon+PSA title. A generic page
# token such as a locale selector therefore cannot prove language.
_SHORT_TITLE_LANGUAGE_RE = re.compile(
    r"^(?=.*\bPok[eé]mon\b)(?=.*\bPSA\s*(?:GEM\s*MT\s*)?"
    r"(?:10(?:\.0)?|9(?:\.0)?|8\.5|8(?:\.0)?)\b)"
    r".*?\b(?P<language>EN|JP)\b",
    re.I,
)


def _normalize_provider_language(value: object) -> tuple[str, str] | None:
    key = str(value or "").strip().casefold()
    if key == "en":
        return "en", "English"
    if key == "jp":
        return "ja", "Japanese"
    return v3._normalize_lang(str(value or ""))


def _short_title_language(title: str) -> tuple[str, str] | None:
    match = _SHORT_TITLE_LANGUAGE_RE.search(str(title or ""))
    if match is None:
        return None
    return _normalize_provider_language(match.group("language"))


def _provider_language(
    proof_text: str,
    *,
    title: str = "",
) -> tuple[str, str] | None:
    found: set[tuple[str, str]] = set()
    short = _short_title_language(title)
    if short is not None:
        found.add(short)
    for pattern in _LANGUAGE_PATTERNS:
        for match in pattern.finditer(str(proof_text or "")):
            normalized = _normalize_provider_language(match.group("language"))
            if normalized is not None:
                found.add(normalized)
    if len(found) != 1:
        return None
    return next(iter(found))


def _diagnostics_enabled() -> bool:
    value = os.getenv("GLOBAL_FANATICS_REJECTION_DIAGNOSTICS", "").strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    return os.getenv("GITHUB_EVENT_NAME", "").strip().casefold() == "pull_request"


def _diagnostic_language(value: tuple[str, str] | None) -> str:
    return value[0] if value is not None else "none"


def _emit_fanatics_diagnostic(
    *,
    title: str,
    url: str,
    proof_text: str,
    resolution: v1.FanaticsNativeResolution,
) -> None:
    """Emit bounded public listing diagnostics without changing resolution.

    No additional provider or TCGdex request is made here. Production schedules
    remain inert unless explicitly opted in; pull-request live validation enables
    the probe automatically so rejection causes can be audited listing by listing.
    """
    global _fanatics_diagnostics_count
    if not _diagnostics_enabled() or _fanatics_diagnostics_count >= _FANATICS_DIAGNOSTICS_MAX:
        return
    _fanatics_diagnostics_count += 1
    provider_language = _provider_language(proof_text, title=title)
    short_language = _short_title_language(title)
    candidates, parse_reason = v3._flexible_candidates(title)
    print(
        "[FANATICS_DIAG] "
        f"status={resolution.status or 'UNKNOWN'} "
        f"reason={resolution.reason or 'unknown'} "
        f"provider_language={_diagnostic_language(provider_language)} "
        f"short_h1_language={_diagnostic_language(short_language)} "
        f"candidate_count={len(candidates)} "
        f"parse_reason={parse_reason or 'unknown'} "
        f"url={url} | title={str(title or '').replace(chr(10), ' ')[:500]}"
    )


def _probe_title(title: str, label: str) -> str:
    return f"{str(title or '').strip()} {label}".strip()


def _title_with_provider_language(
    title: str,
    language: tuple[str, str],
) -> str:
    """Replace one explicit EN/JP H1 field with the long parser label.

    The replacement is retrieval normalization only. The short token itself is
    provider evidence; final acceptance still requires the unchanged exact
    Fanatics/TCGdex resolver.
    """
    raw = str(title or "")
    match = _SHORT_TITLE_LANGUAGE_RE.search(raw)
    if match is not None:
        observed = _normalize_provider_language(match.group("language"))
        if observed == language:
            start, end = match.span("language")
            return f"{raw[:start]}{language[1]}{raw[end:]}"
    return _probe_title(raw, language[1])


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

    language = _provider_language(proof_text, title=title)
    if language is None:
        return original

    recovered = _ORIGINAL_RESOLVER(
        _title_with_provider_language(title, language),
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


def scan_fanatics_native_inventory_with_provider_language(
    page: Any,
    _seeds: Sequence[Any],
    *,
    observed_at,
    max_detail_pages: int = 200,
    scroll_rounds: int = 20,
):
    """Reuse v3 scanning while adding the public provider URL to proof text."""
    try:
        urls, rounds = v3.v2._fanatics_pokemon_urls(page, scroll_rounds=scroll_rounds)
    except Exception as error:
        return [], v3.ScanStatus("fanatics", "ERROR", detail=type(error).__name__, complete=False)

    v3.confirmed.install_global_external_market_stack()
    output = []
    rejects: Counter[str] = Counter()
    limit = max(1, int(max_detail_pages))
    for url in urls[:limit]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(500)
            title = page.locator("h1").first.inner_text(timeout=4000).strip()
            body = page.locator("body").inner_text(timeout=5000)
        except Exception:
            rejects["page_error"] += 1
            continue
        upper = body.upper()
        if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
            rejects["unavailable_or_sold"] += 1
            continue
        before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.IGNORECASE)[0]
        price = v3.scan.legacy._price_from_usd_text(before_guide)
        if price is None:
            rejects["price_unproven"] += 1
            continue
        # The URL slug and H1 are public provider text. Explicit EN/JP fields are
        # accepted only in the bounded H1 schema above; conflicting evidence
        # remains fail-closed.
        proof_text = f"{before_guide}\nProvider URL: {url}"
        resolution = v3.resolve_fanatics_native_identity_v3(
            title,
            proof_text=proof_text,
            resolver=multimarket.resolve_tcgdex_card,
        )
        _emit_fanatics_diagnostic(
            title=title,
            url=url,
            proof_text=proof_text,
            resolution=resolution,
        )
        if resolution.status != "EXACT" or resolution.identity is None:
            rejects[resolution.reason or resolution.status or "identity_unproven"] += 1
            continue
        observation = v3.fanatics_fixed_offer(
            identity=resolution.identity,
            price_usd=price,
            observed_at=observed_at,
            source_id=url,
            identity_proven=True,
            buyer_fee_rate=0.0,
            note=(
                "Fanatics broad Pokemon Buy Now ASK; explicit provider language/grade/number -> exact TCGdex; "
                f"{resolution.reason}; GCC history not required; ASK is not SOLD"
            ),
        )
        output.append(v3.listing_from_observation(observation, source_url=url, title=title))

    return output, v3.ScanStatus(
        "fanatics",
        "OK",
        pages=rounds,
        candidates=len(urls),
        exact=len(output),
        detail=(
            "broad Pokemon marketplace retrieval; explicit provider language+PSA+collector coordinate -> exact TCGdex; "
            f"GCC identity catalog not required; rejects={dict(rejects)}"
        ),
        complete=len(urls) <= limit,
    )


def install_global_marketplace_fanatics_provider_language() -> None:
    global _INSTALLED, _ORIGINAL_RESOLVER, _fanatics_diagnostics_count
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = v3.resolve_fanatics_native_identity_v3
    v3.resolve_fanatics_native_identity_v3 = resolve_fanatics_native_identity_with_provider_language
    v3.scan_fanatics_native_inventory_v3 = scan_fanatics_native_inventory_with_provider_language
    _fanatics_diagnostics_count = 0
    _INSTALLED = True
