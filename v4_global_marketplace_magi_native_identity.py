"""Magi-native exact identity discovery for the V4 Global marketplace lane.

Magi discovery stays one broad public read-only inventory query.  Identity no
longer depends on matching Japanese listing text against English GCC seed names:
a standard Magi single-card title must expose PSA 10, one full collector number
and an exact set code (or an intrinsic promo set code).  The coordinate is then
proved in TCGdex's Japanese projection and the identical immutable card ID is
read from a Latin TCGdex projection to build the commercial identity without
translation or fuzzy matching.

A Magi listing remains a FIXED_ASK.  Explicit SOLD/unavailable markers are
blocked before identity resolution.  Unknown buyer/logistics economics remain
unknown and therefore fail closed downstream.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_canonical_multimarket as multimarket
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_notify as marketplace
import v4_global_marketplace_scan as scan
import v4_global_retrieval_hardening as retrieval_v1
import v4_global_retrieval_hardening_v3 as retrieval_v3
import v4_tcgdex_generalized_coordinate_recovery as generalized
from v4_global_market_core import CommercialIdentity
from v4_global_marketplace_discovery import MarketplaceListing, listing_from_observation
from v4_global_marketplace_scan import ScanStatus
from v4_market_magi_bridge import magi_fixed_ask_to_observation


_MAX_TCGDEX_JA_REQUESTS = 40
_MAX_TCGDEX_ALIAS_REQUESTS = 20
_LATIN_ALIAS_LANGUAGES = ("en", "id")
_SET_ID_RE = re.compile(r"^(?:[A-Za-z]{1,6}\d+[A-Za-z0-9.-]*|[A-Za-z]{1,6}-P)$", re.I)
_EXPLICIT_ENGLISH_RE = re.compile(r"\b(?:ENGLISH|ENG)\b|英語(?:版)?", re.I)
_SENSITIVE_RE = re.compile(
    r"\b(?:1ST\s+EDITION|FIRST\s+EDITION|SHADOWLESS|MASTER\s*BALL|"
    r"POK[EÉ]\s*BALL|REVERSE\s+HOLO|REVERSE|STAMPED?)\b|"
    r"初版|マスターボール|モンスターボール|エラー|誤植|加工ミス",
    re.I,
)


@dataclass(frozen=True)
class MagiNativeResolution:
    status: str
    reason: str
    identity: Optional[CommercialIdentity] = None
    card_id: str = ""
    set_id: str = ""


class _AliasBudget:
    def __init__(
        self,
        json_get: Callable[..., tuple[int, object, Mapping[str, str]]],
        *,
        max_requests: int,
    ) -> None:
        self.json_get = json_get
        self.max_requests = max(1, int(max_requests))
        self.requests_used = 0

    def get(self, url: str, **kwargs):
        if self.requests_used >= self.max_requests:
            return 0, {"error": "budget_exhausted"}, {}
        self.requests_used += 1
        return self.json_get(url, **kwargs)


def _full_number_from_title(title: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(title or "")).upper()
    tokens = {
        japan.number(match.group(0))
        for match in japan.CARD_RE.finditer(normalized)
        if japan.number(match.group(0))
    }
    if not tokens:
        return "", "collector_number_unproven"
    if len(tokens) != 1:
        return "", "collector_number_ambiguous"
    return next(iter(tokens)), "full_collector_number_exact"


def _set_code_from_title(title: str, full_number: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(title or ""))
    codes = {
        match.group(1).strip()
        for match in retrieval_v3.MAGI_SET_CODE_RE.finditer(normalized)
        if match.group(1).strip()
    }
    if len(codes) > 1:
        return "", "set_code_ambiguous"
    if len(codes) == 1:
        return next(iter(codes)), "explicit_set_code"

    if "/" in full_number:
        denominator = full_number.split("/", 1)[1]
        if not denominator.isdigit() and _SET_ID_RE.fullmatch(denominator):
            return denominator, "intrinsic_promo_set_code"
    return "", "set_code_unproven"


def _preflight(ask: japan.Ask) -> tuple[str, str, str]:
    title = japan.current_text(ask.title)
    if japan.has_any(title, japan.AUCTION):
        return "", "", "ongoing_auction"
    if japan.has_any(title, japan.MULTI):
        return "", "", "multi_item_listing"
    if not retrieval_v3.SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return "", "", "single_quantity_unproven"
    if not retrieval_v3.PSA10_RE.search(unicodedata.normalize("NFKC", title)):
        return "", "", "psa10_unproven"
    if _EXPLICIT_ENGLISH_RE.search(title):
        return "", "", "explicit_non_japanese_language"
    if _SENSITIVE_RE.search(title):
        return "", "", "sensitive_variant_unproven"

    full_number, number_reason = _full_number_from_title(title)
    if not full_number:
        return "", "", number_reason
    set_code, set_reason = _set_code_from_title(title, full_number)
    if not set_code:
        return "", "", set_reason
    return full_number, set_code, "magi_native_coordinate_parsed"


def _same_set(left: object, right: object) -> bool:
    return bool(str(left or "").strip()) and str(left or "").strip().casefold() == str(right or "").strip().casefold()


def _proof_for_coordinate(
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    *,
    full_number: str,
    set_code: str,
    cache: dict[tuple[str, str], retrieval_v3.JapaneseCatalogProof],
) -> retrieval_v3.JapaneseCatalogProof:
    key = (set_code.casefold(), full_number.upper())
    if key in cache:
        return cache[key]
    synthetic = japan.Identity(
        name="",
        set_name=set_code,
        number=full_number,
        language="Japanese",
        grader="PSA",
        grade="10",
        year=2000,
    )
    proof = resolver.resolve(synthetic, title=f"[{set_code}/MAGI_NATIVE]")
    cache[key] = proof
    return proof


def _alias_coordinate_ok(
    card: Mapping[str, Any],
    proof: retrieval_v3.JapaneseCatalogProof,
) -> bool:
    card_id = str(card.get("id") or "").strip()
    local_id = str(card.get("localId") or "").strip()
    set_payload = card.get("set")
    if not isinstance(set_payload, Mapping):
        return False
    set_id = str(set_payload.get("id") or "").strip()
    return bool(
        card_id
        and card_id == proof.card_id
        and _same_set(set_id, proof.set_id)
        and generalized._same_local_id(local_id, proof.local_id)
    )


def _fetch_latin_alias_same_card(
    proof: retrieval_v3.JapaneseCatalogProof,
    *,
    json_get: Callable[..., tuple[int, object, Mapping[str, str]]],
) -> tuple[Optional[Mapping[str, Any]], str]:
    if not proof.card_id or not proof.set_id or not proof.local_id:
        return None, "tcgdex_alias_coordinate_unproven"
    errors: list[str] = []
    for language in _LATIN_ALIAS_LANGUAGES:
        try:
            status, payload, _ = json_get(
                f"{multimarket.TCGDEX_BASE_URL}/{language}/cards/{quote(proof.card_id, safe='')}",
                timeout=multimarket.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as error:
            return None, f"tcgdex_alias_{type(error).__name__.casefold()}"
        if status == 0:
            return None, "tcgdex_alias_budget_exhausted"
        if status == 404:
            continue
        if status != 200:
            if generalized._transient_status(status):
                return None, f"tcgdex_alias_transient_http_{status}"
            errors.append(f"tcgdex_alias_http_{status}")
            continue
        card = multimarket._extract_single_payload(payload)
        if not isinstance(card, Mapping):
            errors.append("tcgdex_alias_invalid_payload")
            continue
        if not _alias_coordinate_ok(card, proof):
            return None, "tcgdex_alias_coordinate_conflict"
        name = str(card.get("name") or "").strip()
        set_payload = card.get("set")
        set_name = str(set_payload.get("name") or "").strip() if isinstance(set_payload, Mapping) else ""
        candidate = CommercialIdentity(
            name=name,
            set_name=set_name,
            number="1/1",
            language="ja",
            grader="PSA",
            grade="10",
        )
        if candidate.complete_for_exact_market:
            return card, f"tcgdex_same_card_{language}_projection"
        errors.append("tcgdex_alias_non_latin_identity")
    return None, errors[0] if errors else "tcgdex_alias_not_found"


def _identity_from_alias(
    alias_card: Mapping[str, Any],
    *,
    full_number: str,
) -> Optional[CommercialIdentity]:
    set_payload = alias_card.get("set")
    if not isinstance(set_payload, Mapping):
        return None
    identity = CommercialIdentity(
        name=str(alias_card.get("name") or "").strip(),
        set_name=str(set_payload.get("name") or "").strip(),
        number=full_number,
        language="ja",
        grader="PSA",
        grade="10",
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None
    return identity


def resolve_magi_native_identity(
    ask: japan.Ask,
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    alias_json_get: Callable[..., tuple[int, object, Mapping[str, str]]],
    proof_cache: Optional[dict[tuple[str, str], retrieval_v3.JapaneseCatalogProof]] = None,
    alias_cache: Optional[dict[str, tuple[Optional[Mapping[str, Any]], str]]] = None,
) -> MagiNativeResolution:
    full_number, set_code, reason = _preflight(ask)
    if not full_number or not set_code:
        return MagiNativeResolution("NO_MATCH", reason)

    proof_cache = proof_cache if proof_cache is not None else {}
    alias_cache = alias_cache if alias_cache is not None else {}
    proof = _proof_for_coordinate(
        resolver,
        full_number=full_number,
        set_code=set_code,
        cache=proof_cache,
    )
    if proof.status != "EXACT":
        status = "ERROR" if proof.status in {"ERROR", "BUDGET"} else "NO_MATCH"
        return MagiNativeResolution(status, f"target_catalog_unproven:{proof.reason or proof.status}")
    if not _same_set(proof.set_id, set_code):
        return MagiNativeResolution("AMBIGUOUS", "tcgdex_set_code_conflict", card_id=proof.card_id, set_id=proof.set_id)

    local, denominator = full_number.split("/", 1)
    if not generalized._same_local_id(proof.local_id, local):
        return MagiNativeResolution("AMBIGUOUS", "tcgdex_local_id_conflict", card_id=proof.card_id, set_id=proof.set_id)
    if denominator.isdigit():
        try:
            denominator_ok = bool(proof.official_count) and int(proof.official_count) == int(denominator)
        except (TypeError, ValueError):
            denominator_ok = False
        if not denominator_ok:
            return MagiNativeResolution("AMBIGUOUS", "tcgdex_denominator_conflict", card_id=proof.card_id, set_id=proof.set_id)
    elif not _same_set(denominator, proof.set_id):
        return MagiNativeResolution("AMBIGUOUS", "tcgdex_promo_set_code_conflict", card_id=proof.card_id, set_id=proof.set_id)

    current = japan.current_text("\n".join(value for value in (ask.title, ask.text) if value))
    if not proof.name_ja or not magi_hardening._jp_contains(current, proof.name_ja):
        return MagiNativeResolution("NO_MATCH", "target_japanese_card_name_unproven", card_id=proof.card_id, set_id=proof.set_id)
    # Numeric-set cards must expose the exact Japanese set name as an independent
    # provider-text check. Promo numbers such as 020/M-P already carry their set
    # code intrinsically in the printed number.
    if denominator.isdigit() and (
        not proof.set_name_ja or not magi_hardening._jp_contains(current, proof.set_name_ja)
    ):
        return MagiNativeResolution("NO_MATCH", "target_japanese_set_unproven", card_id=proof.card_id, set_id=proof.set_id)

    if proof.card_id in alias_cache:
        alias_card, alias_reason = alias_cache[proof.card_id]
    else:
        alias_card, alias_reason = _fetch_latin_alias_same_card(proof, json_get=alias_json_get)
        alias_cache[proof.card_id] = (alias_card, alias_reason)
    if alias_card is None:
        status = "ERROR" if "budget" in alias_reason or "transient" in alias_reason else "NO_MATCH"
        return MagiNativeResolution(status, alias_reason, card_id=proof.card_id, set_id=proof.set_id)

    identity = _identity_from_alias(alias_card, full_number=full_number)
    if identity is None:
        return MagiNativeResolution("NO_MATCH", "commercial_identity_incomplete", card_id=proof.card_id, set_id=proof.set_id)
    return MagiNativeResolution(
        "EXACT",
        f"MAGI_NATIVE_TCGDEX_JA_SET_EXACT+{alias_reason}",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def scan_magi_native_inventory(
    page: Any,
    _seeds: Sequence[Any],
    *,
    observed_at,
    max_detail_pages: int = 200,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    """One broad Magi inventory scan with catalog-native exact identity proof."""
    try:
        asks = scan._magi_broad_rows(page)
    except Exception as error:
        return [], ScanStatus("magi", "ERROR", detail=type(error).__name__, complete=False)

    output: list[MarketplaceListing] = []
    rejects: Counter[str] = Counter()
    limit = max(1, int(max_detail_pages))
    resolver = retrieval_v3.TCGdexJapaneseProofResolver(max_requests=_MAX_TCGDEX_JA_REQUESTS)
    alias_budget = _AliasBudget(multimarket._json_get, max_requests=_MAX_TCGDEX_ALIAS_REQUESTS)
    proof_cache: dict[tuple[str, str], retrieval_v3.JapaneseCatalogProof] = {}
    alias_cache: dict[str, tuple[Optional[Mapping[str, Any]], str]] = {}
    try:
        for ask in asks[:limit]:
            try:
                detailed = retrieval_v1.magi_detail_only(page, ask)
            except Exception:
                rejects["detail_error"] += 1
                continue

            available, availability_reason = magi_hardening.magi_listing_availability_check(page, detailed)
            if not available:
                rejects[availability_reason] += 1
                continue

            resolution = resolve_magi_native_identity(
                detailed,
                resolver=resolver,
                alias_json_get=alias_budget.get,
                proof_cache=proof_cache,
                alias_cache=alias_cache,
            )
            if resolution.status != "EXACT" or resolution.identity is None:
                rejects[resolution.reason or resolution.status or "identity_unproven"] += 1
                continue

            observation = magi_fixed_ask_to_observation(
                identity=resolution.identity,
                price_jpy=detailed.price_jpy,
                observed_at=observed_at,
                source_id=detailed.url,
                identity_proven=True,
                buyer_fee_rate=None,
                note=(
                    f"magi marketplace-first FIXED ASK; {resolution.reason}; "
                    "public broad retrieval; GCC history is not an identity prerequisite; "
                    "buyer/logistics all-in unproven; ASK is not SOLD"
                ),
            )
            output.append(
                listing_from_observation(
                    observation,
                    source_url=detailed.url,
                    title=detailed.title,
                )
            )
    finally:
        resolver.close()

    return output, ScanStatus(
        "magi",
        "OK",
        pages=1,
        candidates=len(asks),
        exact=len(output),
        detail=(
            "broad Pokemon PSA10 inventory query; Magi native full-number+set-code -> "
            "exact Japanese TCGdex -> same immutable card Latin projection; no per-card searches; "
            f"GCC identity catalog not required; tcgdex_ja_requests={resolver.requests_used}; "
            f"tcgdex_alias_requests={alias_budget.requests_used}; rejects={dict(rejects)}"
        ),
        complete=len(asks) <= limit,
    )


_INSTALLED = False
_ORIGINAL_SCAN = None


def _scan_with_catalog_independent_magi(args, *, observed_at):
    listings, statuses, gcc_fair, catalog_status = _ORIGINAL_SCAN(args, observed_at=observed_at)
    if getattr(args, "no_browser_sources", False):
        return listings, statuses, gcc_fair, catalog_status

    magi_status = next((row for row in statuses if row.market == "magi"), None)
    if magi_status is None or magi_status.status != "SKIPPED":
        return listings, statuses, gcc_fair, catalog_status
    if "identity catalog unavailable" not in str(magi_status.detail or ""):
        return listings, statuses, gcc_fair, catalog_status

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()
            magi_rows, native_status = scan_magi_native_inventory(
                page,
                (),
                observed_at=observed_at,
                max_detail_pages=max(1, int(args.browser_detail_cap)),
            )
            context.close()
            browser.close()
    except Exception as error:
        native_status = ScanStatus("magi", "ERROR", detail=type(error).__name__, complete=False)
        magi_rows = []

    merged = {listing.stable_key: listing for listing in listings}
    for listing in magi_rows:
        merged[listing.stable_key] = listing
    statuses = [row for row in statuses if row.market != "magi"] + [native_status]
    return list(merged.values()), statuses, gcc_fair, catalog_status


def install_global_marketplace_magi_native_identity() -> None:
    """Install Magi-native identity after Fanatics and before Cardova wrappers."""
    global _INSTALLED, _ORIGINAL_SCAN
    if _INSTALLED:
        return
    _ORIGINAL_SCAN = marketplace._scan
    # marketplace._scan imported this symbol directly, so update both module
    # bindings.  The generic scanner stays available as provenance/tests.
    scan.scan_magi_inventory = scan_magi_native_inventory
    marketplace.scan_magi_inventory = scan_magi_native_inventory
    marketplace._scan = _scan_with_catalog_independent_magi
    _INSTALLED = True
