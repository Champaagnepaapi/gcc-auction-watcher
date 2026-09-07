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
from collections import Counter
from typing import Callable, Optional, Sequence, Any

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
        # The URL slug is public provider text and often preserves the exact
        # language even when a dynamic H1 projection drops it. It is evidence,
        # not an inferred default, and conflicting language tokens still block.
        proof_text = f"{before_guide}\nProvider URL: {url}"
        resolution = v3.resolve_fanatics_native_identity_v3(
            title,
            proof_text=proof_text,
            resolver=multimarket.resolve_tcgdex_card,
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
    global _INSTALLED, _ORIGINAL_RESOLVER
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = v3.resolve_fanatics_native_identity_v3
    v3.resolve_fanatics_native_identity_v3 = resolve_fanatics_native_identity_with_provider_language
    v3.scan_fanatics_native_inventory_v3 = scan_fanatics_native_inventory_with_provider_language
    _INSTALLED = True
