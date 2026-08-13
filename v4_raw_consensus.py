from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Mapping, Optional, Sequence

import watcher


class RawReasonCode:
    EXACT_COMPATIBLE = "EXACT_COMPATIBLE"
    LANGUAGE_MISMATCH = "LANGUAGE_MISMATCH"
    SET_MISMATCH = "SET_MISMATCH"
    NUMBER_MISMATCH = "NUMBER_MISMATCH"
    FINISH_MISMATCH = "FINISH_MISMATCH"
    EDITION_MISMATCH = "EDITION_MISMATCH"
    PROMO_MISMATCH = "PROMO_MISMATCH"
    OUTLIER_CONTAMINATION = "OUTLIER_CONTAMINATION"
    PROVIDER_DISAGREEMENT = "PROVIDER_DISAGREEMENT"
    INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"


MULTILINGUAL_DIMENSION_PATTERNS = {
    "language": {
        "french": r"\b(?:french|francais|français|franzosisch|französisch|francese|frances|francés)\b",
        "english": r"\b(?:english|anglais|englisch|inglese|ingles|inglés)\b",
        "german": r"\b(?:german|allemand|deutsch|tedesco|aleman|alemán)\b",
        "italian": r"\b(?:italian|italien|italienisch|italiano)\b",
        "spanish": r"\b(?:spanish|espagnol|spanisch|spagnolo|espanol|español)\b",
        "japanese": r"\b(?:japanese|japonais|japanisch|giapponese|japones|japonés)\b",
    },
    "edition": {
        "first_edition": (
            r"\b(?:1st edition|first edition|1ère édition|1ere edition|1ere\s*ed|"
            r"1\s*edition|1\.\s*edition|erste edition|prima edizione|1a edición|1a edicion|1a\s*ed)\b"
        ),
        "unlimited": r"\b(?:unlimited|illimitée|illimitee|unbegrenzt|illimitata|ilimitada)\b",
    },
    "shadow": {
        "shadowless": r"\b(?:shadowless|sans ombre|ohne schatten|senza ombra|sin sombra)\b"
    },
    "finish": {
        "reverse": (
            r"\b(?:reverse|reverse holo|holo reverse|reverse holofoil|"
            r"holographique reverse|reverse holographisch|reverse olografica)\b"
        ),
        "non_holo": (
            r"\b(?:non holo|non-holo|nicht holo|nicht-holo|"
            r"non holographic|non holographique|non olografica)\b"
        ),
        "holo": r"\b(?:holo|holofoil|holographic|holographique|holographisch|olografica)\b",
    },
    "special_finish": {
        "poke_ball": r"\b(?:poke ball|pokeball|reverse poke ball|reverse pokeball)\b",
        "master_ball": r"\b(?:master ball|masterball|reverse master ball|reverse masterball)\b",
        "cosmos": r"\b(?:cosmos|cosmos holo)\b",
        "galaxy": r"\b(?:galaxy|galaxy holo)\b",
        "cracked_ice": r"\b(?:cracked ice|cracked ice holo)\b",
    },
    "printing": {
        "promo": r"\b(?:promo|promotional|carte promo|promo card|black star promo)\b",
        "stamped": r"\b(?:stamped|stamp|estampillée|estampillee|mit stempel)\b",
    },
}


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def parse_multilingual_commercial_dimensions(text: str) -> dict[str, str]:
    """Deterministic parser extracting edition, finish, language and variants across languages."""
    plain = normalize_text(text)
    found: dict[str, set[str]] = {}
    for dimension, values in MULTILINGUAL_DIMENSION_PATTERNS.items():
        for value, pattern in values.items():
            if re.search(pattern, plain, re.IGNORECASE):
                found.setdefault(dimension, set()).add(value)

    # Discard 'holo' if 'reverse' or 'non_holo' is present
    finish = found.get("finish", set())
    if "reverse" in finish or "non_holo" in finish:
        finish.discard("holo")

    result: dict[str, str] = {}
    for dimension, values in found.items():
        if len(values) == 1:
            result[dimension] = next(iter(values))
        elif len(values) > 1:
            result[dimension] = "__conflict__"
    return result


@dataclass(frozen=True)
class RobustStatistics:
    median: float
    mad: float
    iqr: float
    q1: float
    q3: float
    min_val: float
    max_val: float
    dispersion: float
    outliers: tuple[float, ...]
    retained: tuple[float, ...]


