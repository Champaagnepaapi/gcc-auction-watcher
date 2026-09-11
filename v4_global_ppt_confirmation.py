"""Strict PokemonPriceTracker confirmation for the V4 Global Multi-Vault lane.

Read-only aggregate graded evidence only. A reviewed provider setId remains the
fast path, while unmapped Japanese sets may be recovered generically from an
exact TCGdex coordinate. Retrieval never substitutes for proof: the provider
row must resolve uniquely by TCGdex externalCatalogId, or by an exact
name+set+collector fallback only when externalCatalogId is absent.

PPT evidence is SOLD_AGGREGATED, never item-level SOLD. PPT and PokeTrace/eBay
remain one EBAY_GRADED_AGGREGATE correlation family.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Mapping, Optional, Sequence

import requests

from ecb_fx import ECBCurrencyConverter
import v4_canonical_multimarket as multimarket
from v4_global_market_core import CommercialIdentity, EBAY_GRADED_AGGREGATE

PPT_URL = "https://www.pokemonpricetracker.com/api/v2/cards"
PROVIDER = "PokemonPriceTracker"

# Live-proven by the bounded Japan Edge PPT diagnostic: Japanese Pokemon Card
# 151 is exposed as provider setId=23599. No other numeric setId is guessed.
REVIEWED_JP_SET_IDS = {
    "151": "23599",
    "pokemon card 151": "23599",
}

SENSITIVE_TERMS = (
    "master ball",
    "masterball",
    "poke ball",
    "pokeball",
    "reverse",
    "reverse holo",
    "1st edition",
    "first edition",
    "shadowless",
    "stamp",
    "stamped",
    "error",
    "incorrect texture",
)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _collector(value: object) -> str:
    raw = str(value or "").strip().lstrip("#").split("/", 1)[0]
    token = re.sub(r"[^A-Za-z0-9]+", "", raw).casefold()
    if token.isdigit():
        return str(int(token))
    match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
    return f"{match.group(1)}{int(match.group(2))}" if match else token


def _positive(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _header_int(headers: Mapping[str, object], name: str) -> Optional[int]:
    for key, value in headers.items():
        if str(key).casefold() != name.casefold():
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
    return None


def _rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, Mapping):
        return [data]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return [row for row in data if isinstance(row, Mapping)]
    return []


def _unique_rows(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    output: list[Mapping[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        fingerprint = tuple(
            str(row.get(key) or "")
            for key in (
                "externalCatalogId",
                "tcgPlayerId",
                "tcgplayerId",
                "setId",
                "set_id",
                "setName",
                "set_name",
                "cardNumber",
                "number",
                "name",
                "language",
                "printing",
                "variant",
            )
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        output.append(row)
    return output


def _grade_key(identity: CommercialIdentity) -> str:
    grader = _norm(identity.grader).replace(" ", "")
    try:
        value = float(str(identity.grade).strip())
        grade = str(int(value)) if value.is_integer() else f"{value:g}"
    except (TypeError, ValueError):
        grade = str(identity.grade or "").strip()
    return f"{grader}{grade.replace('.', '_')}"


def _sensitive_claims(identity: CommercialIdentity) -> tuple[str, ...]:
    blob = _norm(" ".join((identity.edition, identity.finish, identity.variant)))
    found: list[str] = []
    for raw in SENSITIVE_TERMS:
        claim = _norm(raw)
        if claim and claim in blob and claim not in found:
            found.append(claim)
    return tuple(found)


def _provider_blob(row: Mapping[str, object]) -> str:
    return _norm(
        " ".join(
            str(row.get(key) or "")
            for key in ("name", "printing", "variant", "rarity", "description")
        )
    )


def _language_compatible(row: Mapping[str, object]) -> bool:
    declared = row.get("language")
    return declared in (None, "") or _norm(declared) in {
        "ja",
        "jp",
        "japanese",
        "japonais",
        "japan",
    }


def _variant_compatible(identity: CommercialIdentity, row: Mapping[str, object]) -> bool:
    provider_blob = _provider_blob(row)
    return all(claim in provider_blob for claim in _sensitive_claims(identity))


def reviewed_set_id(identity: CommercialIdentity) -> Optional[str]:
    if _norm(identity.language) not in {"ja", "jp", "japanese", "japonais"}:
        return None
    return REVIEWED_JP_SET_IDS.get(_norm(identity.set_name))


def _match(identity, rows, set_id, *, canonical=None):
    """Reviewed set IDs narrow retrieval; the canonical gate remains mandatory."""
    status, row, _proof = _match_canonical(identity, canonical, rows, provider_set_id=set_id)
    return status, row


def _language_code(value):
    return {"jp": "ja", "japanese": "ja", "japonais": "ja", "english": "en", "anglais": "en"}.get(_norm(value), _norm(value))


def _identity_text_norm(value):
    # Keep Japanese names as evidence, rather than treating them as an absent
    # ASCII field. Reuse the already validated Global Unicode normalizer.
    from v4_global_marketplace_unicode_identity import _unicode_identity_norm
    return _unicode_identity_norm(value)


def _number_consistent(value, full_number):
    if _collector(value) != _collector(full_number):
        return False
    # Numerator-only provider fields may use an exact catalog/set coordinate,
    # but a printed conflicting denominator is never discarded.
    actual = str(value or "").partition("/")[2]
    expected = str(full_number or "").partition("/")[2]
    return not actual or _norm(actual) == _norm(expected)


def _canonical_variant_compatible(identity, canonical, row):
    from v4_global_economic_confirmation import _lot_for_identity
    from v4_global_provider_exact_bridge import _sensitive_dimensions_compatible
    from v4_multimarket_safety import _candidate_sensitive_dimensions
    candidate = {
        "name": row.get("name"), "rarity": row.get("rarity"),
        "variant": " ".join(str(row.get(k) or "") for k in ("variant", "printing", "finish", "edition")),
    }
    observed = _candidate_sensitive_dimensions(candidate)
    if any(len(values) != 1 for values in observed.values()):
        return False
    return _sensitive_dimensions_compatible(_lot_for_identity(identity), canonical, candidate)


def _deep_coordinate_consistent(row, requested_id):
    """A present contradictory detail identifier cannot supply the price."""
    return all(str(row[key]).strip() == str(requested_id).strip()
               for key in ("tcgPlayerId", "tcgplayerId") if row.get(key) not in (None, ""))


def _match_canonical(identity, canonical, rows, *, provider_set_id=""):
    """One strict macro/material gate for reviewed and dynamic PPT retrieval."""
    if canonical is None or canonical.status != "EXACT" or not canonical.card_id:
        return "TCGDEX_UNRESOLVED", None, ""
    language = _language_code(identity.language)
    if language not in {"ja", "en"} or _language_code(canonical.language_code) != language:
        return "TCGDEX_UNRESOLVED", None, ""
    if not _number_consistent(identity.number, canonical.full_number):
        return "TCGDEX_UNRESOLVED", None, ""
    names = {_identity_text_norm(identity.name), _identity_text_norm(canonical.name)} - {""}
    sets = {_identity_text_norm(identity.set_name), _identity_text_norm(canonical.set_name)} - {""}
    matches = []
    for row in _unique_rows(rows):
        if row.get("language") not in (None, "") and _language_code(row["language"]) != language:
            continue
        if not _number_consistent(row.get("cardNumber") or row.get("number"), canonical.full_number):
            continue
        row_name = _identity_text_norm(row.get("name"))
        catalog_id = _norm(row.get("externalCatalogId"))
        if (row_name and row_name not in names) or (not row_name and catalog_id != _norm(canonical.card_id)):
            continue
        row_set = _identity_text_norm(row.get("setName") or row.get("set_name"))
        if row_set and row_set not in sets:
            continue
        row_id = _norm(row.get("setId") or row.get("set_id"))
        if provider_set_id and row_id != _norm(provider_set_id):
            continue
        if catalog_id and catalog_id != _norm(canonical.card_id):
            continue
        if not catalog_id and not row_set and not provider_set_id:
            continue
        proof = "TCGDEX_EXTERNAL_CATALOG_ID" if catalog_id else "TCGDEX_SET_NAME_NUMBER_FALLBACK"
        matches.append((row, proof))
    if len(matches) > 1:
        return "AMBIGUOUS", None, matches[0][1]
    if not matches:
        return "CLEAN_NO_MATCH", None, "TCGDEX_COORDINATE_NOT_FOUND"
    row, proof = matches[0]
    if not _canonical_variant_compatible(identity, canonical, row):
        return "MICROVARIANT_UNPROVEN", None, proof
    return "EXACT", row, proof

@dataclass
class PptBudget:
    max_http_calls: int = 12
    max_credits: int = 60
    daily_remaining_floor: int = 15_000
    interval_seconds: float = 1.10
    http_calls: int = 0
    credits: int = 0
    daily_remaining: Optional[int] = None
    blocked_reason: str = ""
    _last_call: Optional[float] = None

    def can_call(self) -> bool:
        if self.blocked_reason:
            return False
        if self.http_calls >= self.max_http_calls:
            self.blocked_reason = "HTTP_CALL_CAP"
        elif self.credits >= self.max_credits:
            self.blocked_reason = "CREDIT_CAP"
        elif (
            self.daily_remaining is not None
            and self.daily_remaining <= self.daily_remaining_floor
        ):
            self.blocked_reason = "DAILY_REMAINING_SAFETY_FLOOR"
        return not self.blocked_reason

    def wait(self) -> None:
        if self._last_call is None or self.interval_seconds <= 0:
            return
        delay = self.interval_seconds - (time.monotonic() - self._last_call)
        if delay > 0:
            time.sleep(delay)

    def record(self, headers: Mapping[str, object]) -> None:
        self.http_calls += 1
        self._last_call = time.monotonic()
        consumed = _header_int(headers, "X-Api-Calls-Consumed")
        remaining = _header_int(headers, "X-Ratelimit-Daily-Remaining")
        if consumed is None:
            self.blocked_reason = "CREDIT_HEADER_REQUIRED"
            return
        if remaining is None:
            self.blocked_reason = "DAILY_REMAINING_HEADER_REQUIRED"
            return
        self.credits += consumed
        self.daily_remaining = remaining
        if self.credits > self.max_credits:
            self.blocked_reason = "CREDIT_CAP_EXCEEDED"
        elif remaining <= self.daily_remaining_floor:
            self.blocked_reason = "DAILY_REMAINING_SAFETY_FLOOR"


@dataclass(frozen=True)
class PptSnapshot:
    status: str
    fair_eur: Optional[float] = None
    sales_count: int = 0
    last_sale_at: Optional[datetime] = None
    evidence_class: str = "SOLD_AGGREGATED"
    correlation_group: str = EBAY_GRADED_AGGREGATE
    match_proof: str = ""
    note: str = ""
    provider_set_id: str = ""
    identity_resolution: str = ""


def _request(
    session: requests.Session,
    api_key: str,
    budget: PptBudget,
    params: Mapping[str, object],
    timeout: float,
):
    if not budget.can_call():
        return None, None
    budget.wait()
    try:
        response = session.get(
            PPT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            params=dict(params),
            timeout=timeout,
        )
    except requests.RequestException as error:
        budget.blocked_reason = f"REQUEST_ERROR:{type(error).__name__}"
        return None, None
    budget.record(getattr(response, "headers", {}) or {})
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return int(response.status_code), payload


def _parse_last_sale(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_from_deep_row(
    identity: CommercialIdentity,
    row: Mapping[str, object],
    *,
    fx: ECBCurrencyConverter,
    observed_at: datetime,
    provider_set_id: str,
    resolution: str,
) -> PptSnapshot:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    grades = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    bucket = grades.get(_grade_key(identity))
    if not isinstance(bucket, Mapping):
        return PptSnapshot(
            "CLEAN_NO_MATCH",
            note="exact grade bucket missing",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    try:
        count = max(0, int(bucket.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    smart = bucket.get("smartMarketPrice") if isinstance(bucket.get("smartMarketPrice"), Mapping) else {}
    centers = [
        value
        for value in (
            _positive(bucket.get("medianPrice")),
            _positive(smart.get("price")),
            _positive(bucket.get("averagePrice")),
        )
        if value is not None
    ]
    if count <= 0 or not centers:
        return PptSnapshot(
            "CLEAN_INSUFFICIENT",
            sales_count=count,
            note="aggregate center/count missing",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    fair_usd = float(median(centers))
    converted = fx.convert(Decimal(str(fair_usd)), "USD", "EUR", observed_at.date())
    if converted is None or converted <= 0:
        return PptSnapshot(
            "FX_UNAVAILABLE",
            sales_count=count,
            note="USD/EUR unavailable",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    return PptSnapshot(
        "MATCHED",
        fair_eur=round(float(converted), 2),
        sales_count=count,
        last_sale_at=_parse_last_sale(bucket.get("lastSaleDate")),
        match_proof=(
            "JP_QUERY_SCOPE_PROVIDER_SET_ID_NUMBER_AND_VARIANT"
            if resolution == "REVIEWED_SET_ID"
            else resolution
        ),
        note="PPT Japanese eBay graded aggregate; ASK/current auction never used",
        provider_set_id=provider_set_id,
        identity_resolution=resolution,
    )


def fetch_snapshot(
    identity: CommercialIdentity,
    *,
    api_key: str,
    budget: PptBudget,
    session: requests.Session,
    fx: ECBCurrencyConverter,
    timeout: float = 15.0,
    now: Optional[datetime] = None,
    canonical: Optional[multimarket.CanonicalCard] = None,
) -> PptSnapshot:
    observed_at = now or datetime.now(timezone.utc)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return PptSnapshot("BLOCKED_IDENTITY", note="incomplete/non-actionable identity")
    if _norm(identity.language) not in {"ja", "jp", "japanese", "japonais"}:
        return PptSnapshot("BLOCKED_LANGUAGE", note="PPT exact mapping currently Japanese only")
    if _norm(identity.grader) != "psa" or str(identity.grade).strip() not in {"10", "10.0"}:
        return PptSnapshot("BLOCKED_GRADE", note="reviewed PPT mapping requires PSA 10")
    if not api_key:
        return PptSnapshot("PROVIDER_DISABLED", note="PPT key unavailable")

    if canonical is None or canonical.status != "EXACT":
        return PptSnapshot("TCGDEX_UNRESOLVED", note="exact canonical required before PPT; no network")

    reviewed = reviewed_set_id(identity)
    matched: Optional[Mapping[str, object]] = None
    provider_set_id = reviewed or ""
    resolution = "REVIEWED_SET_ID" if reviewed else ""

    if reviewed:
        status, payload = _request(
            session,
            api_key,
            budget,
            {
                "language": "japanese",
                "setId": reviewed,
                "search": _collector(identity.number),
                "limit": 5,
            },
            timeout,
        )
        if status is None:
            return PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
            return PptSnapshot("RATE_LIMIT", note="HTTP 429")
        if status != 200:
            return PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}")
        match_status, row = _match(identity, _rows(payload), reviewed, canonical=canonical)
        if match_status in {"AMBIGUOUS", "MICROVARIANT_UNPROVEN"}:
            return PptSnapshot(
                match_status,
                match_proof=match_status,
                note=match_status,
                provider_set_id=reviewed,
                identity_resolution=resolution,
            )
        if match_status == "EXACT":
            matched = row
    else:
        if canonical is None or canonical.status != "EXACT":
            return PptSnapshot(
                "TCGDEX_UNRESOLVED",
                note="unmapped PPT set requires exact TCGdex coordinate; no network",
            )
        status, payload = _request(
            session,
            api_key,
            budget,
            {
                "language": "japanese",
                "search": identity.name,
                # PPT consumes credits roughly in proportion to returned rows.
                # Keep generic discovery as tightly bounded as the reviewed path;
                # exact identity is still proved only after response matching.
                "limit": 5,
            },
            timeout,
        )
        if status is None:
            return PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
            return PptSnapshot("RATE_LIMIT", note="HTTP 429")
        if status != 200:
            return PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}")
        match_status, row, proof = _match_canonical(identity, canonical, _rows(payload))
        if match_status in {"AMBIGUOUS", "MICROVARIANT_UNPROVEN"}:
            return PptSnapshot(match_status, match_proof=proof, note=proof, identity_resolution=proof)
        if match_status == "EXACT" and row is not None:
            matched = row
            resolution = proof
            provider_set_id = str(row.get("setId") or row.get("set_id") or "").strip()

    if matched is None:
        return PptSnapshot(
            "CLEAN_NO_MATCH",
            note="exact PPT coordinate not found",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )

    tcgplayer_id = matched.get("tcgPlayerId") or matched.get("tcgplayerId")
    if not tcgplayer_id:
        return PptSnapshot(
            "CLEAN_INSUFFICIENT",
            note="TCGPLAYER_ID_MISSING",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    status, payload = _request(
        session,
        api_key,
        budget,
        {
            "language": "japanese",
            "tcgPlayerId": str(tcgplayer_id),
            "includeHistory": "true",
            "includeEbay": "true",
            "includeCardmarket": "false",
            "days": 180,
            "maxDataPoints": 180,
        },
        timeout,
    )
    if status is None:
        return PptSnapshot(
            "PENDING_BUDGET",
            note=budget.blocked_reason,
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return PptSnapshot(
            "RATE_LIMIT",
            note="HTTP 429",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )
    if status != 200:
        return PptSnapshot(
            "PROVIDER_ERROR",
            note=f"HTTP {status}",
            provider_set_id=provider_set_id,
            identity_resolution=resolution,
        )

    deep_rows = _rows(payload)
    if reviewed:
        deep_status, row = _match(identity, deep_rows, reviewed, canonical=canonical)
        deep_proof = "REVIEWED_SET_ID"
    else:
        deep_status, row, deep_proof = _match_canonical(
            identity,
            canonical,
            deep_rows,
            provider_set_id=provider_set_id,
        )
    if deep_status != "EXACT" or row is None:
        return PptSnapshot(
            deep_status,
            match_proof=deep_proof,
            note="deep identity not exact",
            provider_set_id=provider_set_id,
            identity_resolution=resolution or deep_proof,
        )

    if not _deep_coordinate_consistent(row, tcgplayer_id):
        return PptSnapshot("CLEAN_NO_MATCH", note="DEEP_COORDINATE_CONFLICT", provider_set_id=provider_set_id)
    return _snapshot_from_deep_row(
        identity,
        row,
        fx=fx,
        observed_at=observed_at,
        provider_set_id=provider_set_id,
        resolution=resolution or deep_proof,
    )
