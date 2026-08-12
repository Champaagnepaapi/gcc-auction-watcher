from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping, Optional
from urllib.parse import quote

import requests

import watcher


TCGDEX_BASE_URL = "https://api.tcgdex.net/v2"
POKETRACE_BASE_URL = "https://api.poketrace.com/v1"

TCGDEX_ENABLED = os.getenv("V4_TCGDEX_ENABLED", "true").strip().lower() == "true"
TCGDEX_TIMEOUT_SECONDS = float(os.getenv("V4_TCGDEX_REQUEST_TIMEOUT", "6"))
TCGDEX_CACHE_TTL_HOURS = max(
    1, int(os.getenv("V4_TCGDEX_CACHE_TTL_HOURS", "24"))
)
POKETRACE_ENABLED = (
    os.getenv("V4_POKETRACE_ENABLED", "true").strip().lower() == "true"
)
POKETRACE_API_KEY = os.getenv("POKETRACE_API_KEY", "").strip()
POKETRACE_TIMEOUT_SECONDS = float(
    os.getenv("V4_POKETRACE_REQUEST_TIMEOUT", "8")
)
POKETRACE_MAX_REQUESTS_PER_RUN = max(
    0, int(os.getenv("V4_POKETRACE_MAX_REQUESTS_PER_RUN", "40"))
)
POKETRACE_PACING_SECONDS = max(
    0.0, float(os.getenv("V4_POKETRACE_PACING_SECONDS", "0.40"))
)
POKETRACE_MIN_SALES = max(
    2, int(os.getenv("V4_POKETRACE_MIN_SALES", "3"))
)
RAW_REVIEW_TTL_HOURS = max(
    1, int(os.getenv("V4_RAW_REVIEW_TTL_HOURS", "24"))
)
MULTIMARKET_EXTERNAL_CACHE_SCHEMA_VERSION = 3
CANONICAL_CACHE_STATE_KEY = "v4_canonical_market_cache"
CANONICAL_CACHE_SCHEMA_VERSION = 1
MANUAL_REVIEW_STATE_KEY = "v4_graded_market_pending"
MANUAL_REVIEW_SCHEMA_VERSION = 1

PSA_PRODUCTION_GRADES = frozenset({8.0, 8.5, 9.0, 10.0})

_LANGUAGE_CODES = {
    "english": "en",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "german": "de",
    "allemand": "de",
    "spanish": "es",
    "espagnol": "es",
    "italian": "it",
    "italien": "it",
    "portuguese": "pt",
    "portugais": "pt",
    "japanese": "ja",
    "japonais": "ja",
    "korean": "ko",
    "coreen": "ko",
    "coréen": "ko",
    "dutch": "nl",
    "polish": "pl",
    "russian": "ru",
    "indonesian": "id",
    "thai": "th",
    "chinese": "zh-tw",
}


@dataclass(frozen=True)
class CanonicalCard:
    status: str
    card_id: str = ""
    set_id: str = ""
    set_name: str = ""
    local_id: str = ""
    full_number: str = ""
    name: str = ""
    language_code: str = ""
    pricing: Mapping[str, Any] = field(default_factory=dict)
    variants: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    unique_name_number: bool = False


@dataclass(frozen=True)
class RawMarketSignal:
    low: float
    central: float
    high: float
    currency: str
    sources: tuple[str, ...]
    variant: str
    note: str


@dataclass
class MultiMarketDiagnostics:
    tcgdex_attempted: int = 0
    tcgdex_exact: int = 0
    tcgdex_no_match: int = 0
    tcgdex_ambiguous: int = 0
    tcgdex_error: int = 0
    raw_signal_found: int = 0
    raw_signal_variant_ambiguous: int = 0
    poketrace_attempted: int = 0
    poketrace_exact: int = 0
    poketrace_no_match: int = 0
    poketrace_ambiguous: int = 0
    poketrace_strong: int = 0
    poketrace_weak: int = 0
    poketrace_error: int = 0
    poketrace_rate_limited: int = 0
    poketrace_budget_pending: int = 0
    fallback_apr_ebay: int = 0
    manual_raw_leads: int = 0
    manual_raw_notified: int = 0
    manual_raw_deduped: int = 0
    psa_below_8_excluded: int = 0
    psa_unsupported_grade_excluded: int = 0


@dataclass
class RequestBudget:
    poketrace_requests: int = 0
    last_poketrace_started: Optional[float] = None
    auth_checked: bool = False
    auth_ok: bool = False
    auth_note: str = ""


@dataclass(frozen=True)
class ManualReviewLead:
    identity_key: str
    lot: watcher.Lot
    canonical: CanonicalCard
    raw: RawMarketSignal
    gap_pct: float
    graded_note: str


_ORIGINAL_INSPECT_ITEM = watcher.inspect_item
_ORIGINAL_IS_VALID_POKEMON_CARD = watcher.is_valid_pokemon_card
_ORIGINAL_PROCESS_EXTERNAL = watcher.process_external_market_candidates
_ORIGINAL_FORMAT_RUN_DIAGNOSTICS = watcher.format_run_diagnostics

_SESSION = requests.Session()
_DIAGNOSTICS = MultiMarketDiagnostics()


def _normalize(value: object) -> str:
    plain = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.casefold()).strip()


def _normalize_number(value: object) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    raw = raw.lstrip("#")
    return raw


def _number_parts(value: object) -> tuple[str, str]:
    raw = _normalize_number(value)
    if "/" not in raw:
        return raw, ""
    left, right = raw.split("/", 1)
    return left, right


def _canonical_number_parts(value: object) -> tuple[str, str]:
    left, right = _number_parts(value)

    def normalize_part(part: str) -> str:
        if part.isdigit():
            return str(int(part))
        return part

    return normalize_part(left), normalize_part(right)


def _same_card_number(first: object, second: object) -> bool:
    first_left, first_right = _canonical_number_parts(first)
    second_left, second_right = _canonical_number_parts(second)
    if not first_left or not second_left or first_left != second_left:
        return False
    if first_right and second_right:
        return first_right == second_right
    return True