@dataclass(frozen=True)
class RawProviderEstimate:
    provider: str
    central: float
    low: float
    high: float
    currency: str = "EUR"
    sample_size: int = 0
    language: str = ""
    is_exact_language: bool = False
    is_exact_variant: bool = False
    is_exact_condition: bool = False
    dispersion: float = 0.0
    anomaly_flags: tuple[str, ...] = ()
    confidence: str = "STRONG"  # "STRONG", "MODERATE", "WEAK", "REJECTED"
    reason_code: str = RawReasonCode.EXACT_COMPATIBLE
    status: str = "ACCEPTED"  # "ACCEPTED", "DOWNWEIGHTED", "REJECTED"
    provenance: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class RawConsensusResult:
    status: str  # "MATCHED", "INSUFFICIENT", "CONFLICT", "REJECTED", "ANOMALOUS"
    central: float = 0.0
    low: float = 0.0
    high: float = 0.0
    currency: str = "EUR"
    confidence: str = "REJECTED"  # "STRONG", "MODERATE", "WEAK", "REJECTED"
    providers_used: tuple[str, ...] = ()
    providers_rejected: tuple[str, ...] = ()
    is_exact_language_supported: bool = False
    disagreement_ratio: float = 1.0
    anomaly_flags: tuple[str, ...] = ()
    estimates: tuple[RawProviderEstimate, ...] = ()
    diagnostics: tuple[str, ...] = ()
    note: str = ""


def _finite_positive(value: Any) -> Optional[float]:
    try:
        val = float(value)
        if math.isfinite(val) and val > 0:
            return round(val, 2)
    except (TypeError, ValueError):
        pass
    return None


def _usd_per_eur() -> float:
    try:
        import v4_canonical_multimarket as mm
        if hasattr(mm, "_usd_per_eur"):
            return float(mm._usd_per_eur())
    except Exception:
        pass
    rate = getattr(watcher, "USD_PER_EUR", 1.08)
    return float(rate) if rate and rate > 0 else 1.08


def _to_eur(amount: Optional[float], currency: str) -> Optional[float]:
    if amount is None or amount <= 0:
        return None
    curr = currency.strip().upper()
    if curr in {"EUR", "€"}:
        return round(amount, 2)
    if curr in {"USD", "$"}:
        rate = _usd_per_eur()
        return round(amount / rate, 2)
    if curr in {"GBP", "£"}:
        return round(amount * 1.16, 2)
    return None


def _normalize_lang(language: str) -> str:
    lang = str(language or "").strip().lower()
    if lang in {"french", "français", "francais", "fr"}:
        return "fr"
    if lang in {"english", "anglais", "en"}:
        return "en"
    if lang in {"japanese", "japonais", "ja"}:
        return "ja"
    if lang in {"german", "allemand", "de"}:
        return "de"
    if lang in {"spanish", "espagnol", "es"}:
        return "es"
    if lang in {"italian", "italien", "it"}:
        return "it"
    return lang


def compute_robust_statistics(values: Sequence[float]) -> Optional[RobustStatistics]:
    """Compute Median, MAD (Median Absolute Deviation), IQR, and identify Tukey outliers."""
    pts = [float(v) for v in values if _finite_positive(v) is not None]
    if not pts:
        return None
    pts.sort()
    n = len(pts)
    med = float(median(pts))
    
    # MAD (Median Absolute Deviation)
    abs_deviations = [abs(x - med) for x in pts]
    mad = float(median(abs_deviations))
    
    # Quartiles & IQR
    if n >= 4:
        mid = n // 2
        lower_half = pts[:mid]
        upper_half = pts[mid:] if n % 2 == 0 else pts[mid + 1:]
        q1 = float(median(lower_half))
        q3 = float(median(upper_half))
    else:
        q1 = pts[0]
        q3 = pts[-1]
    iqr = max(0.0, q3 - q1)

    # Tukey Fences: [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
    fence_low = max(0.01, q1 - (1.5 * iqr if iqr > 0 else med * 0.40))
    fence_high = q3 + (1.5 * iqr if iqr > 0 else med * 0.40)

    outliers = tuple(x for x in pts if x < fence_low or x > fence_high)
    retained = tuple(x for x in pts if x not in outliers)
    if not retained:
        retained = tuple(pts)

    min_val = min(pts)
    max_val = max(pts)
    dispersion = (max_val - min_val) / med if med > 0 else 0.0

    return RobustStatistics(
        median=round(med, 2),
        mad=round(mad, 2),
        iqr=round(iqr, 2),
        q1=round(q1, 2),
        q3=round(q3, 2),
        min_val=round(min_val, 2),
        max_val=round(max_val, 2),
        dispersion=round(dispersion, 2),
        outliers=outliers,
        retained=retained,
    )


