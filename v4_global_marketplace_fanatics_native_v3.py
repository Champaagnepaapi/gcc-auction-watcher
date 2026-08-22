"""Fanatics-native v3: real public title schemas, still fail-closed.

Retrieval is one broad public `Pokemon` Buy Now query.  The title parser accepts
only explicit Pokemon + language + PSA grade + collector-number evidence.  It
then builds a small bounded set/name candidate set and requires the existing
TCGdex resolver to return EXACT.  A provider set-label mismatch is tolerated
only when TCGdex proves name+localId unique in the explicit language; otherwise
it remains blocking.  No ASK is ever treated as SOLD.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Callable, Optional, Sequence

import v4_canonical_multimarket as multimarket
import v4_global_economic_confirmation as confirmed
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_native_v2 as v2
import v4_global_marketplace_scan as scan
from v4_global_market_core import CommercialIdentity
from v4_global_marketplace_discovery import MarketplaceListing, listing_from_observation
from v4_global_marketplace_scan import ScanStatus
from v4_market_fanatics_bridge import fanatics_fixed_offer


_MAX_CANDIDATES = 10
_LANGUAGE_RE = re.compile(r"\b(?P<language>Japanese|English|JPN|ENG)\b", re.IGNORECASE)
_POKEMON_RE = re.compile(r"\bPok[eé]mon\b", re.IGNORECASE)
_PSA_RE = re.compile(
    r"\bPSA\s*(?:GEM\s*MT\s*)?(?P<grade>10(?:\.0)?|9(?:\.0)?|8\.5|8(?:\.0)?)\b",
    re.IGNORECASE,
)
_HASH_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])#0*(?P<local>\d{1,4})(?![A-Za-z0-9])")
_NO_NUMBER_RE = re.compile(r"\bNo\.?\s*0*(?P<local>\d{1,4})\b", re.IGNORECASE)
_BARE_BEFORE_PSA_RE = re.compile(r"(?<![A-Za-z0-9])0*(?P<local>\d{1,4})\s+(?=PSA\b)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_TRAILING_FINISH_RE = re.compile(
    r"\s+(?:MASTER\s*BALL|MASTERBALL|POK[EÉ]\s*BALL|POKEBALL|REVERSE\s+HOLO|REVERSE|HOLO)\s*$",
    re.IGNORECASE,
)


def _language(title: str) -> tuple[str, str] | None:
    matches = {_normalize_lang(match.group("language")) for match in _LANGUAGE_RE.finditer(title)}
    matches.discard(None)
    if len(matches) != 1:
        return None
    return next(iter(matches))


def _normalize_lang(value: str) -> tuple[str, str] | None:
    key = str(value or "").casefold()
    if key in {"japanese", "jpn"}:
        return "ja", "Japanese"
    if key in {"english", "eng"}:
        return "en", "English"
    return None


def _number_match(prefix: str):
    collector_matches = []
    for match in v1._FULL_NUMBER_RE.finditer(prefix):
        left = match.group("left")
        if re.search(r"\d", left):
            collector_matches.append(match)
    if len(collector_matches) == 1:
        match = collector_matches[0]
        return match, v1._norm_local(match.group("left")), True
    if len(collector_matches) > 1:
        return None, "", False

    for regex in (_HASH_NUMBER_RE, _NO_NUMBER_RE, _BARE_BEFORE_PSA_RE):
        matches = list(regex.finditer(prefix))
        if len(matches) == 1:
            return matches[0], v1._norm_local(matches[0].group("local")), False
        if len(matches) > 1:
            return None, "", False
    return None, "", False


def _strip_scaffolding(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _POKEMON_RE.sub(" ", text)
    text = _LANGUAGE_RE.sub(" ", text)
    text = _YEAR_RE.sub(" ", text)
    # `JPN.SWSH` leaves the era token after the explicit JPN language marker.
    text = re.sub(r"^[\s.]+", "", text)
    text = " ".join(text.split())
    return text.strip(" -|:./")


def _dimensions(title: str) -> tuple[str, str, str]:
    edition, finish, variant = v1._explicit_dimensions(title)
    upper = unicodedata.normalize("NFKC", str(title or "")).upper()
    if re.search(r"\bMASTER\s*BALL\b|\bMASTERBALL\b", upper):
        finish = "Master Ball"
    elif re.search(r"\bPOK[EÉ]\s*BALL\b|\bPOKEBALL\b", upper):
        finish = "Poke Ball"
    return edition, finish, variant


def _coordinate(
    *,
    title: str,
    language_code: str,
    language_label: str,
    grade: str,
    local_id: str,
    set_name: str,
    name: str,
) -> Optional[v1.FanaticsNativeCoordinate]:
    clean_set = " ".join(unicodedata.normalize("NFKC", str(set_name or "")).split()).strip(" -|:")
    clean_name = " ".join(unicodedata.normalize("NFKC", str(name or "")).split()).strip(" -|:")
    if not clean_name:
        return None
    year_match = _YEAR_RE.search(title)
    edition, finish, variant = _dimensions(title)
    return v1.FanaticsNativeCoordinate(
        year=int(year_match.group(0)) if year_match else 0,
        language_code=language_code,
        language_label=language_label,
        set_name=clean_set,
        name=clean_name,
        local_id=local_id,
        grade=grade,
        edition=edition,
        finish=finish,
        variant=variant,
    )


def _flexible_candidates(title: str) -> tuple[list[v1.FanaticsNativeCoordinate], str]:
    normalized = " ".join(unicodedata.normalize("NFKC", str(title or "")).split())
    if not _POKEMON_RE.search(normalized):
        return [], "not_pokemon"
    language = _language(normalized)
    if language is None:
        return [], "explicit_language_unproven"
    psa = _PSA_RE.search(normalized)
    if psa is None:
        return [], "supported_psa_grade_unproven"
    grade = v1._grade(psa.group("grade"))
    if grade not in v1._SUPPORTED_GRADES:
        return [], "unsupported_psa_grade"

    prefix = normalized[: psa.start()].strip()
    number_match, local_id, full_fraction = _number_match(prefix)
    if number_match is None or not local_id:
        return [], "collector_number_unproven"

    left = _strip_scaffolding(prefix[: number_match.start()])
    right = _strip_scaffolding(prefix[number_match.end() :])
    output: list[v1.FanaticsNativeCoordinate] = []
    seen: set[tuple[str, str]] = set()

    def add(set_name: str, name: str) -> None:
        coordinate = _coordinate(
            title=normalized,
            language_code=language[0],
            language_label=language[1],
            grade=grade,
            local_id=local_id,
            set_name=set_name,
            name=name,
        )
        if coordinate is None:
            return
        key = (v1._norm(coordinate.set_name), v1._norm(coordinate.name))
        if key in seen or len(output) >= _MAX_CANDIDATES:
            return
        seen.add(key)
        output.append(coordinate)

    # Name after the collector number, including `FA/Pikachu` style titles.
    if right:
        add(left, v2._POST_NUMBER_DESCRIPTOR_RE.sub("", right).strip())
        if "/" in right:
            add(left, right.rsplit("/", 1)[-1].strip())

    # `... Set - FA/Eevee #210` style titles put the name after a slash before #.
    if "/" in left:
        lhs, rhs = left.rsplit("/", 1)
        lhs = re.sub(
            r"(?:^|\s[-|:]\s*)(?:FA|SAR|AR|SR|UR|HR|RRR|RR|CHR|CSR|SSR|HOLO|REVERSE)\s*$",
            "",
            lhs,
            flags=re.IGNORECASE,
        ).strip(" -|:")
        add(lhs, rhs)

    # An explicit trailing finish is a provider field, not part of the card
    # name. Prefer the stripped shape before noisier original partitions so the
    # bounded candidate cap cannot starve the exact set/name coordinate.
    stripped_finish = _TRAILING_FINISH_RE.sub("", left).strip()
    left_forms: list[str] = []
    if stripped_finish and stripped_finish != left:
        left_forms.append(stripped_finish)
    left_forms.append(left)

    for form in left_forms:
        tokens = form.split()
        # Card name as bounded suffix: the common Fanatics schema.
        for width in range(1, min(4, max(0, len(tokens) - 1)) + 1):
            add(" ".join(tokens[:-width]), " ".join(tokens[-width:]))
        # Some provider titles put name first and set after it.
        for width in range(1, min(3, max(0, len(tokens) - 1)) + 1):
            add(" ".join(tokens[width:]), " ".join(tokens[:width]))
        # Full fraction + explicit language can safely reach TCGdex uniqueness
        # even when Fanatics omits the set from H1 (e.g. `Vivillon 107/106 ...`).
        if full_fraction and len(tokens) <= 4:
            add("", form)

    return output, "fanatics_flexible_exact_candidates" if output else "set_or_name_unproven"


def fanatics_coordinate_candidates_v3(title: str) -> tuple[list[v1.FanaticsNativeCoordinate], str]:
    strict, strict_reason = v2.fanatics_coordinate_candidates(title)
    flexible, flexible_reason = _flexible_candidates(title)
    output: list[v1.FanaticsNativeCoordinate] = []
    seen: set[tuple[str, str, str]] = set()
    for coordinate in (*strict, *flexible):
        key = (v1._norm(coordinate.set_name), v1._norm(coordinate.name), coordinate.local_id)
        if key in seen or len(output) >= _MAX_CANDIDATES:
            continue
        seen.add(key)
        output.append(coordinate)
    if output:
        return output, "fanatics_v3_candidate_partitions"
    return [], flexible_reason if flexible_reason != "fanatics_flexible_exact_candidates" else strict_reason


def _resolve_coordinate_v3(
    coordinate: v1.FanaticsNativeCoordinate,
    *,
    title: str,
    proof_text: str,
    resolver: Callable[[Any], multimarket.CanonicalCard],
) -> tuple[Optional[CommercialIdentity], str]:
    canonical = resolver(v1._lot_for_coordinate(coordinate))
    if canonical.status != "EXACT":
        return None, f"tcgdex_{(canonical.reason or canonical.status or 'no_match').casefold()}"
    if canonical.language_code != coordinate.language_code:
        return None, "tcgdex_language_conflict"
    if v1._norm_local(canonical.local_id) != coordinate.local_id:
        return None, "tcgdex_local_id_conflict"
    if v1._norm(canonical.name) != v1._norm(coordinate.name):
        return None, "tcgdex_card_name_conflict"

    provider_set = v1._norm(coordinate.set_name)
    canonical_set = v1._norm(canonical.set_name)
    set_exact = bool(provider_set and provider_set == canonical_set)
    if not set_exact and not canonical.unique_name_number:
        return None, "tcgdex_set_unproven_without_unique_name_localid"

    exposed = v2._exposed_collector_numbers(f"{title}\n{proof_text}")
    canonical_number = v1._norm_full_number(canonical.full_number)
    if exposed and canonical_number not in exposed:
        return None, "conflicting_full_fraction"

    identity = CommercialIdentity(
        name=canonical.name,
        set_name=canonical.set_name,
        number=canonical.full_number or coordinate.local_id,
        language=coordinate.language_code,
        grader="PSA",
        grade=coordinate.grade,
        edition=coordinate.edition,
        finish=coordinate.finish,
        variant=coordinate.variant,
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "commercial_identity_incomplete"
    return identity, "FANATICS_TCGDEX_SET_EXACT" if set_exact else "FANATICS_TCGDEX_UNIQUE_NAME_LOCALID"


def resolve_fanatics_native_identity_v3(
    title: str,
    *,
    proof_text: str = "",
    resolver: Callable[[Any], multimarket.CanonicalCard] = multimarket.resolve_tcgdex_card,
) -> v1.FanaticsNativeResolution:
    candidates, parse_reason = fanatics_coordinate_candidates_v3(title)
    if not candidates:
        return v1.FanaticsNativeResolution("NO_MATCH", parse_reason)
    exact: dict[str, tuple[CommercialIdentity, v1.FanaticsNativeCoordinate, str]] = {}
    reasons: Counter[str] = Counter()
    for coordinate in candidates:
        identity, reason = _resolve_coordinate_v3(
            coordinate,
            title=title,
            proof_text=proof_text,
            resolver=resolver,
        )
        if identity is None:
            reasons[reason] += 1
            continue
        exact[identity.strict_key] = (identity, coordinate, reason)
    if len(exact) > 1:
        return v1.FanaticsNativeResolution("AMBIGUOUS", "multiple_exact_tcgdex_partitions")
    if len(exact) == 1:
        identity, coordinate, reason = next(iter(exact.values()))
        return v1.FanaticsNativeResolution("EXACT", reason, coordinate=coordinate, identity=identity)
    reason = reasons.most_common(1)[0][0] if reasons else "tcgdex_no_exact_partition"
    return v1.FanaticsNativeResolution("NO_MATCH", reason, coordinate=candidates[0])


def scan_fanatics_native_inventory_v3(
    page: Any,
    _seeds: Sequence[Any],
    *,
    observed_at,
    max_detail_pages: int = 200,
    scroll_rounds: int = 20,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    try:
        urls, rounds = v2._fanatics_pokemon_urls(page, scroll_rounds=scroll_rounds)
    except Exception as error:
        return [], ScanStatus("fanatics", "ERROR", detail=type(error).__name__, complete=False)

    confirmed.install_global_external_market_stack()
    output: list[MarketplaceListing] = []
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
        price = scan.legacy._price_from_usd_text(before_guide)
        if price is None:
            rejects["price_unproven"] += 1
            continue
        resolution = resolve_fanatics_native_identity_v3(
            title,
            proof_text=before_guide,
            resolver=multimarket.resolve_tcgdex_card,
        )
        if resolution.status != "EXACT" or resolution.identity is None:
            rejects[resolution.reason or resolution.status or "identity_unproven"] += 1
            continue
        observation = fanatics_fixed_offer(
            identity=resolution.identity,
            price_usd=price,
            observed_at=observed_at,
            source_id=url,
            identity_proven=True,
            buyer_fee_rate=0.0,
            note=(
                "Fanatics broad Pokemon Buy Now ASK; explicit language/grade/number -> exact TCGdex; "
                f"{resolution.reason}; GCC history not required; ASK is not SOLD"
            ),
        )
        output.append(listing_from_observation(observation, source_url=url, title=title))

    return output, ScanStatus(
        "fanatics",
        "OK",
        pages=rounds,
        candidates=len(urls),
        exact=len(output),
        detail=(
            "broad Pokemon marketplace retrieval; explicit language+PSA+collector coordinate -> exact TCGdex; "
            f"GCC identity catalog not required; rejects={dict(rejects)}"
        ),
        complete=len(urls) <= limit,
    )


def install_global_marketplace_fanatics_native_v3() -> None:
    v1.scan_fanatics_native_inventory = scan_fanatics_native_inventory_v3
    v1.install_global_fanatics_native_identity()