def _language_code(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    value = _normalize(lot.language or identity.get("language") or "")
    return _LANGUAGE_CODES.get(value, "")


def _json_get(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float,
) -> tuple[int, object, Mapping[str, str]]:
    response = _SESSION.get(url, params=params, headers=headers, timeout=timeout)
    status = int(getattr(response, "status_code", 0) or 0)
    response_headers = getattr(response, "headers", {})
    try:
        payload = response.json()
    except Exception:
        payload = {}
    return status, payload, response_headers


def _extract_list_payload(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("items", "cards", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    for key in ("items", "cards", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _extract_single_payload(payload: object) -> Optional[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Mapping):
            return data
        if payload.get("id"):
            return payload
    return None


def _denominator_matches(card: Mapping[str, Any], denominator: str) -> bool:
    if not denominator:
        return True
    set_payload = card.get("set")
    if not isinstance(set_payload, Mapping):
        return False
    counts = set_payload.get("cardCount")
    if not isinstance(counts, Mapping):
        return False
    observed = {
        str(value).strip()
        for value in (counts.get("official"), counts.get("total"))
        if value is not None
    }
    den_norm = str(int(denominator)) if denominator.isdigit() else denominator
    observed_norm = {
        str(int(val)) if val.isdigit() else val for val in observed
    }
    return denominator in observed or den_norm in observed_norm


def _validate_tcgdex_card(
    lot: watcher.Lot,
    card: Mapping[str, Any],
    *,
    language_code: str,
    unique_name_number: bool,
    reason: str,
) -> Optional[CanonicalCard]:
    identity = watcher.extract_card_identity(lot)
    target_name = _normalize(identity.get("core") or lot.title)
    candidate_name = _normalize(card.get("name"))
    if not target_name or candidate_name != target_name:
        return None

    reference = lot.card_number or identity.get("ref") or ""
    candidate_local_id = str(card.get("localId") or "").strip()
    if not _same_card_number(reference, candidate_local_id):
        return None

    _, denominator = _canonical_number_parts(reference)
    if denominator and not _denominator_matches(card, denominator):
        return None

    set_payload = card.get("set")
    if not isinstance(set_payload, Mapping):
        return None
    set_id = str(set_payload.get("id") or "").strip()
    set_name = str(set_payload.get("name") or "").strip()
    card_id = str(card.get("id") or "").strip()
    local_id = _normalize_number(card.get("localId"))
    if not all((card_id, set_id, set_name, local_id)):
        return None

    counts = set_payload.get("cardCount")
    official = ""
    if isinstance(counts, Mapping):
        value = counts.get("official")
        if value is not None:
            official = str(value).strip()
    full_number = f"{local_id}/{official}" if official else _normalize_number(reference)
    return CanonicalCard(
        status="EXACT",
        card_id=card_id,
        set_id=set_id,
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=str(card.get("name") or "").strip(),
        language_code=language_code,
        pricing=card.get("pricing") if isinstance(card.get("pricing"), Mapping) else {},
        variants=card.get("variants") if isinstance(card.get("variants"), Mapping) else {},
        reason=reason,
        unique_name_number=unique_name_number,
    )


def _fetch_tcgdex_card_detail(language_code: str, card_id: str) -> tuple[int, Optional[Mapping[str, Any]]]:
    status, payload, _ = _json_get(
        f"{TCGDEX_BASE_URL}/{language_code}/cards/{quote(card_id, safe='')}",
        timeout=TCGDEX_TIMEOUT_SECONDS,
    )
    if status != 200:
        return status, None
    return status, _extract_single_payload(payload)


_TCGDEX_MEMORY_CACHE: dict[tuple[str, str, str, str], CanonicalCard] = {}


def clear_tcgdex_cache() -> None:
    _TCGDEX_MEMORY_CACHE.clear()


def resolve_tcgdex_card(lot: watcher.Lot) -> CanonicalCard:
    global _DIAGNOSTICS
    if not TCGDEX_ENABLED:
        return CanonicalCard("DISABLED", reason="TCGdex désactivé")
    identity = watcher.extract_card_identity(lot)
    name = str(identity.get("core") or "").strip()
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    numerator, _ = _number_parts(reference)
    language_code = _language_code(lot)
    if not (name and numerator and language_code):
        return CanonicalCard(
            "NO_MATCH",
            reason="nom + numéro + langue insuffisants pour TCGdex exact",
        )

    norm_left, norm_right = _canonical_number_parts(reference)
    norm_num = f"{norm_left}/{norm_right}" if norm_right else norm_left
    listing_set = _normalize(lot.card_set or identity.get("series") or "")
    cache_key = (language_code, _normalize(name), norm_num, listing_set)
    if cache_key in _TCGDEX_MEMORY_CACHE:
        cached = _TCGDEX_MEMORY_CACHE[cache_key]
        if cached.status == "EXACT":
            _DIAGNOSTICS.tcgdex_exact += 1
        elif cached.status == "AMBIGUOUS":
            _DIAGNOSTICS.tcgdex_ambiguous += 1
        elif cached.status == "NO_MATCH":
            _DIAGNOSTICS.tcgdex_no_match += 1
        return cached

    _DIAGNOSTICS.tcgdex_attempted += 1

    num_queries = [numerator]
    if numerator.isdigit():
        unpadded = str(int(numerator))
        if unpadded != numerator and unpadded not in num_queries:
            num_queries.append(unpadded)
        for pad_len in (3, 2):
            padded = f"{int(numerator):0{pad_len}d}"
            if padded not in num_queries:
                num_queries.append(padded)

    briefs_by_id: dict[str, Mapping[str, Any]] = {}
    had_transient_error = False
    error_reason = ""

    try:
        # Primary proof: query ALL equivalent numeric representations
        for q_num in num_queries:
            status, payload, _ = _json_get(
                f"{TCGDEX_BASE_URL}/{language_code}/cards",
                params={"name": f"eq:{name}", "localId": f"eq:{q_num}"},
                timeout=TCGDEX_TIMEOUT_SECONDS,
            )
            if status == 200:
                found = _extract_list_payload(payload)
                for item in found:
                    if isinstance(item, Mapping):
                        b_id = str(item.get("id") or "").strip()
                        if b_id:
                            briefs_by_id[b_id] = item
                        else:
                            had_transient_error = True
                            error_reason = "malformed brief without id"
            else:
                had_transient_error = True
                error_reason = f"HTTP {status} on /cards (localId={q_num})"

        if had_transient_error:
            _DIAGNOSTICS.tcgdex_error += 1
            return CanonicalCard("ERROR", reason=f"TCGdex {error_reason}")

        unique_briefs = list(briefs_by_id.values())
        if unique_briefs:
            if len(unique_briefs) > 10:
                _DIAGNOSTICS.tcgdex_ambiguous += 1
                amb_res = CanonicalCard(
                    "AMBIGUOUS",
                    reason="plusieurs cartes TCGdex exactes pour nom + localId",
                )
                _TCGDEX_MEMORY_CACHE[cache_key] = amb_res
                return amb_res

            details: list[Mapping[str, Any]] = []
            detail_error = False
            for brief in unique_briefs:
                card_id = str(brief.get("id") or "").strip()
                if not card_id:
                    detail_error = True
                    had_transient_error = True
                    error_reason = "malformed brief id"
                    break
                det_status, detail = _fetch_tcgdex_card_detail(language_code, card_id)
                if det_status == 200 and detail is not None:
                    details.append(detail)
                else:
                    detail_error = True
                    had_transient_error = True
                    error_reason = f"HTTP {det_status} on detail {card_id}"
                    break

            if detail_error:
                _DIAGNOSTICS.tcgdex_error += 1
                return CanonicalCard("ERROR", reason=f"TCGdex {error_reason}")

            valid = [
                _validate_tcgdex_card(
                    lot,
                    detail,
                    language_code=language_code,
                    unique_name_number=len(unique_briefs) == 1,
                    reason="TCGDEX_EXACT_NAME_LOCALID",
                )
                for detail in details
            ]
            valid = [item for item in valid if item is not None]
            by_id = {item.card_id: item for item in valid}
            if len(by_id) == 1:
                result = next(iter(by_id.values()))
                _DIAGNOSTICS.tcgdex_exact += 1
                _TCGDEX_MEMORY_CACHE[cache_key] = result
                return result
            if len(by_id) > 1:
                # Exact listing set can safely disambiguate without fuzzy matching
                # since all candidate briefs were fully resolved.
                if listing_set:
                    matching = [
                        item
                        for item in by_id.values()
                        if _normalize(item.set_name) == listing_set
                    ]
                    if len(matching) == 1:
                        _DIAGNOSTICS.tcgdex_exact += 1
                        res = CanonicalCard(
                            **{
                                **matching[0].__dict__,
                                "reason": "TCGDEX_EXACT_NAME_LOCALID_SET",
                                "unique_name_number": False,
                            }
                        )
                        _TCGDEX_MEMORY_CACHE[cache_key] = res
                        return res
                _DIAGNOSTICS.tcgdex_ambiguous += 1
                amb_res = CanonicalCard(
                    "AMBIGUOUS",
                    reason="plusieurs cartes TCGdex exactes pour nom + localId",
                )
                _TCGDEX_MEMORY_CACHE[cache_key] = amb_res
                return amb_res

        # Secondary proof: exact localized set name + set/localId endpoint.
        raw_listing_set = str(lot.card_set or identity.get("series") or "").strip()
        if raw_listing_set and not unique_briefs and not had_transient_error:
            set_status, set_payload, _ = _json_get(
                f"{TCGDEX_BASE_URL}/{language_code}/sets",
                params={"name": f"eq:{raw_listing_set}"},
                timeout=TCGDEX_TIMEOUT_SECONDS,
            )
            if set_status == 200:
                sets = _extract_list_payload(set_payload)
                if len(sets) == 1:
                    set_id = str(sets[0].get("id") or "").strip()
                    if set_id:
                        for q_num in num_queries:
                            card_status, card_payload, _ = _json_get(
                                f"{TCGDEX_BASE_URL}/{language_code}/sets/"
                                f"{quote(set_id, safe='')}/{quote(q_num, safe='')}",
                                timeout=TCGDEX_TIMEOUT_SECONDS,
                            )
                            if card_status == 200:
                                detail = _extract_single_payload(card_payload)
                                if detail is not None:
                                    result = _validate_tcgdex_card(
                                        lot,
                                        detail,
                                        language_code=language_code,
                                        unique_name_number=False,
                                        reason="TCGDEX_EXACT_SET_LOCALID",
                                    )
                                    if result is not None:
                                        _DIAGNOSTICS.tcgdex_exact += 1
                                        _TCGDEX_MEMORY_CACHE[cache_key] = result
                                        return result
                                    break
                            elif card_status == 404:
                                continue
                            else:
                                had_transient_error = True
                                error_reason = f"HTTP {card_status}"
                elif len(sets) > 1:
                    _DIAGNOSTICS.tcgdex_ambiguous += 1
                    amb_res = CanonicalCard(
                        "AMBIGUOUS", reason="set TCGdex exact non unique"
                    )
                    _TCGDEX_MEMORY_CACHE[cache_key] = amb_res
                    return amb_res
            else:
                had_transient_error = True
                error_reason = f"HTTP {set_status} on /sets"
    except Exception as error:
        _DIAGNOSTICS.tcgdex_error += 1
        return CanonicalCard(
            "ERROR", reason=f"TCGdex {type(error).__name__}"
        )

    if had_transient_error:
        _DIAGNOSTICS.tcgdex_error += 1
        return CanonicalCard("ERROR", reason=f"TCGdex {error_reason}")

    _DIAGNOSTICS.tcgdex_no_match += 1
    no_match_res = CanonicalCard("NO_MATCH", reason="aucune identité TCGdex exacte")
    _TCGDEX_MEMORY_CACHE[cache_key] = no_match_res
    return no_match_res


def _attach_canonical_to_lot(lot: watcher.Lot, canonical: CanonicalCard) -> None:
    setattr(lot, "_canonical_card", canonical)
    setattr(lot, "tcgdex_status", canonical.status)
    setattr(lot, "tcgdex_resolution_reason", canonical.reason)
    if canonical.status != "EXACT":
        return
    # Keep rendered/listing identity untouched; enrich dedicated structured fields.
    lot.card_set = canonical.set_name
    if not lot.card_number:
        identity = watcher.extract_card_identity(lot)
        lot.card_number = str(identity.get("ref") or canonical.full_number).strip()
    lot.set_family = canonical.set_id
    lot.tcgdex_card_id = canonical.card_id
    lot.tcgdex_set_id = canonical.set_id
    lot.tcgdex_language = canonical.language_code
    lot.tcgdex_resolution_reason = canonical.reason
    lot.tcgdex_unique_name_number = canonical.unique_name_number
    lot.tcgdex_pricing = dict(canonical.pricing)
    lot.tcgdex_variants = dict(canonical.variants)


def canonical_inspect_item(page, lot: watcher.Lot, *, log_listing_errors: bool = True) -> watcher.Lot:
    inspected = _ORIGINAL_INSPECT_ITEM(
        page, lot, log_listing_errors=log_listing_errors
    )
    if inspected.inspection_error:
        return inspected
    # Do not spend catalog/provider work on PSA slabs outside the production
    # grade scope. The normal validity gate will account for the exclusion.
    if (inspected.grader or "").strip().upper() == "PSA":
        target = watcher._target_grade(inspected)
        if target not in PSA_PRODUCTION_GRADES:
            return inspected
    canonical = resolve_tcgdex_card(inspected)
    _attach_canonical_to_lot(inspected, canonical)
    return inspected


def psa_grade_in_production_scope(lot: watcher.Lot) -> bool:
    if (lot.grader or "").strip().upper() != "PSA":
        return True
    target = watcher._target_grade(lot)
    return target in PSA_PRODUCTION_GRADES


def scoped_is_valid_pokemon_card(
    lot: watcher.Lot, run_diagnostics: Optional[watcher.RunDiagnostics] = None
) -> bool:
    global _DIAGNOSTICS
    if not _ORIGINAL_IS_VALID_POKEMON_CARD(lot, run_diagnostics):
        return False
    if (lot.grader or "").strip().upper() != "PSA":
        return True
    grade = watcher._target_grade(lot)
    if grade in PSA_PRODUCTION_GRADES:
        return True
    if grade is not None and grade < 8:
        _DIAGNOSTICS.psa_below_8_excluded += 1
        watcher.log(
            f"Lot PSA hors scope production: PSA {grade:g} < 8 | {lot.title}"
        )
    else:
        _DIAGNOSTICS.psa_unsupported_grade_excluded += 1
        watcher.log(
            f"Lot PSA hors scope production: grade {lot.grade} non supporté | {lot.title}"
        )
    if run_diagnostics is not None:
        run_diagnostics.record_valuation(
            lot, watcher.REJECTION_OTHER, watcher.ACCOUNT_EXCLUDED_BY_RULES
        )
    return False


def _canonical_from_lot(lot: watcher.Lot) -> CanonicalCard:
    cached = getattr(lot, "_canonical_card", None)
    if isinstance(cached, CanonicalCard):
        return cached
    status = str(getattr(lot, "tcgdex_status", "") or "")
    if status and status != "EXACT":
        return CanonicalCard(
            status=status,
            reason=str(getattr(lot, "tcgdex_resolution_reason", "") or ""),
        )
    card_id = str(getattr(lot, "tcgdex_card_id", "") or "")
    set_id = str(getattr(lot, "tcgdex_set_id", "") or "")
    if not card_id or not set_id:
        canonical = resolve_tcgdex_card(lot)
        _attach_canonical_to_lot(lot, canonical)
        return canonical
    identity = watcher.extract_card_identity(lot)
    return CanonicalCard(
        status="EXACT",
        card_id=card_id,
        set_id=set_id,
        set_name=lot.card_set,
        local_id=_canonical_number_parts(lot.card_number or identity.get("ref"))[0],
        full_number=str(lot.card_number or identity.get("ref") or ""),
        name=str(identity.get("core") or lot.title),
        language_code=str(getattr(lot, "tcgdex_language", "") or ""),
        pricing=getattr(lot, "tcgdex_pricing", {}) or {},
        variants=getattr(lot, "tcgdex_variants", {}) or {},
        reason=str(getattr(lot, "tcgdex_resolution_reason", "") or ""),
        unique_name_number=bool(
            getattr(lot, "tcgdex_unique_name_number", False)
        ),
    )


def _finite_positive(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not (number > 0 and number < 1_000_000_000):
        return None
    return number


def _usd_per_eur() -> Optional[float]:
    try:
        value = watcher.get_psa_apr_usd_per_eur()
    except Exception:
        return None
    return _finite_positive(value)


def _to_eur(value: float, unit: str) -> Optional[float]:
    if unit.upper() == "EUR":
        return value
    if unit.upper() != "USD":
        return None
    rate = _usd_per_eur()
    if rate is None:
        return None
    return value / rate


def _raw_variant_choice(
    lot: watcher.Lot, canonical: CanonicalCard
) -> tuple[str, bool]:
    expected = watcher.expected_commercial_dimensions(lot)
    if any(
        expected.get(key) not in {None, ""}
        for key in ("printing", "special_finish", "variant", "shadow")
    ):
        return "", False
    edition = expected.get("edition", "")
    finish = expected.get("finish", "")
    variants = canonical.variants or {}

    if edition == "first_edition":
        if finish == "holo":
            return "1st-edition-holofoil", True
        if finish in {"non_holo", ""}:
            return "1st-edition", True
        return "", False
    if edition == "unlimited":
        if finish == "holo":
            return "unlimited-holofoil", True
        if finish in {"non_holo", ""}:
            return "unlimited", True
        return "", False

    if finish == "holo":
        return "holo", True
    if finish == "reverse":
        return "reverse", True
    if finish == "non_holo":
        return "normal", True

    available = [
        key
        for key, flag in (
            ("normal", variants.get("normal")),
            ("holo", variants.get("holo")),
            ("reverse", variants.get("reverse")),
        )
        if flag is True
    ]
    if len(available) == 1:
        return available[0], True
    return "", False


def _all_raw_centers(
    canonical: CanonicalCard,
) -> list[tuple[str, float, str]]:
    """Return conservative marketplace centers across every exposed RAW variant."""
    pricing = canonical.pricing
    centers: list[tuple[str, float, str]] = []
    cardmarket = pricing.get("cardmarket")
    if isinstance(cardmarket, Mapping):
        for suffix, label in (("", "normal"), ("-holo", "holo")):
            values = [
                _finite_positive(cardmarket.get(f"trend{suffix}")),
                _finite_positive(cardmarket.get(f"avg7{suffix}")),
                _finite_positive(cardmarket.get(f"avg30{suffix}")),
                _finite_positive(cardmarket.get(f"avg{suffix}")),
            ]
            values = [value for value in values if value is not None]
            if values:
                centers.append(("Cardmarket", median(values), label))

    tcgplayer = pricing.get("tcgplayer")
    if isinstance(tcgplayer, Mapping):
        unit = str(tcgplayer.get("unit") or "USD")
        for key, tier in tcgplayer.items():
            if key in {"unit", "updated"} or not isinstance(tier, Mapping):
                continue
            value = (
                _finite_positive(tier.get("marketPrice"))
                or _finite_positive(tier.get("midPrice"))
            )
            if value is None:
                continue
            converted = _to_eur(value, unit)
            if converted is not None:
                centers.append(("TCGplayer", converted, str(key)))
    return centers


def raw_market_signal(
    lot: watcher.Lot, canonical: CanonicalCard
) -> Optional[RawMarketSignal]:
    global _DIAGNOSTICS
    if canonical.status != "EXACT" or not canonical.pricing:
        return None
    variant, deterministic = _raw_variant_choice(lot, canonical)
    pricing = canonical.pricing
    centers: list[tuple[str, float]] = []

    if deterministic:
        cardmarket = pricing.get("cardmarket")
        if isinstance(cardmarket, Mapping):
            # Cardmarket has only normal vs holo fields; never use it as an
            # exact edition/reverse/special-printing proof.
            expected = watcher.expected_commercial_dimensions(lot)
            edition_sensitive = expected.get("edition") not in {None, ""}
            if not edition_sensitive and variant in {"normal", "holo"}:
                suffix = "-holo" if variant == "holo" else ""
                values = [
                    _finite_positive(cardmarket.get(f"trend{suffix}")),
                    _finite_positive(cardmarket.get(f"avg7{suffix}")),
                    _finite_positive(cardmarket.get(f"avg30{suffix}")),
                    _finite_positive(cardmarket.get(f"avg{suffix}")),
                ]
                values = [value for value in values if value is not None]
                if values:
                    centers.append(("Cardmarket", median(values)))

        tcgplayer = pricing.get("tcgplayer")
        if isinstance(tcgplayer, Mapping):
            key_patterns = {
                "normal": ("normal",),
                "holo": ("holo", "holofoil"),
                "reverse": ("reverse", "reverseholofoil", "reverseholo"),
                "1st-edition": ("1stedition", "firstedition", "1steditionnormal"),
                "1st-edition-holofoil": (
                    "1steditionholofoil",
                    "firsteditionholofoil",
                    "1steditionholo",
                ),
                "unlimited": ("unlimited", "unlimitednormal"),
                "unlimited-holofoil": ("unlimitedholofoil", "unlimitedholo"),
            }.get(variant, ())

            norm_tcgplayer = {
                re.sub(r"[^a-z0-9]", "", str(k).lower()): (k, v)
                for k, v in tcgplayer.items()
                if isinstance(v, Mapping)
            }
            for pat in key_patterns:
                matched = norm_tcgplayer.get(pat)
                if matched is not None:
                    _, tier = matched
                    value = (
                        _finite_positive(tier.get("marketPrice"))
                        or _finite_positive(tier.get("midPrice"))
                    )
                    if value is not None:
                        unit = str(tcgplayer.get("unit") or "USD")
                        converted = _to_eur(value, unit)
                        if converted is not None:
                            centers.append(("TCGplayer", converted))
                            break
    else:
        # Variant uncertainty must never become an automatic graded valuation.
        # For manual-review only, use the minimum across every exposed RAW
        # variant as the conservative floor. If a slab is still deeply below
        # that floor, it is worth human inspection without claiming its value.
        _DIAGNOSTICS.raw_signal_variant_ambiguous += 1
        centers = [
            (f"{source}:{raw_variant}", value)
            for source, value, raw_variant in _all_raw_centers(canonical)
        ]
        variant = "AMBIGUOUS_CONSERVATIVE_ENVELOPE"

    if not centers:
        return None
    values = [value for _, value in centers]
    central = median(values)
    low = min(values) * 0.90
    high = max(values) * 1.10
    signal = RawMarketSignal(
        low=max(0.01, low),
        central=central,
        high=max(central, high),
        currency="EUR",
        sources=tuple(source for source, _ in centers),
        variant=variant,
        note="; ".join(f"{source} {value:.2f} €" for source, value in centers),
    )
    _DIAGNOSTICS.raw_signal_found += 1
    return signal


def _poketrace_headers() -> Mapping[str, str]:
    return {"X-API-Key": POKETRACE_API_KEY}


def _paced_poketrace_get(
    budget: RequestBudget,
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> tuple[int, object, Mapping[str, str]]:
    if budget.poketrace_requests >= POKETRACE_MAX_REQUESTS_PER_RUN:
        return 0, {"_budget_pending": True}, {}
    if budget.last_poketrace_started is not None and POKETRACE_PACING_SECONDS > 0:
        elapsed = time.monotonic() - budget.last_poketrace_started
        if elapsed < POKETRACE_PACING_SECONDS:
            time.sleep(POKETRACE_PACING_SECONDS - elapsed)
    budget.last_poketrace_started = time.monotonic()
    budget.poketrace_requests += 1
    return _json_get(
        url,
        params=params,
        headers=_poketrace_headers(),
        timeout=POKETRACE_TIMEOUT_SECONDS,
    )


def _ensure_poketrace_auth(budget: RequestBudget) -> tuple[bool, str]:
    if budget.auth_checked:
        return budget.auth_ok, budget.auth_note
    budget.auth_checked = True
    try:
        status, payload, _headers = _paced_poketrace_get(
            budget, f"{POKETRACE_BASE_URL}/auth/info"
        )
    except Exception as error:
        budget.auth_note = f"auth {type(error).__name__}"
        return False, budget.auth_note
    if status != 200:
        budget.auth_note = f"auth HTTP {status}"
        return False, budget.auth_note
    data = _extract_single_payload(payload)
    user = data.get("user") if isinstance(data, Mapping) else None
    plan = (
        str(user.get("plan") or "").strip().upper()
        if isinstance(user, Mapping)
        else ""
    )
    active = bool(data.get("active", True)) if isinstance(data, Mapping) else False
    if active and plan in {"PRO", "GROWTH", "SCALE"}:
        budget.auth_ok = True
        budget.auth_note = plan
        return True, plan
    budget.auth_note = f"plan {plan or 'UNKNOWN'} / active={active}"
    return False, budget.auth_note


def _candidate_commercially_compatible(
    lot: watcher.Lot, candidate: Mapping[str, Any]
) -> bool:
    expected = watcher.expected_commercial_dimensions(lot)
    if any(value == "__conflict__" for value in expected.values()):
        return False
    raw_variant = str(candidate.get("variant") or "").replace("_", " ")
    canonical_variant = (
        raw_variant
        .replace("Holofoil", "Holo")
        .replace("holofoil", "holo")
    )
    if _normalize(raw_variant) == "normal":
        canonical_variant += " non holo"
    text = " ".join(
        (
            canonical_variant,
            str(candidate.get("rarity") or ""),
            str(candidate.get("name") or ""),
        )
    )
    observed = watcher._commercial_dimension_candidates(text)
    for dimension in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS:
        expected_value = expected.get(dimension)
        if not expected_value:
            continue
        values = observed.get(dimension, set())
        if expected_value not in values:
            return False
    return True


def _poketrace_language_market_is_exact(
    lot: watcher.Lot, candidate: Mapping[str, Any]
) -> bool:
    """Only accept a US graded tier as exact when language market is provable."""
    language = _normalize(
        lot.language or watcher.extract_card_identity(lot).get("language") or ""
    )
    game = str(candidate.get("game") or "").strip().casefold()
    if language == "english":
        return game in {"", "pokemon"}
    if language == "japanese":
        return game in {"pokemon-japanese", "pokemon_japanese", "japanese"}
    # PokeTrace US responses do not currently expose a reliable per-card
    # French/German/Spanish/Italian language field. Those markets remain useful
    # for retrieval/manual review, but never as exact automatic graded evidence.
    return False


def _candidate_exact_for_canonical(
    lot: watcher.Lot,
    canonical: CanonicalCard,
    candidate: Mapping[str, Any],
) -> bool:
    if str(candidate.get("productType") or "single").strip().casefold() != "single":
        return False
    if _normalize(candidate.get("name")) != _normalize(canonical.name):
        return False
    if not _same_card_number(candidate.get("cardNumber"), canonical.full_number):
        return False

    cand_local, cand_den = _canonical_number_parts(candidate.get("cardNumber"))
    canonical_local, canonical_den = _canonical_number_parts(canonical.full_number)
    if not cand_local or cand_local != canonical_local:
        return False
    if canonical_den and cand_den and cand_den != canonical_den:
        return False

    set_payload = candidate.get("set")
    provider_set = (
        str(set_payload.get("name") or "").strip()
        if isinstance(set_payload, Mapping)
        else ""
    )
    set_exact = bool(
        provider_set and _normalize(provider_set) == _normalize(canonical.set_name)
    )
    # A provider set-name mismatch can be accepted only when TCGdex proved this
    # exact name + full number globally unique in the listing language.
    unique_bridge = bool(
        canonical.unique_name_number
        and canonical_den
        and cand_den == canonical_den
    )
    if not (set_exact or unique_bridge):
        return False
    if not _poketrace_language_market_is_exact(lot, candidate):
        return False
    return _candidate_commercially_compatible(lot, candidate)


def _poketrace_grade_tier(lot: watcher.Lot) -> str:
    grader = (lot.grader or "").strip().upper()
    grade = watcher._target_grade(lot)
    if not grader or grade is None:
        return ""
    if float(grade).is_integer():
        grade_text = str(int(grade))
    else:
        grade_text = str(grade).replace(".", "_")
    return f"{grader}_{grade_text}"


def _dispersion_from_range(low: float, central: float, high: float) -> str:
    if central <= 0:
        return "élevée"
    spread = max(0.0, high - low) / central
    if spread <= 0.30:
        return "faible"
    if spread <= 0.60:
        return "moyenne"
    return "élevée"


def _poketrace_evidence(
    lot: watcher.Lot,
    canonical: CanonicalCard,
    budget: RequestBudget,
    now: datetime,
) -> watcher.ExternalMarketEvidence:
    global _DIAGNOSTICS
    key = watcher.external_commercial_identity_key(lot)
    if not (
        POKETRACE_ENABLED and POKETRACE_API_KEY and canonical.status == "EXACT"
    ):
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="PokeTrace non applicable",
            fetched_at=now,
        )
    if budget.poketrace_requests >= POKETRACE_MAX_REQUESTS_PER_RUN:
        _DIAGNOSTICS.poketrace_budget_pending += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_PENDING,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="budget PokeTrace du run épuisé",
            fetched_at=now,
        )

    auth_ok, auth_note = _ensure_poketrace_auth(budget)
    if not auth_ok:
        # Auth/plan failure must not suppress APR/eBay fallback.
        _DIAGNOSTICS.poketrace_error += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=f"PokeTrace graded indisponible: {auth_note}",
            fetched_at=now,
        )

    _DIAGNOSTICS.poketrace_attempted += 1
    search_text = " ".join(
        value for value in (canonical.name, canonical.full_number) if value
    )
    try:
        status, payload, headers = _paced_poketrace_get(
            budget,
            f"{POKETRACE_BASE_URL}/cards",
            params={
                "search": search_text,
                "market": "US",
                "limit": 20,
                "product_type": "single",
            },
        )
    except Exception as error:
        _DIAGNOSTICS.poketrace_error += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_PROVIDER_ERROR,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=f"PokeTrace {type(error).__name__}",
            fetched_at=now,
        )
    if isinstance(payload, Mapping) and payload.get("_budget_pending"):
        _DIAGNOSTICS.poketrace_budget_pending += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_PENDING,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="budget PokeTrace du run épuisé",
            fetched_at=now,
        )
    if status == 429:
        _DIAGNOSTICS.poketrace_rate_limited += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_RATE_LIMITED,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=f"PokeTrace 429 Retry-After={headers.get('Retry-After', '')}",
            fetched_at=now,
        )
    if status != 200:
        _DIAGNOSTICS.poketrace_error += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=f"PokeTrace HTTP {status}",
            fetched_at=now,
        )

    matches = [
        candidate
        for candidate in _extract_list_payload(payload)
        if _candidate_exact_for_canonical(lot, canonical, candidate)
    ]
    by_id = {
        str(candidate.get("id") or ""): candidate
        for candidate in matches
        if str(candidate.get("id") or "")
    }
    if len(by_id) > 1:
        _DIAGNOSTICS.poketrace_ambiguous += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_INSUFFICIENT,
            watcher.EVIDENCE_WEAK,
            "poketrace",
            note="plusieurs candidats PokeTrace exacts restent possibles",
            fetched_at=now,
        )
    if not by_id:
        _DIAGNOSTICS.poketrace_no_match += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="aucun candidat PokeTrace exact",
            fetched_at=now,
        )

    _DIAGNOSTICS.poketrace_exact += 1
    card = next(iter(by_id.values()))
    prices = card.get("prices")
    ebay_prices = prices.get("ebay") if isinstance(prices, Mapping) else None
    tier_name = _poketrace_grade_tier(lot)
    tier = ebay_prices.get(tier_name) if isinstance(ebay_prices, Mapping) else None
    if not isinstance(tier, Mapping) and isinstance(ebay_prices, Mapping):
        norm_tier_target = re.sub(r"[^a-zA-Z0-9]", "", tier_name).upper()
        for k, v in ebay_prices.items():
            if (
                isinstance(v, Mapping)
                and re.sub(r"[^a-zA-Z0-9]", "", str(k)).upper() == norm_tier_target
            ):
                tier = v
                break
    if not isinstance(tier, Mapping):
        _DIAGNOSTICS.poketrace_weak += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=f"PokeTrace exact mais tier {tier_name} absent",
            fetched_at=now,
        )

    avg = _finite_positive(tier.get("avg"))
    low = _finite_positive(tier.get("low"))
    high = _finite_positive(tier.get("high"))
    try:
        sale_count = max(0, int(tier.get("saleCount") or 0))
    except (TypeError, ValueError):
        sale_count = 0
    currency = str(card.get("currency") or "USD").upper()
    if avg is None:
        _DIAGNOSTICS.poketrace_weak += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_INSUFFICIENT,
            watcher.EVIDENCE_WEAK,
            "poketrace",
            note=f"PokeTrace {tier_name}: moyenne absente",
            fetched_at=now,
        )
    avg_eur = _to_eur(avg, currency)
    low_eur = _to_eur(low or avg, currency)
    high_eur = _to_eur(high or avg, currency)
    if None in {avg_eur, low_eur, high_eur}:
        _DIAGNOSTICS.poketrace_error += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note=f"PokeTrace {tier_name}: conversion {currency}/EUR indisponible",
            fetched_at=now,
        )
    low_eur = min(float(low_eur), float(avg_eur))
    high_eur = max(float(high_eur), float(avg_eur))
    dispersion = _dispersion_from_range(low_eur, float(avg_eur), high_eur)
    if sale_count < POKETRACE_MIN_SALES or dispersion == "élevée":
        _DIAGNOSTICS.poketrace_weak += 1
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_INSUFFICIENT,
            watcher.EVIDENCE_WEAK,
            "poketrace",
            note=(
                f"PokeTrace exact {tier_name}: {sale_count} vente(s), "
                f"dispersion {dispersion}"
            ),
            fetched_at=now,
        )

    liquidity = "élevée" if sale_count >= 5 else (
        "moyenne" if sale_count >= 3 else "faible"
    )
    threshold = watcher.adaptive_discount_threshold(
        sale_count,
        dispersion,
        liquidity,
        0,
        0,
        sale_count,
        True,
        False,
    )
    confidence = "moyenne" if sale_count >= 3 and dispersion != "élevée" else "faible"
    estimate = watcher.MarketEstimate(
        low=low_eur,
        central=float(avg_eur),
        high=high_eur,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity=liquidity,
        dispersion=dispersion,
        confidence=confidence,
        adaptive_discount_pct=threshold,
        rationale=(
            f"PokeTrace US eBay sold aggregate {tier_name}, "
            f"{sale_count} vente(s)"
        ),
        source_counts={"poketrace": sale_count},
        exact_grade_count=sale_count,
        same_grader_count=sale_count,
        source_consistent=True,
        grade_arbitrage=False,
    )
    _DIAGNOSTICS.poketrace_strong += 1
    return watcher.ExternalMarketEvidence(
        key,
        watcher.EXTERNAL_MATCHED,
        watcher.EVIDENCE_STRONG,
        "poketrace",
        estimate=estimate,
        note=(
            f"PokeTrace {card.get('id')} | {tier_name} | "
            f"eBay sold agrégé | {sale_count} vente(s) | {currency}"
        ),
        fetched_at=now,
    )