def get_catalog_proven_finish(variants: Mapping[str, Any]) -> Optional[str]:
    """Deterministically prove if a card only exists in ONE finish based on TCGdex catalog metadata.
    
    Returns 'normal', 'holo', or 'reverse' ONLY when mathematically proven by catalog invariants.
    Returns None if multiple finishes exist or if variants payload is empty/unproven.
    """
    if not isinstance(variants, Mapping) or not variants:
        return None
    
    flags = {
        "normal": variants.get("normal") is True,
        "holo": variants.get("holo") is True,
        "reverse": variants.get("reverse") is True,
    }
    true_keys = [k for k, v in flags.items() if v]
    if len(true_keys) == 1:
        return true_keys[0]
    return None


def validate_microvariant_compatibility(
    listing_dimensions: Mapping[str, str],
    provider_variant: str,
    provider_language: str,
    lot_language: str,
    catalog_proven_finish: Optional[str] = None,
) -> tuple[bool, str, str]:
    """Validate that provider RAW candidate matches listing commercial microvariants fail-closed."""
    norm_lot_lang = _normalize_lang(lot_language)
    norm_prov_lang = _normalize_lang(provider_language)

    # 1. Conflict in listing metadata
    if any(v == "__conflict__" for v in listing_dimensions.values()):
        return False, RawReasonCode.INSUFFICIENT_IDENTITY, "Listing metadata has conflicting commercial dimensions"

    # 2. Language validation
    if norm_prov_lang and norm_prov_lang != norm_lot_lang:
        if norm_prov_lang != "en":
            # Third-party non-matching language is rejected
            return False, RawReasonCode.LANGUAGE_MISMATCH, f"Language mismatch: {norm_prov_lang} vs {norm_lot_lang}"

    # 3. Promo status
    listing_printing = listing_dimensions.get("printing", "")
    is_listing_promo = "promo" in listing_printing or "promo" in listing_dimensions.get("special_finish", "")
    is_prov_promo = "promo" in provider_variant.lower()
    if is_listing_promo != is_prov_promo and is_listing_promo:
        return False, RawReasonCode.PROMO_MISMATCH, "Listing is promo but provider candidate is regular/non-promo"

    # 4. Edition validation
    listing_edition = listing_dimensions.get("edition", "")
    if listing_edition == "first_edition":
        if "unlimited" in provider_variant.lower():
            return False, RawReasonCode.EDITION_MISMATCH, "Listing is 1st Edition but provider candidate is Unlimited"
    elif listing_edition == "unlimited":
        if "1st-edition" in provider_variant.lower() or "first" in provider_variant.lower():
            return False, RawReasonCode.EDITION_MISMATCH, "Listing is Unlimited but provider candidate is 1st Edition"

    # 5. Finish validation
    listing_finish = listing_dimensions.get("finish", "")
    target_finish = listing_finish or catalog_proven_finish

    if target_finish:
        norm_prov_var = provider_variant.lower()
        if target_finish == "holo":
            if norm_prov_var in {"normal", "reverse", "unlimited", "1st-edition"}:
                return False, RawReasonCode.FINISH_MISMATCH, f"Finish mismatch: listing requires holo, provider has {provider_variant}"
        elif target_finish == "reverse":
            if norm_prov_var in {"normal", "holo", "holofoil"}:
                return False, RawReasonCode.FINISH_MISMATCH, f"Finish mismatch: listing requires reverse, provider has {provider_variant}"
        elif target_finish == "non_holo" or target_finish == "normal":
            if "holo" in norm_prov_var or "reverse" in norm_prov_var:
                return False, RawReasonCode.FINISH_MISMATCH, f"Finish mismatch: listing requires normal, provider has {provider_variant}"

    # 6. Special finish validation
    listing_spec = listing_dimensions.get("special_finish", "")
    if listing_spec and listing_spec not in {"", "__conflict__"}:
        if listing_spec not in provider_variant.lower():
            return False, RawReasonCode.FINISH_MISMATCH, f"Special finish {listing_spec} not confirmed in provider candidate"

    return True, RawReasonCode.EXACT_COMPATIBLE, "Exact compatible commercial variant"


