"""Use exact GCC PSA certificate numbers before the fragile APR search page.

This bridge is retrieval-only. It does not alter commercial identity, valuation
rules, evidence thresholds, provider budgets, notifications, or transaction
behavior. A PSA Estimate is never treated as a SOLD observation.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional

import watcher


_INSTALLED = False
_ORIGINAL_FIXED_RESULT_TO_LOT = None
_ORIGINAL_SCRAPE_PSA_APR = None

_CERT_URL_TEMPLATE = "https://www.psacard.com/cert/{cert}/psa"
_CERT_RE = re.compile(r"^\d{6,12}$")
_LABELED_CERT_RE = re.compile(
    r"(?:Cert(?:ification)?(?:\s+Number)?|Num[ée]ro\s+de\s+certification|"
    r"Certification)\s*:?\s*#?\s*(\d{6,12})\b",
    re.I,
)
_ANTIBOT_MARKERS = (
    "captcha",
    "access denied",
    "verify you are human",
    "pardon our interruption",
    "too many requests",
    "just a moment...",
    "attention required",
    "cloudflare",
    "perimeterx",
    "datadome",
)
_ITEM_GRADE_RE = re.compile(
    r"\bItem\s+Grade\b\s*:?\s*(?:PSA\s*)?(10|[1-9](?:[.,]5)?)\b",
    re.I,
)
_POP_RE = re.compile(r"\bPSA\s+Population\b\s*:?\s*([\d,]+)\b", re.I)
_POP_HIGHER_RE = re.compile(r"\bPSA\s+Pop\s+Higher\b\s*:?\s*([\d,]+)\b", re.I)
_DATE_RE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:\d{2}|\d{4})\b"
)
_USD_RE = re.compile(r"\$\s*\d[\d,]*(?:\.\d{1,2})?")
_PSA_GRADE_RE = re.compile(r"\bPSA\s*(10|[1-9](?:[.,]5)?)\b", re.I)


def _clean_cert_number(value: object) -> str:
    text = str(value or "").strip()
    return text if _CERT_RE.fullmatch(text) else ""


def _attach_fixed_gcc_psa_cert(result: dict, item_url: str, coverage, **kwargs):
    lot = _ORIGINAL_FIXED_RESULT_TO_LOT(result, item_url, coverage, **kwargs)
    if lot is None or (lot.grader or "").strip().upper() != "PSA":
        return lot
    item = result.get("item") if isinstance(result, dict) else None
    if not isinstance(item, dict):
        return lot
    cert = _clean_cert_number(item.get("serialNumber"))
    if cert:
        setattr(lot, "_v4_psa_cert_number", cert)
    return lot


def _cert_number_from_lot(lot: watcher.Lot) -> str:
    direct = _clean_cert_number(getattr(lot, "_v4_psa_cert_number", ""))
    if direct:
        return direct
    text = "\n".join(
        str(value or "")
        for value in (
            getattr(lot, "body", ""),
            getattr(lot, "listing_text", ""),
        )
    )
    match = _LABELED_CERT_RE.search(text)
    return _clean_cert_number(match.group(1)) if match else ""


def _page_http_status(response) -> Optional[int]:
    if response is None or not hasattr(response, "status"):
        return None
    value = response.status
    try:
        value = value() if callable(value) else value
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_item_grade(body: str) -> Optional[float]:
    match = _ITEM_GRADE_RE.search(body or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_population(pattern: re.Pattern[str], body: str) -> Optional[int]:
    match = pattern.search(body or "")
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _cert_sale_rows(body: str) -> list[str]:
    """Extract bounded sale blocks and deliberately ignore estimate-only text."""
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in (body or "").splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]
    rows: list[str] = []
    for index, line in enumerate(lines):
        if not _DATE_RE.search(line):
            continue
        start = max(0, index - 3)
        end = min(len(lines), index + 7)
        block = lines[start:end]
        joined = "\n".join(block)
        if not _USD_RE.search(joined) or not _PSA_GRADE_RE.search(joined):
            continue
        if "PSA Estimate" in joined and not any(
            marker in joined
            for marker in ("eBay", "Fanatics", "Auction", "Best Offer", "Buy It Now")
        ):
            continue
        rows.append(joined)
        if len(rows) >= watcher.PSA_APR_MAX_RESULTS:
            break
    return rows


def _cert_page_result(
    lot: watcher.Lot,
    cert: str,
    body: str,
    *,
    usd_per_eur: float,
    now=None,
) -> watcher.PsaAprData:
    if cert not in re.sub(r"\D", "", body or ""):
        return watcher.PsaAprData(
            [],
            note="PSA cert page identity conflict: certificate number absent",
            provider_status=watcher.EXTERNAL_PROVIDER_ERROR,
        )

    target_grade = watcher._target_grade(lot)
    page_grade = _parse_item_grade(body)
    if target_grade is None or page_grade is None or abs(page_grade - target_grade) > 1e-9:
        return watcher.PsaAprData(
            [],
            note="PSA cert page identity conflict: grade mismatch",
            provider_status=watcher.EXTERNAL_PROVIDER_ERROR,
        )

    score, reason = watcher.psa_apr_match_score(lot, body)
    if score < watcher.PSA_APR_MATCH_MIN_SCORE:
        return watcher.PsaAprData(
            [],
            note=f"PSA cert page identity conflict: {reason}",
            provider_status=watcher.EXTERNAL_PROVIDER_ERROR,
        )

    rows = _cert_sale_rows(body)
    sales = watcher.parse_psa_apr_sales(rows, usd_per_eur, now)
    exact_grade_sales = [
        sale
        for sale in sales
        if sale.grade is not None and abs(float(sale.grade) - float(target_grade)) < 1e-9
    ]
    exact_grade_sales = [
        replace(
            sale,
            context=f"PSA cert {cert} | {sale.context}".strip(" |")[:300],
        )
        for sale in exact_grade_sales
    ]

    population = _parse_population(_POP_RE, body)
    pop_higher = _parse_population(_POP_HIGHER_RE, body)
    most_recent_price = None
    dated = [sale for sale in exact_grade_sales if sale.sold_at is not None]
    if dated:
        most_recent_price = max(dated, key=lambda sale: sale.sold_at).price

    data = watcher.PsaAprData(
        sales=exact_grade_sales,
        population=population,
        pop_higher=pop_higher,
        most_recent_price=most_recent_price,
        matched_url=_CERT_URL_TEMPLATE.format(cert=cert),
        match_score=score,
        note=(
            f"PSA public cert exact {cert}; "
            f"{len(exact_grade_sales)} same-grade SOLD similar-item row(s)"
        ),
        provider_status=(
            watcher.EXTERNAL_MATCHED
            if exact_grade_sales
            else watcher.EXTERNAL_CLEAN_NO_MATCH
        ),
    )
    return watcher.attach_psa_spec_provenance(data, body, lot)


def _cert_first_scrape_psa_apr(page, lot: watcher.Lot, *args, **kwargs):
    cert = _cert_number_from_lot(lot)
    if not cert:
        return _ORIGINAL_SCRAPE_PSA_APR(page, lot, *args, **kwargs)

    if (
        not watcher.PSA_APR_ENABLED
        or (lot.grader or "").strip().upper() != "PSA"
        or watcher._target_grade(lot) is None
        or not watcher.psa_apr_identity_is_sufficient(lot)
    ):
        return watcher.PsaAprData(
            [], note="APR non applicable", provider_status=watcher.EXTERNAL_CLEAN_NO_MATCH
        )

    rate = kwargs.get("usd_per_eur")
    if rate is None and args:
        rate = args[0]
    if rate is None:
        rate = watcher.get_psa_apr_usd_per_eur()
    if rate is None:
        return watcher.PsaAprData(
            [],
            note="conversion USD/EUR indisponible",
            provider_status=watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
        )

    now = kwargs.get("now")
    if now is None and len(args) >= 2:
        now = args[1]

    url = _CERT_URL_TEMPLATE.format(cert=cert)
    watcher.log(f"PSA cert direct: {cert}")
    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=watcher.PSA_APR_NAV_TIMEOUT,
        )
        status = _page_http_status(response)
        if status == 429:
            return watcher.PsaAprData(
                [],
                note="PSA cert HTTP 429",
                provider_status=watcher.EXTERNAL_RATE_LIMITED,
            )
        if status == 403:
            return watcher.PsaAprData(
                [],
                note="PSA cert HTTP 403",
                provider_status=watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            )
        if status is not None and status >= 400:
            return watcher.PsaAprData(
                [],
                note=f"PSA cert HTTP {status}",
                provider_status=watcher.EXTERNAL_PROVIDER_ERROR,
            )
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass
        body = page.locator("body").inner_text(
            timeout=min(watcher.PSA_APR_NAV_TIMEOUT, 3000)
        )
    except Exception as error:
        return watcher.PsaAprData(
            [],
            note=f"PSA cert indisponible ({type(error).__name__})",
            provider_status=watcher.EXTERNAL_PROVIDER_ERROR,
        )

    lower = (body or "").lower()
    if any(marker in lower for marker in _ANTIBOT_MARKERS):
        status = (
            watcher.EXTERNAL_RATE_LIMITED
            if "too many requests" in lower
            else watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        return watcher.PsaAprData(
            [],
            note="PSA cert refusé ou anti-bot",
            provider_status=status,
        )

    return _cert_page_result(
        lot,
        cert,
        body,
        usd_per_eur=float(rate),
        now=now,
    )


def reset_v4_psa_cert_sales_bridge_for_tests() -> None:
    global _INSTALLED, _ORIGINAL_FIXED_RESULT_TO_LOT, _ORIGINAL_SCRAPE_PSA_APR
    if _INSTALLED:
        if _ORIGINAL_FIXED_RESULT_TO_LOT is not None:
            watcher._gcc_fixed_result_to_lot = _ORIGINAL_FIXED_RESULT_TO_LOT
        if _ORIGINAL_SCRAPE_PSA_APR is not None:
            watcher.scrape_psa_apr = _ORIGINAL_SCRAPE_PSA_APR
    _INSTALLED = False
    _ORIGINAL_FIXED_RESULT_TO_LOT = None
    _ORIGINAL_SCRAPE_PSA_APR = None


def install_v4_psa_cert_sales_bridge() -> None:
    global _INSTALLED, _ORIGINAL_FIXED_RESULT_TO_LOT, _ORIGINAL_SCRAPE_PSA_APR
    if _INSTALLED:
        return

    _ORIGINAL_FIXED_RESULT_TO_LOT = watcher._gcc_fixed_result_to_lot
    _ORIGINAL_SCRAPE_PSA_APR = watcher.scrape_psa_apr
    watcher._gcc_fixed_result_to_lot = _attach_fixed_gcc_psa_cert
    watcher.scrape_psa_apr = _cert_first_scrape_psa_apr
    _INSTALLED = True

    watcher.log(
        "PSA cert bridge enabled: exact GCC serialNumber -> public PSA cert "
        "similar-item SOLD; PSA Estimate never treated as SOLD"
    )