def _should_manual_review(
    lot: watcher.Lot, raw: Optional[RawMarketSignal]
) -> tuple[bool, float]:
    if raw is None or lot.current_price is None or raw.low <= 0:
        return False, 0.0
    gap = (raw.low - lot.current_price) / raw.low * 100
    return gap >= watcher.MIN_DISCOUNT, gap


def _manual_review_key(lot: watcher.Lot) -> str:
    return watcher.external_commercial_identity_key(lot)


def _manual_review_should_notify(
    state: dict, lead: ManualReviewLead, now: datetime
) -> bool:
    root = state.get(MANUAL_REVIEW_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != MANUAL_REVIEW_SCHEMA_VERSION:
        root = {"schema_version": MANUAL_REVIEW_SCHEMA_VERSION, "entries": {}}
        state[MANUAL_REVIEW_STATE_KEY] = root
    entries = root.setdefault("entries", {})
    if not isinstance(entries, dict):
        root["entries"] = {}
        entries = root["entries"]
    previous = entries.get(lead.identity_key)
    if isinstance(previous, Mapping):
        try:
            sent_at = datetime.fromisoformat(str(previous.get("sent_at") or ""))
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            sent_at = None
        try:
            previous_price = float(previous.get("price"))
        except (TypeError, ValueError):
            previous_price = None
        try:
            previous_gap = float(previous.get("gap_pct"))
        except (TypeError, ValueError):
            previous_gap = 0.0
        if sent_at is not None and now - sent_at < timedelta(hours=RAW_REVIEW_TTL_HOURS):
            price_improved = (
                previous_price is not None
                and previous_price > 0
                and lead.lot.current_price is not None
                and lead.lot.current_price <= previous_price * 0.90
            )
            gap_improved = lead.gap_pct >= previous_gap + 5
            if not (price_improved or gap_improved):
                return False
    entries[lead.identity_key] = {
        "sent_at": now.isoformat(),
        "price": lead.lot.current_price,
        "gap_pct": lead.gap_pct,
        "tcgdex_card_id": lead.canonical.card_id,
    }
    return True


def _notify_manual_review(lead: ManualReviewLead) -> None:
    title = "GCC MANUAL REVIEW — GRADED MARKET PENDING"
    grade = watcher.format_grade_label(lead.lot.grader, lead.lot.grade)
    message = (
        f"{title}\n\n"
        f"{lead.canonical.name} #{lead.canonical.full_number}\n"
        f"{lead.canonical.set_name} · TCGdex {lead.canonical.card_id}\n"
        f"{grade}\n\n"
        f"Prix GCC : {lead.lot.current_price:.2f} €\n"
        f"Marché RAW externe : {lead.raw.low:.2f}–{lead.raw.high:.2f} €\n"
        f"RAW central : {lead.raw.central:.2f} €\n"
        f"Sources RAW : {', '.join(lead.raw.sources)}\n"
        f"Écart prudent vs RAW : {lead.gap_pct:.1f}%\n"
        f"Marché gradé : {lead.graded_note or 'non confirmé'}\n\n"
        "RAW ≠ valeur du slab gradé. Aucun prix max conseillé n'est "
        "calculé depuis le RAW; revue manuelle uniquement.\n"
        f"{lead.lot.url}"
    )
    watcher.log("*** MANUAL REVIEW: graded market pending ***")
    print(message, flush=True)
    if watcher.NTFY_TOPIC:
        try:
            requests.post(
                f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "3",
                    "Tags": "mag,card_index",
                },
                timeout=10,
            ).raise_for_status()
        except Exception as error:
            watcher.log(
                f"Notification manual review échouée: {type(error).__name__}"
            )