def estimate_cardmarket_raw(
    cardmarket_data: Mapping[str, Any],
    variant: str = "normal",
    lot_language: str = "fr",
    listing_dimensions: Optional[Mapping[str, str]] = None,
    catalog_proven_finish: Optional[str] = None,
) -> Optional[RawProviderEstimate]:
    """Robust outlier-resistant estimator for Cardmarket data with microvariant validation."""
    if not isinstance(cardmarket_data, Mapping):
        return None

    dims = listing_dimensions or {}
    norm_lot_lang = _normalize_lang(lot_language)
    cm_lang = norm_lot_lang if norm_lot_lang in {"en", "fr", "de", "it", "es"} else "en"
    is_compat, reason_code, reason_msg = validate_microvariant_compatibility(
        dims, variant, cm_lang, lot_language, catalog_proven_finish
    )
    if not is_compat:
        return RawProviderEstimate(
            provider="Cardmarket",
            central=0.0,
            low=0.0,
            high=0.0,
            language=cm_lang,
            is_exact_language=(cm_lang == norm_lot_lang),
            confidence="REJECTED",
            reason_code=reason_code,
            status="REJECTED",
            note=f"Cardmarket rejected ({reason_msg})",
        )

    suffix = "-holo" if variant == "holo" else ""
    trend = _finite_positive(cardmarket_data.get(f"trend{suffix}") or cardmarket_data.get("trend"))
    avg1 = _finite_positive(cardmarket_data.get(f"avg{suffix}") or cardmarket_data.get("avg") or cardmarket_data.get(f"avg1{suffix}") or cardmarket_data.get("avg1"))
    avg7 = _finite_positive(cardmarket_data.get(f"avg7{suffix}") or cardmarket_data.get("avg7"))
    avg30 = _finite_positive(cardmarket_data.get(f"avg30{suffix}") or cardmarket_data.get("avg30"))
    low = _finite_positive(cardmarket_data.get(f"low{suffix}") or cardmarket_data.get("low") or cardmarket_data.get(f"lowPrice{suffix}") or cardmarket_data.get("lowPrice"))

    history_points: list[float] = []
    history = cardmarket_data.get("history") or cardmarket_data.get("sales") or cardmarket_data.get("points")
    if isinstance(history, Sequence):
        for item in history:
            if isinstance(item, Mapping):
                p = _finite_positive(item.get("price") or item.get("value"))
                if p:
                    history_points.append(p)
            else:
                p = _finite_positive(item)
                if p:
                    history_points.append(p)

    macro_points = [p for p in (avg1, avg7, avg30, trend) if p is not None]
    all_points = history_points if len(history_points) >= 4 else (history_points + macro_points)
    if not all_points:
        return None

    stats = compute_robust_statistics(all_points)
    if stats is None:
        return None

    anomaly_flags: list[str] = []

    # 1. Floor Disconnect Validation:
    if low is not None and low > 0:
        if trend is not None and trend > 3.0 * low:
            anomaly_flags.append("FLOOR_DISCONNECT")
        elif avg30 is not None and avg30 > 3.5 * low:
            anomaly_flags.append("FLOOR_DISCONNECT")

    # 2. Multi-Period Divergence:
    if avg7 is not None and avg30 is not None:
        if avg7 < 0.45 * avg30 or avg30 > 2.2 * avg7:
            anomaly_flags.append("OUTLIER_SPIKE")
            anomaly_flags.append("PERIOD_DIVERGENCE")

    # 3. Statistical Dispersion:
    rel_mad = stats.mad / stats.median if stats.median > 0 else 0.0
    if rel_mad > 0.45 or stats.dispersion > 1.50:
        if "OUTLIER_SPIKE" not in anomaly_flags:
            anomaly_flags.append("HIGH_DISPERSION")

    # Robust Bounds
    if "FLOOR_DISCONNECT" in anomaly_flags or "OUTLIER_SPIKE" in anomaly_flags:
        anchors = [p for p in (low, avg7, avg1) if p is not None]
        if low is not None:
            anchor_med = float(median(anchors)) if anchors else low * 1.5
            robust_central = min(anchor_med, low * 2.5)
            robust_low = max(0.01, min(low, robust_central * 0.85))
            robust_high = max(robust_central, robust_central * 1.20)
        else:
            robust_central = float(median(stats.retained))
            robust_low = max(0.01, min(stats.retained) * 0.85)
            robust_high = max(stats.retained) * 1.15

        if low and trend and trend > 4.5 * low:
            confidence = "REJECTED"
            reason_code = RawReasonCode.OUTLIER_CONTAMINATION
            status = "REJECTED"
        elif avg7 and avg30 and avg30 > 3.0 * avg7:
            confidence = "REJECTED"
            reason_code = RawReasonCode.OUTLIER_CONTAMINATION
            status = "REJECTED"
        else:
            confidence = "WEAK"
            reason_code = RawReasonCode.OUTLIER_CONTAMINATION
            status = "DOWNWEIGHTED"
    else:
        robust_central = float(median(stats.retained))
        if low is not None and low > 0:
            robust_low = max(0.01, min(low, min(stats.retained) * 0.90, robust_central * 0.85))
        else:
            robust_low = max(0.01, min(stats.retained) * 0.90)
        robust_high = max(stats.retained) * 1.10
        confidence = "STRONG" if stats.dispersion <= 0.40 else "MODERATE"
        reason_code = RawReasonCode.EXACT_COMPATIBLE
        status = "ACCEPTED"

    norm_lot_lang = _normalize_lang(lot_language)
    is_exact_lang = norm_lot_lang in {"fr", "en", "de", "it", "es"}

    note_parts = [
        f"trend={trend}€" if trend else "",
        f"avg7={avg7}€" if avg7 else "",
        f"avg30={avg30}€" if avg30 else "",
        f"low={low}€" if low else "",
    ]
    note_str = "Cardmarket (" + ", ".join(p for p in note_parts if p) + ")"
    if anomaly_flags:
        note_str += f" [{reason_code}: {', '.join(anomaly_flags)}]"

    return RawProviderEstimate(
        provider="Cardmarket",
        central=round(robust_central, 2),
        low=round(robust_low, 2),
        high=round(robust_high, 2),
        currency="EUR",
        sample_size=len(all_points),
        language=norm_lot_lang,
        is_exact_language=is_exact_lang,
        is_exact_variant=True,
        is_exact_condition=True,
        dispersion=stats.dispersion,
        anomaly_flags=tuple(anomaly_flags),
        confidence=confidence,
        reason_code=reason_code,
        status=status,
        provenance={"trend": trend, "avg1": avg1, "avg7": avg7, "avg30": avg30, "low": low, "mad": stats.mad},
        note=note_str,
    )


