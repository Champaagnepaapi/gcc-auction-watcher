"""Fanatics-native v2 recovery for the V4 Global marketplace lane.

Fanatics is scanned with one broad public Pokemon retrieval query, never with a
card-targeted search. Identity is then proven from the listing H1 through a
small bounded set/name partition set and the existing exact TCGdex resolver.
Retrieval breadth never relaxes the final identity gate.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence
from urllib.parse import quote, urlparse, parse_qs

import v4_canonical_multimarket as multimarket
import v4_global_economic_confirmation as confirmed
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_scan as scan
from v4_global_market_core import CommercialIdentity
from v4_global_marketplace_discovery import MarketplaceListing, listing_from_observation
from v4_global_marketplace_scan import ScanStatus
from v4_market_fanatics_bridge import fanatics_fixed_offer


FANATICS_POKEMON_BROWSE = scan.legacy.FANATICS_MARKETPLACE.format(
    query=quote("Pokemon", safe="")
)
_MAX_SUFFIX_NAME_TOKENS = 4
_MAX_COORDINATE_CANDIDATES = 6

_TITLE_SHELL_RE = re.compile(
    r"^\s*(?:(?:Pok[eé]mon)\s+(?P<year_first>\d{4})|"
    r"(?P<year_second>\d{4})\s+(?:Pok[eé]mon))\s+"
    r"(?P<language>Japanese|English)\s+"
    r"(?P<body>.+?)\s+PSA\s*(?:GEM\s*MT\s*)?"
    r"(?P<grade>10(?:\.0)?|9(?:\.0)?|8\.5|8(?:\.0)?)\b",
    re.IGNORECASE,
)
_LOCAL_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])#0*(?P<local>[A-Za-z0-9-]+)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_POST_NUMBER_DESCRIPTOR_RE = re.compile(
    r"^(?:FA|SAR|AR|SR|UR|HR|RRR|RR|CHR|CSR|SSR|HOLO|REVERSE)\s*[/|:-]\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FanaticsTitleShell:
    year: int
    language_code: str
    language_label: str
    grade: str
    local_id: str
    left: str
    right: str
    normalized_title: str


def _clean_set(value: str) -> str:
    text = " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).strip(" -|:")
    text = v1.retrieval_v1.FANATICS_SET_CODE_RE.sub("", text).strip()
    text = v1.retrieval_v2.FANATICS_ERA_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"^Pok[eé]mon\s+", "", text, flags=re.IGNORECASE).strip()
    return text


def _parse_shell(title: str) -> tuple[Optional[FanaticsTitleShell], str]:
    normalized = " ".join(unicodedata.normalize("NFKC", str(title or "")).split())
    match = _TITLE_SHELL_RE.search(normalized)
    if not match:
        return None, "fanatics_title_schema_unproven"

    language = v1._LANGUAGE_CODES.get(match.group("language").casefold())
    if language is None:
        return None, "language_unproven"
    grade = v1._grade(match.group("grade"))
    if grade not in v1._SUPPORTED_GRADES:
        return None, "unsupported_psa_grade"

    body = " ".join(match.group("body").split())
    markers = list(_LOCAL_MARKER_RE.finditer(body))
    if len(markers) != 1:
        return None, "fanatics_local_id_unproven" if not markers else "fanatics_local_id_ambiguous"
    marker = markers[0]
    local_id = v1._norm_local(marker.group("local"))
    if not local_id:
        return None, "fanatics_local_id_unproven"

    year_text = match.group("year_first") or match.group("year_second")
    return (
        FanaticsTitleShell(
            year=int(year_text),
            language_code=language[0],
            language_label=language[1],
            grade=grade,
            local_id=local_id,
            left=body[: marker.start()].strip(" -|:"),
            right=body[marker.end() :].strip(" -|:"),
            normalized_title=normalized,
        ),
        "fanatics_h1_shell",
    )


def _coordinate_from_parts(shell: FanaticsTitleShell, set_name: str, name: str) -> Optional[v1.FanaticsNativeCoordinate]:
    set_name = _clean_set(set_name)
    name = " ".join(unicodedata.normalize("NFKC", str(name or "")).split()).strip(" -|:")
    if not set_name or not name:
        return None
    edition, finish, variant = v1._explicit_dimensions(shell.normalized_title)
    return v1.FanaticsNativeCoordinate(
        year=shell.year,
        language_code=shell.language_code,
        language_label=shell.language_label,
        set_name=set_name,
        name=name,
        local_id=shell.local_id,
        grade=shell.grade,
        edition=edition,
        finish=finish,
        variant=variant,
    )


def fanatics_coordinate_candidates(title: str) -> tuple[list[v1.FanaticsNativeCoordinate], str]:
    """Return a bounded deterministic partition set for one public Fanatics H1."""
    shell, reason = _parse_shell(title)
    if shell is None:
        return [], reason

    output: list[v1.FanaticsNativeCoordinate] = []
    seen: set[tuple[str, str]] = set()

    def add(set_name: str, name: str) -> None:
        coordinate = _coordinate_from_parts(shell, set_name, name)
        if coordinate is None:
            return
        key = (v1._norm(coordinate.set_name), v1._norm(coordinate.name))
        if key in seen or len(output) >= _MAX_COORDINATE_CANDIDATES:
            return
        seen.add(key)
        output.append(coordinate)

    # Existing Fanatics schema: an explicit rarity token can delimit set/name.
    rarity_matches = list(v1._RARITY_RE.finditer(shell.left))
    if len(rarity_matches) == 1:
        rarity = rarity_matches[0]
        add(shell.left[: rarity.start()], shell.left[rarity.end() :])

    # Real Fanatics titles also occur without a rarity boundary. Card names are
    # tested only as a bounded suffix (1..4 tokens); TCGdex must prove set+name.
    tokens = shell.left.split()
    for width in range(1, min(_MAX_SUFFIX_NAME_TOKENS, max(0, len(tokens) - 1)) + 1):
        add(" ".join(tokens[:-width]), " ".join(tokens[-width:]))

    # A second observed public form places a descriptor/name after #localId,
    # e.g. "#001 FA/Pikachu". The descriptor is retrieval syntax only; the
    # suffix name still requires exact TCGdex proof against the set before #.
    if shell.right:
        add(shell.left, _POST_NUMBER_DESCRIPTOR_RE.sub("", shell.right).strip())
        if "/" in shell.right:
            add(shell.left, shell.right.rsplit("/", 1)[-1].strip())

    return output, "fanatics_h1_candidate_partitions" if output else "set_or_name_unproven"


def _exposed_collector_numbers(text: str) -> set[str]:
    """Return only slash tokens that can actually be collector numbers.

    Fanatics can use slashes as display separators (for example `FA/Pikachu`).
    The legacy generic detector intentionally accepts alphanumerics on both
    sides, so using it raw would turn that display syntax into a fake conflicting
    card number. A real collector coordinate must contain a digit on its left
    side; this still preserves numeric and alphanumeric promo coordinates.
    """
    output: set[str] = set()
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    for match in v1._FULL_NUMBER_RE.finditer(normalized):
        left = match.group("left")
        if not re.search(r"\d", left):
            continue
        output.add(v1._norm_full_number(f"{left}/{match.group('right')}"))
    return output


def _resolve_coordinate(
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
    if v1._norm(canonical.set_name) != v1._norm(coordinate.set_name):
        return None, "tcgdex_set_name_conflict"
    if v1._norm(canonical.name) != v1._norm(coordinate.name):
        return None, "tcgdex_card_name_conflict"

    exposed = _exposed_collector_numbers(f"{title}\n{proof_text}")
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
    return identity, "FANATICS_H1_PARTITION_TCGDEX_EXACT"


def resolve_fanatics_native_identity_v2(
    title: str,
    *,
    proof_text: str = "",
    resolver: Callable[[Any], multimarket.CanonicalCard] = multimarket.resolve_tcgdex_card,
) -> v1.FanaticsNativeResolution:
    candidates, parse_reason = fanatics_coordinate_candidates(title)
    if not candidates:
        return v1.FanaticsNativeResolution("NO_MATCH", parse_reason)

    exact: dict[str, tuple[CommercialIdentity, v1.FanaticsNativeCoordinate]] = {}
    reasons: Counter[str] = Counter()
    for coordinate in candidates:
        identity, reason = _resolve_coordinate(
            coordinate,
            title=title,
            proof_text=proof_text,
            resolver=resolver,
        )
        if identity is None:
            reasons[reason] += 1
            continue
        exact[identity.strict_key] = (identity, coordinate)

    if len(exact) > 1:
        return v1.FanaticsNativeResolution("AMBIGUOUS", "multiple_exact_tcgdex_partitions")
    if len(exact) == 1:
        identity, coordinate = next(iter(exact.values()))
        return v1.FanaticsNativeResolution(
            "EXACT",
            "FANATICS_H1_PARTITION_TCGDEX_EXACT",
            coordinate=coordinate,
            identity=identity,
        )
    if reasons:
        reason = reasons.most_common(1)[0][0]
        return v1.FanaticsNativeResolution("NO_MATCH", reason, coordinate=candidates[0])
    return v1.FanaticsNativeResolution("NO_MATCH", "tcgdex_no_exact_partition", coordinate=candidates[0])


@dataclass(frozen=True)
class FanaticsCollection:
    urls: list[str]
    observations: int
    state: str
    stop_reason: str
    http_status: Optional[int]
    container_present: bool
    complete: bool = False
    navigation_labels: tuple[str, ...] = ()
    scroll_regions: int = 0
    pagination: str = "NOT_INSPECTED"

    def __iter__(self):
        # Preserve the two-value collector API for existing callers.
        yield self.urls
        yield self.observations

    @property
    def detail(self) -> str:
        return (f"collection={self.state}; http={self.http_status}; "
                f"observations={self.observations}; stop={self.stop_reason}; "
                f"container_present={self.container_present}; "
                f"navigation_labels={self.navigation_labels}; scroll_regions={self.scroll_regions}; "
                f"pagination={self.pagination}")


_CONTENT_SNAPSHOT = r"""() => {
    const root = document.querySelector('main, [role="main"]');
    const labels = root ? Array.from(root.querySelectorAll('h1,h2,[role="status"]')) : [];
    const visible = el => !!(el.getClientRects().length);
    const empty = labels.some(el => visible(el) &&
        /^(no results found|no items found|no matching items found)[.!]?$/i.test(el.innerText.trim()));
    const hrefs = root ? Array.from(root.querySelectorAll('a[href]')).slice(0,1800).map(a => a.href) : [];
    const navigation_labels = [...document.querySelectorAll('button,[role=button],nav a')].filter(visible)
      .map(e=>(e.getAttribute('aria-label')||e.innerText||'').trim())
      .filter(s=>/next|previous|page|more|load|show/i.test(s) && s.length<=80).slice(0,12);
    const scroll_regions = root ? [...root.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+50 && /auto|scroll/.test(getComputedStyle(e).overflowY)).length : 0;
    return {container_present: !!root && visible(root), empty_proven: empty, hrefs, navigation_labels, scroll_regions};
}"""


def _fanatics_browse_location_matches(url: str) -> bool:
    actual, expected = urlparse(url), urlparse(FANATICS_POKEMON_BROWSE)
    return (actual.scheme == expected.scheme and actual.netloc == expected.netloc
            and actual.path.rstrip('/') == expected.path.rstrip('/')
            and all(parse_qs(actual.query).get(key) == value
                    for key, value in parse_qs(expected.query).items()))


def _fanatics_pokemon_urls(page: Any, *, scroll_rounds: int) -> FanaticsCollection:
    response = page.goto(FANATICS_POKEMON_BROWSE, wait_until="domcontentloaded", timeout=25000)
    raw_status = getattr(response, "status", None)
    status = raw_status if isinstance(raw_status, int) else None
    found: list[str] = []
    observations, stable = 0, 0
    container = False
    navigation_labels, scroll_regions = (), 0
    last_advanced_inventory: tuple[str, ...] = ()
    pagination = "NOT_INSPECTED"

    def result(state, reason, complete=False):
        return FanaticsCollection(found, observations, state, reason, status, container, complete, navigation_labels, scroll_regions, pagination)

    if status is not None and not 200 <= status < 300:
        return result("UNAVAILABLE", "HTTP_UNAVAILABLE")
    for _ in range(min(20, max(1, int(scroll_rounds)))):
        if not _fanatics_browse_location_matches(str(getattr(page, "url", ""))):
            return result("UNAVAILABLE", "UNEXPECTED_LOCATION")
        observations += 1
        try:
            snapshot = page.evaluate(_CONTENT_SNAPSHOT)
            if not isinstance(snapshot, dict):
                return result("UNAVAILABLE", "DOM_UNREADABLE")
            container = snapshot.get("container_present") is True
            navigation_labels = tuple(str(s)[:80] for s in snapshot.get("navigation_labels", [])[:12])
            scroll_regions = int(snapshot.get("scroll_regions") or 0)
            hrefs = snapshot.get("hrefs")
            if not isinstance(hrefs, list):
                return result("UNAVAILABLE", "DOM_UNREADABLE")
        except Exception:
            return result("UNAVAILABLE", "DOM_UNREADABLE")
        previous = len(found)
        if container:
            for href in hrefs:
                canonical = v1.retrieval_v2._canonical_fanatics_url(str(href))
                if canonical and canonical not in found:
                    found.append(canonical)
            if snapshot.get("empty_proven") is True:
                if found:
                    return result("UNAVAILABLE", "CONTRADICTORY_CONTENT")
                if status is not None:
                    return result("EMPTY_PROVEN", "EXPLICIT_EMPTY_CONTENT", True)
        # Zero URLs never establish readiness or completeness. Keep polling the
        # explicit main-content state within the existing bounded scroll loop.
        stable = stable + 1 if container and found and len(found) == previous else 0
        if stable >= 2:
            # The live marketplace exposes ordinary numbered pagination. Only
            # its uniquely labeled, enabled Next button is used (pagination
            # may be a sibling of main, as on many public inventory pages);
            # facet "See More" controls and any blocked state are untouched.
            inventory = tuple(found)
            if inventory != last_advanced_inventory:
                try:
                    next_page = page.get_by_role('button', name='Go to next page', exact=True)
                    count = next_page.count()
                    pagination = f"NEXT_COUNT_{min(count, 9)}"
                    if (count == 1 and next_page.is_visible() and next_page.is_enabled()
                            and next_page.get_attribute('aria-disabled') != 'true'):
                        next_page.click(timeout=2000)
                        pagination = "NEXT_CLICKED"
                        last_advanced_inventory = inventory
                        stable = 0
                        page.wait_for_timeout(850)
                        continue
                    elif count == 1:
                        pagination = "NEXT_NOT_ACTIONABLE"
                except Exception as error:
                    pagination = "NEXT_INSPECTION_" + type(error).__name__[:40]
            else:
                pagination = "NO_NEW_RESULTS_AFTER_NEXT"
            # A stable viewport is not a provider inventory count or an end
            # cursor. Retain these results without declaring the sweep complete.
            return result("RESULTS", "RESULTS_STABLE_WITHOUT_PAGINATION_PROOF")
        if container and found:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(850)
    return result("RESULTS" if found else "UNAVAILABLE",
                  "OBSERVATION_LIMIT" if found else "CONTENT_UNPROVEN")


def scan_fanatics_native_inventory_v2(
    page: Any,
    _seeds: Sequence[Any],
    *,
    observed_at,
    max_detail_pages: int = 200,
    scroll_rounds: int = 20,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    """Broad Pokemon retrieval; exact TCGdex identity; no GCC identity prerequisite."""
    try:
        collection = _fanatics_pokemon_urls(page, scroll_rounds=scroll_rounds)
        urls, rounds = collection
    except Exception as error:
        return [], ScanStatus("fanatics", "ERROR", detail=type(error).__name__, complete=False)

    confirmed.install_global_external_market_stack()
    output: list[MarketplaceListing] = []
    rejects: Counter[str] = Counter()
    limit = max(1, int(max_detail_pages))
    for url in urls[:limit]:
        title = ""
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

        resolution = resolve_fanatics_native_identity_v2(
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
                "Fanatics broad Pokemon Buy Now ASK; bounded H1 partition -> exact TCGdex; "
                "GCC history not required; ASK is not SOLD"
            ),
        )
        output.append(listing_from_observation(observation, source_url=url, title=title))

    detail = (
        "broad Pokemon marketplace retrieval; bounded H1 partitions -> exact TCGdex; "
        f"GCC identity catalog not required; rejects={dict(rejects)}"
    )
    return output, ScanStatus(
        "fanatics",
        "UNAVAILABLE" if collection.state == "UNAVAILABLE" else "OK",
        pages=rounds,
        candidates=len(urls),
        exact=len(output),
        detail=f"{detail}; {collection.detail}",
        complete=collection.complete and len(urls) <= limit,
    )


def install_global_marketplace_fanatics_native_v2() -> None:
    """Upgrade PR #171's installer without creating a second marketplace wrapper."""
    v1.scan_fanatics_native_inventory = scan_fanatics_native_inventory_v2
    v1.install_global_fanatics_native_identity()