def _fallback_external(
    page,
    candidate: watcher.ValuationCandidate,
    budgets: watcher.ValidationBudgets,
    external_diagnostics: watcher.ExternalMarketDiagnostics,
    now: datetime,
) -> watcher.ExternalMarketEvidence:
    global _DIAGNOSTICS
    _DIAGNOSTICS.fallback_apr_ebay += 1
    return watcher.fetch_external_market_evidence(
        page, candidate, budgets, external_diagnostics, now
    )


def _combine_retry_with_fallback(
    primary: watcher.ExternalMarketEvidence,
    fallback: watcher.ExternalMarketEvidence,
) -> watcher.ExternalMarketEvidence:
    if (
        fallback.status == watcher.EXTERNAL_MATCHED
        and fallback.strength == watcher.EVIDENCE_STRONG
        and fallback.estimate is not None
    ):
        return fallback
    if fallback.status in watcher.EXTERNAL_RETRY_STATUSES:
        return fallback
    if fallback.status == watcher.EXTERNAL_PENDING:
        return fallback
    if primary.status in watcher.EXTERNAL_RETRY_STATUSES:
        return watcher.replace(
            primary,
            note=(
                f"{primary.note}; fallback {fallback.source or 'external'} "
                f"{fallback.status}: {fallback.note}"
            ).strip("; "),
        )
    if primary.status == watcher.EXTERNAL_PENDING:
        return watcher.replace(
            primary,
            note=(
                f"{primary.note}; fallback {fallback.source or 'external'} "
                f"{fallback.status}: {fallback.note}"
            ).strip("; "),
        )
    return fallback