def estimate_tcgplayer_raw(
    tcgplayer_data: Mapping[str, Any],
    variant: str = "normal",
    lot_language: str = "fr",
    listing_dimensions: Optional[Mapping[str, str]] = None,
    catalog_proven_finish: Optional[str] = None,
) -> Optional[RawProviderEstimate]:
    """Robust estimator for TCGplayer data with exact SKU/variant matching and currency conversion."""
    if not isinstance(tcgplayer_data, Mapping):
        return None

    dims = listing_dimensions or {}
    unit = str(tcgplayer_data.get("unit") or "USD")
    norm_lot_lang = _normalize_lang(lot_language)

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
    }.get(variant, (variant,))

    norm_tcgplayer = {
        re.sub(r"[^a-z0-9]", "", str(k).lower()): (k, v)
        for k, v in tcgplayer_data.items()
        if isinstance(v, Mapping)
    }

    tier: Optional[Mapping[str, Any]] = None
    matched_tier_name = ""
    for pat in key_patterns:
        matched = norm_tcgplayer.get(pat)
        if matched is not None:
            matched_tier_name, tier = matched
            break

    if tier is None:
        return None

    is_compat, reason_code, reason_msg = validate_microvariant_compatibility(
        dims, matched_tier_name or variant, "en", lot_language, catalog_proven_finish
    )
    if not is_compat:
        return RawProviderEstimate(
            provider="TCGplayer",
            central=0.0,
            low=0.0,
            high=0.0,
            language="en",
            is_exact_language=(norm_lot_lang == "en"),
            confidence="REJECTED",
            reason_code=reason_code,
            status="REJECTED",
            note=f"TCGplayer rejected ({reason_msg})",
        )

    market_price = _finite_positive(tier.get("marketPrice"))
    mid_price = _finite_positive(tier.get("midPrice"))
    low_price = _finite_positive(tier.get("lowPrice"))
    direct_low = _finite_positive(tier.get("directLowPrice"))

    raw_val = market_price or mid_price
    if raw_val is None:
        return None

    central_eur = _to_eur(raw_val, unit)
    if central_eur is None:
        return None

    low_val = direct_low or low_price or (raw_val * 0.85)
    low_eur = _to_eur(low_val, unit) or (central_eur * 0.85)
    high_eur = round(central_eur * 1.15, 2)

    is_exact_lang = (norm_lot_lang == "en")
    confidence = "STRONG" if is_exact_lang else "MODERATE"
    status = "ACCEPTED" if is_exact_lang else "DOWNWEIGHTED"

    return RawProviderEstimate(
        provider="TCGplayer",
        central=round(central_eur, 2),
        low=round(low_eur, 2),
        high=round(high_eur, 2),
        currency="EUR",
        sample_size=1,
        language="en" if not is_exact_lang else norm_lot_lang,
        is_exact_language=is_exact_lang,
        is_exact_variant=True,
        is_exact_condition=True,
        dispersion=0.0,
        anomaly_flags=() if is_exact_lang else ("ENGLISH_PROXY",),
        confidence=confidence,
        reason_code=RawReasonCode.EXACT_COMPATIBLE if is_exact_lang else RawReasonCode.LANGUAGE_MISMATCH,
        status=status,
        provenance={"raw": raw_val, "unit": unit, "eur": central_eur},
        note=f"TCGplayer ({raw_val} {unit} -> {central_eur:.2f} €)",
    )


def estimate_justtcg_raw(
    justtcg_data: Mapping[str, Any],
    variant: str = "normal",
    lot_language: str = "fr",
    listing_dimensions: Optional[Mapping[str, str]] = None,
    catalog_proven_finish: Optional[str] = None,
) -> Optional[RawProviderEstimate]:
    """Robust estimator for JustTCG data with exact language and Near Mint condition benchmark."""
    if not isinstance(justtcg_data, Mapping):
        return None

    dims = listing_dimensions or {}
    unit = str(justtcg_data.get("currency") or "EUR")
    norm_lot_lang = _normalize_lang(lot_language)
    data_lang = _normalize_lang(str(justtcg_data.get("language") or "fr"))

    is_compat, reason_code, reason_msg = validate_microvariant_compatibility(
        dims, variant, data_lang, lot_language, catalog_proven_finish
    )
    if not is_compat:
        return RawProviderEstimate(
            provider="JustTCG",
            central=0.0,
            low=0.0,
            high=0.0,
            language=data_lang,
            is_exact_language=(data_lang == norm_lot_lang),
            confidence="REJECTED",
            reason_code=reason_code,
            status="REJECTED",
            note=f"JustTCG rejected ({reason_msg})",
        )

    market_price = _finite_positive(justtcg_data.get("marketPrice") or justtcg_data.get("price") or justtcg_data.get("central"))
    low_price = _finite_positive(justtcg_data.get("lowPrice") or justtcg_data.get("low"))
    high_price = _finite_positive(justtcg_data.get("highPrice") or justtcg_data.get("high"))

    if market_price is None:
        return None

    central_eur = _to_eur(market_price, unit)
    if central_eur is None:
        return None

    low_eur = _to_eur(low_price, unit) if low_price else round(central_eur * 0.85, 2)
    high_eur = _to_eur(high_price, unit) if high_price else round(central_eur * 1.15, 2)

    is_exact_lang = (data_lang == norm_lot_lang)
    confidence = "STRONG" if is_exact_lang else "MODERATE"
    status = "ACCEPTED" if is_exact_lang else "DOWNWEIGHTED"

    return RawProviderEstimate(
        provider="JustTCG",
        central=round(central_eur, 2),
        low=round(low_eur or central_eur * 0.85, 2),
        high=round(high_eur or central_eur * 1.15, 2),
        currency="EUR",
        sample_size=int(justtcg_data.get("salesCount") or 1),
        language=data_lang,
        is_exact_language=is_exact_lang,
        is_exact_variant=True,
        is_exact_condition=True,
        dispersion=0.0,
        anomaly_flags=() if is_exact_lang else ("PROXY_LANGUAGE",),
        confidence=confidence,
        reason_code=RawReasonCode.EXACT_COMPATIBLE if is_exact_lang else RawReasonCode.LANGUAGE_MISMATCH,
        status=status,
        provenance={"raw": market_price, "currency": unit, "eur": central_eur},
        note=f"JustTCG ({central_eur:.2f} € | {data_lang})",
    )


def estimate_pricecharting_raw(
    pricecharting_data: Mapping[str, Any],
    lot_language: str = "fr",
    listing_dimensions: Optional[Mapping[str, str]] = None,
) -> Optional[RawProviderEstimate]:
    """Robust estimator for PriceCharting loose/ungraded reference."""
    if not isinstance(pricecharting_data, Mapping):
        return None

    loose_val = _finite_positive(
        pricecharting_data.get("ungraded")
        or pricecharting_data.get("loose")
        or pricecharting_data.get("raw")
    )
    if loose_val is None:
        return None

    unit = str(pricecharting_data.get("currency") or "USD")
    central_eur = _to_eur(loose_val, unit)
    if central_eur is None:
        return None

    norm_lot_lang = _normalize_lang(lot_language)
    is_exact_lang = (norm_lot_lang == "en")
    confidence = "MODERATE" if is_exact_lang else "WEAK"
    status = "ACCEPTED" if is_exact_lang else "DOWNWEIGHTED"

    return RawProviderEstimate(
        provider="PriceCharting",
        central=round(central_eur, 2),
        low=round(central_eur * 0.85, 2),
        high=round(central_eur * 1.15, 2),
        currency="EUR",
        sample_size=1,
        language="en",
        is_exact_language=is_exact_lang,
        is_exact_variant=True,
        is_exact_condition=True,
        dispersion=0.0,
        anomaly_flags=() if is_exact_lang else ("ENGLISH_PROXY",),
        confidence=confidence,
        reason_code=RawReasonCode.EXACT_COMPATIBLE if is_exact_lang else RawReasonCode.LANGUAGE_MISMATCH,
        status=status,
        provenance={"loose": loose_val, "unit": unit, "eur": central_eur},
        note=f"PriceCharting ({loose_val} {unit} -> {central_eur:.2f} €)",
    )