def multimarket_process_external_market_candidates(
    page,
    candidates: list[watcher.ValuationCandidate],
    state: dict,
    budgets: watcher.ValidationBudgets,
    run_diagnostics: watcher.RunDiagnostics,
    now: datetime,
    *,
    provider=None,
    ttl_hours: int = watcher.EXTERNAL_EVIDENCE_TTL_HOURS,
) -> list[watcher.Opportunity]:
    global _DIAGNOSTICS
    _DIAGNOSTICS = MultiMarketDiagnostics()
    clear_tcgdex_cache()

    # Invalidate only the old V4 external-cache schema once. The strict identity
    # key remains unchanged; new entries may contain PokeTrace evidence.
    watcher.EXTERNAL_CACHE_SCHEMA_VERSION = MULTIMARKET_EXTERNAL_CACHE_SCHEMA_VERSION

    request_budget = RequestBudget()
    leads: dict[str, ManualReviewLead] = {}

    def fetch(candidate, validation_budgets, fetch_now):
        if provider is not None:
            return provider(candidate, validation_budgets, fetch_now)

        canonical = _canonical_from_lot(candidate.lot)
        raw = raw_market_signal(candidate.lot, canonical)
        poketrace = _poketrace_evidence(
            candidate.lot, canonical, request_budget, fetch_now
        )
        if (
            poketrace.status == watcher.EXTERNAL_MATCHED
            and poketrace.strength == watcher.EVIDENCE_STRONG
        ):
            return poketrace

        if poketrace.status == watcher.EXTERNAL_PENDING:
            should_review, gap = _should_manual_review(candidate.lot, raw)
            if should_review and raw is not None:
                leads[_manual_review_key(candidate.lot)] = ManualReviewLead(
                    _manual_review_key(candidate.lot),
                    candidate.lot,
                    canonical,
                    raw,
                    gap,
                    poketrace.note,
                )
            return poketrace

        fallback = _fallback_external(
            page,
            candidate,
            validation_budgets,
            run_diagnostics.external_market,
            fetch_now,
        )
        combined = _combine_retry_with_fallback(poketrace, fallback)
        should_review, gap = _should_manual_review(candidate.lot, raw)
        if should_review and raw is not None and combined.strength != watcher.EVIDENCE_STRONG:
            leads[_manual_review_key(candidate.lot)] = ManualReviewLead(
                _manual_review_key(candidate.lot),
                candidate.lot,
                canonical,
                raw,
                gap,
                "; ".join(
                    value
                    for value in (poketrace.note, fallback.note)
                    if value
                ),
            )
        return combined

    opportunities = _ORIGINAL_PROCESS_EXTERNAL(
        page,
        candidates,
        state,
        budgets,
        run_diagnostics,
        now,
        provider=fetch,
        ttl_hours=ttl_hours,
    )
    opportunity_keys = {
        watcher.external_commercial_identity_key(op.lot)
        for op in opportunities
    }
    for key, lead in leads.items():
        if key in opportunity_keys:
            continue
        _DIAGNOSTICS.manual_raw_leads += 1
        if _manual_review_should_notify(state, lead, now):
            _notify_manual_review(lead)
            _DIAGNOSTICS.manual_raw_notified += 1
        else:
            _DIAGNOSTICS.manual_raw_deduped += 1

    watcher.log("=== CANONICAL MULTI-MARKET ===")
    watcher.log(
        "TCGdex: "
        f"attempted {_DIAGNOSTICS.tcgdex_attempted} | "
        f"exact {_DIAGNOSTICS.tcgdex_exact} | "
        f"no-match {_DIAGNOSTICS.tcgdex_no_match} | "
        f"ambiguous {_DIAGNOSTICS.tcgdex_ambiguous} | "
        f"errors {_DIAGNOSTICS.tcgdex_error}"
    )
    watcher.log(
        "RAW external: "
        f"signals {_DIAGNOSTICS.raw_signal_found} | "
        f"variant-ambiguous {_DIAGNOSTICS.raw_signal_variant_ambiguous}"
    )
    watcher.log(
        "PokeTrace: "
        f"attempted {_DIAGNOSTICS.poketrace_attempted} | "
        f"exact {_DIAGNOSTICS.poketrace_exact} | "
        f"strong {_DIAGNOSTICS.poketrace_strong} | "
        f"weak {_DIAGNOSTICS.poketrace_weak} | "
        f"no-match {_DIAGNOSTICS.poketrace_no_match} | "
        f"ambiguous {_DIAGNOSTICS.poketrace_ambiguous} | "
        f"errors {_DIAGNOSTICS.poketrace_error} | "
        f"429 {_DIAGNOSTICS.poketrace_rate_limited} | "
        f"budget-pending {_DIAGNOSTICS.poketrace_budget_pending}"
    )
    watcher.log(
        "Manual graded-market pending: "
        f"leads {_DIAGNOSTICS.manual_raw_leads} | "
        f"notified {_DIAGNOSTICS.manual_raw_notified} | "
        f"deduped {_DIAGNOSTICS.manual_raw_deduped}"
    )
    watcher.log(
        "PSA scope: "
        f"below-8 excluded {_DIAGNOSTICS.psa_below_8_excluded} | "
        f"unsupported excluded {_DIAGNOSTICS.psa_unsupported_grade_excluded}"
    )
    return opportunities


def install_canonical_multimarket_pipeline() -> None:
    """Install V4 production-only canonical identity and multi-market enrichment."""
    watcher.EXTERNAL_CACHE_SCHEMA_VERSION = MULTIMARKET_EXTERNAL_CACHE_SCHEMA_VERSION
    watcher.inspect_item = canonical_inspect_item
    watcher.is_valid_pokemon_card = scoped_is_valid_pokemon_card
    watcher.process_external_market_candidates = (
        multimarket_process_external_market_candidates
    )