def estimate_ebay_raw(
    ebay_data: Mapping[str, Any],
    lot_language: str = "fr",
    listing_dimensions: Optional[Mapping[str, str]] = None,
) -> Optional[RawProviderEstimate]:
    """Robust estimator for exact eBay sold raw comparables."""
    if not isinstance(ebay_data, Mapping):
        return None

    sales = ebay_data.get("sales")
    if not isinstance(sales, Sequence) or not sales:
        return None

    eur_sales: list[float] = []
    for s in sales:
        if isinstance(s, Mapping):
            p = _finite_positive(s.get("price"))
            curr = str(s.get("currency") or "EUR")
            converted = _to_eur(p, curr)
            if converted:
                eur_sales.append(converted)
        else:
            p = _finite_positive(s)
            if p:
                eur_sales.append(p)

    if not eur_sales:
        return None

    stats = compute_robust_statistics(eur_sales)
    if stats is None:
        return None

    central_eur = float(median(stats.retained))
    low_eur = min(stats.retained)
    high_eur = max(stats.retained)
    count = len(eur_sales)

    norm_lot_lang = _normalize_lang(lot_language)
    data_lang = _normalize_lang(str(ebay_data.get("language") or norm_lot_lang))
    is_exact_lang = (data_lang == norm_lot_lang)

    confidence = "STRONG" if (count >= 3 and is_exact_lang) else "MODERATE"
    status = "ACCEPTED" if is_exact_lang else "DOWNWEIGHTED"

    return RawProviderEstimate(
        provider="eBay RAW",
        central=round(central_eur, 2),
        low=round(low_eur, 2),
        high=round(high_eur, 2),
        currency="EUR",
        sample_size=count,
        language=data_lang,
        is_exact_language=is_exact_lang,
        is_exact_variant=True,
        is_exact_condition=True,
        dispersion=stats.dispersion,
        anomaly_flags=(),
        confidence=confidence,
        reason_code=RawReasonCode.EXACT_COMPATIBLE if is_exact_lang else RawReasonCode.LANGUAGE_MISMATCH,
        status=status,
        provenance={"sales_count": count, "sales": eur_sales, "mad": stats.mad},
        note=f"eBay RAW ({count} ventes: {central_eur:.2f} €)",
    )


def arbitrate_raw_consensus(
    estimates: Sequence[RawProviderEstimate],
    lot_language: str = "fr",
) -> RawConsensusResult:
    """Arbitrate multi-provider estimates using statistical consensus and reason-coded diagnostics.
    
    1. Rejects incompatible microvariants and anomalous outliers with precise reason codes.
    2. Prioritizes exact-language providers for non-English cards.
    3. Computes cross-provider dispersion & disagreement ratio.
    4. Produces rich observability audit logs for diagnostics and notifications.
    """
    valid_estimates = [e for e in estimates if e is not None]
    if not valid_estimates:
        return RawConsensusResult(
            status="INSUFFICIENT",
            diagnostics=("No RAW provider estimates available",),
            note="Aucune source RAW disponible",
        )

    diagnostics: list[str] = []
    rejected_providers: list[str] = []

    # First pass: check explicit rejections
    non_rejected = []
    for e in valid_estimates:
        if e.confidence == "REJECTED" or e.status == "REJECTED" or e.central <= 0:
            rejected_providers.append(f"{e.provider} [{e.reason_code}]")
            diagnostics.append(f"{e.provider}: REJECTED [{e.reason_code}] ({e.note})")
        else:
            non_rejected.append(e)

    if not non_rejected:
        return RawConsensusResult(
            status="REJECTED",
            confidence="REJECTED",
            providers_rejected=tuple(rejected_providers),
            estimates=tuple(valid_estimates),
            diagnostics=tuple(diagnostics),
            note="Toutes les sources RAW ont été rejetées",
        )

    # Separate non-anomalous candidates from flagged candidates
    clean_candidates = [
        e for e in non_rejected
        if e.confidence in {"STRONG", "MODERATE"}
        and not any(flag in e.anomaly_flags for flag in ("FLOOR_DISCONNECT", "OUTLIER_SPIKE"))
    ]
    anomalous_candidates = [
        e for e in non_rejected
        if e not in clean_candidates
    ]

    accepted_estimates: list[RawProviderEstimate] = []

    if clean_candidates:
        clean_centrals = [e.central for e in clean_candidates]
        clean_stats = compute_robust_statistics(clean_centrals)
        clean_ref = clean_stats.median if clean_stats else float(median(clean_centrals))

        for anom in anomalous_candidates:
            raw_trend = anom.provenance.get("trend") or anom.provenance.get("raw") or anom.central
            trend_ratio = float(raw_trend) / clean_ref if clean_ref > 0 and raw_trend else 1.0
            central_ratio = anom.central / clean_ref if clean_ref > 0 else 1.0

            if trend_ratio > 1.80 or trend_ratio < 0.40 or central_ratio > 1.80 or central_ratio < 0.40:
                rejected_providers.append(f"{anom.provider} [{RawReasonCode.OUTLIER_CONTAMINATION}]")
                diagnostics.append(f"{anom.provider}: REJECTED [{RawReasonCode.OUTLIER_CONTAMINATION}] (trend {float(raw_trend):.2f}€ vs consensus ref {clean_ref:.2f}€)")
            else:
                accepted_estimates.append(anom)
                diagnostics.append(f"{anom.provider}: DOWNWEIGHTED [{anom.reason_code}] ({anom.note})")

        for clean in clean_candidates:
            accepted_estimates.append(clean)
            status_label = "ACCEPTED" if clean.is_exact_language else "DOWNWEIGHTED"
            diagnostics.append(f"{clean.provider}: {status_label} [{clean.reason_code}] ({clean.note})")
    else:
        for anom in anomalous_candidates:
            accepted_estimates.append(anom)
            diagnostics.append(f"{anom.provider}: DOWNWEIGHTED [{anom.reason_code}] ({anom.note})")

    if not accepted_estimates:
        return RawConsensusResult(
            status="REJECTED",
            confidence="REJECTED",
            providers_rejected=tuple(rejected_providers),
            estimates=tuple(valid_estimates),
            diagnostics=tuple(diagnostics),
            note="Toutes les sources RAW ont été rejetées pour anomalie",
        )

    # Language Prioritization
    norm_lot_lang = _normalize_lang(lot_language)
    exact_lang_estimates = [e for e in accepted_estimates if e.is_exact_language]
    has_exact_lang = len(exact_lang_estimates) > 0

    centrals = [e.central for e in accepted_estimates]
    stats = compute_robust_statistics(centrals)
    disagreement_ratio = round(max(centrals) / min(centrals), 2) if min(centrals) > 0 else 1.0

    anomaly_flags: list[str] = []
    if disagreement_ratio > 1.75:
        anomaly_flags.append(RawReasonCode.PROVIDER_DISAGREEMENT)
        diagnostics.append(f"CONSENSUS: WARNING [{RawReasonCode.PROVIDER_DISAGREEMENT}] (ratio {disagreement_ratio:.2f} > 1.75)")

    # Confidence Assignment based on agreement and sample size
    if len(accepted_estimates) >= 2:
        if disagreement_ratio <= 1.35 and (stats.dispersion if stats else 0.0) <= 0.35:
            confidence = "STRONG"
        elif disagreement_ratio <= 1.75:
            confidence = "MODERATE"
        else:
            confidence = "WEAK"
    elif len(accepted_estimates) == 1:
        single = accepted_estimates[0]
        if single.confidence == "STRONG" and single.is_exact_language:
            confidence = "MODERATE"
        else:
            confidence = "WEAK"
    else:
        confidence = "REJECTED"

    if has_exact_lang and len(exact_lang_estimates) < len(accepted_estimates):
        weighted_points = [e.central for e in exact_lang_estimates] * 2 + [
            e.central for e in accepted_estimates if not e.is_exact_language
        ]
        consensus_central = float(median(weighted_points))
    else:
        consensus_central = stats.median if stats else float(median(centrals))

    consensus_low = min(e.low for e in accepted_estimates)
    consensus_high = max(e.high for e in accepted_estimates)
    providers_used = tuple(e.provider for e in accepted_estimates)

    note_parts = [f"{e.provider}: {e.central:.2f} €" for e in accepted_estimates]
    if rejected_providers:
        note_parts.append(f"Rejetés: [{', '.join(rejected_providers)}]")
    note_str = "; ".join(note_parts)

    status = "CONFLICT" if confidence == "WEAK" and disagreement_ratio > 1.75 else "MATCHED"

    return RawConsensusResult(
        status=status,
        central=round(consensus_central, 2),
        low=round(consensus_low, 2),
        high=round(consensus_high, 2),
        currency="EUR",
        confidence=confidence,
        providers_used=providers_used,
        providers_rejected=tuple(rejected_providers),
        is_exact_language_supported=has_exact_lang,
        disagreement_ratio=disagreement_ratio,
        anomaly_flags=tuple(anomaly_flags),
        estimates=tuple(valid_estimates),
        diagnostics=tuple(diagnostics),
        note=note_str,
    )
