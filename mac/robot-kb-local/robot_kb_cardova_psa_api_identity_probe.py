#!/usr/bin/env python3
"""Read-only Cardova paid-SOLD -> official PSA API -> exact TCGdex probe.

This is the successor diagnostic to the public PSA HTML cert-page probe.  Live
Mac validation proved that the HTML page is WAF-blocked (HTTP 403), so this lane
uses only PSA's documented bearer-authenticated Public API cert endpoint:

    GET https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}

The token is read from the macOS Keychain only and is never printed or persisted
in output.  PSA fields are converted into the exact bounded identity surface
already validated by ``robot_kb_cardova_psa_identity_probe``; canonical identity
still requires the existing deterministic TCGdex stack and exact microvariant
gate.  No fuzzy identity, provider alias table, Robot KB write, V4 economic use,
notification, purchase, bid, offer, checkout or payment exists here.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import requests


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402
import robot_kb_cardova_psa_identity_probe as html_probe  # noqa: E402
import v4_global_economic_confirmation as confirmation  # noqa: E402


PSA_API_BASE_URL = "https://api.psacard.com/publicapi"
PSA_CERT_URL_TEMPLATE = PSA_API_BASE_URL + "/cert/GetByCertNumber/{cert}"
PSA_TOKEN_KEYCHAIN_SERVICE = "robot-pokemon-kb-psa-public-api-token"
DEFAULT_MAX_CERTS = 20
HARD_MAX_CERTS = 20
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 10.0
_CERT_RE = re.compile(r"^\d{6,14}$")


class PsaApiIdentityProbeError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _cert(value: object) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return text if _CERT_RE.fullmatch(text) else ""


def _api_url(cert: str) -> str:
    return PSA_CERT_URL_TEMPLATE.format(cert=cert)


def _safe_api_url(url: str) -> bool:
    parsed = urlsplit(str(url or ""))
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() != "api.psacard.com":
        return False
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        return False
    match = re.fullmatch(r"/publicapi/cert/GetByCertNumber/(\d{6,14})", parsed.path)
    return bool(match)


def load_token_from_keychain(
    *,
    service: str = PSA_TOKEN_KEYCHAIN_SERVICE,
    runner: Callable[..., Any] = subprocess.run,
) -> str:
    """Read the PSA API bearer token from macOS Keychain without logging it."""
    try:
        result = runner(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as error:
        raise PsaApiIdentityProbeError(
            f"PSA token Keychain lookup failed: {type(error).__name__}"
        ) from error
    if int(getattr(result, "returncode", 1) or 0) != 0:
        raise PsaApiIdentityProbeError(
            f"PSA API token missing from macOS Keychain service {service}"
        )
    token = str(getattr(result, "stdout", "") or "").strip()
    if not token or len(token) < 16 or any(ch.isspace() for ch in token):
        raise PsaApiIdentityProbeError("PSA API token in Keychain is malformed")
    return token


def api_payload_to_item(payload: Mapping[str, Any]) -> tuple[Optional[Mapping[str, str]], str]:
    """Project PSA Public API cert JSON into the existing bounded identity surface."""
    if not isinstance(payload, Mapping):
        return None, "PSA_API_PAYLOAD_NOT_OBJECT"
    if payload.get("IsValidRequest") is False:
        return None, "PSA_API_INVALID_REQUEST"

    raw_cert = payload.get("PSACert")
    if not isinstance(raw_cert, Mapping):
        return None, "PSA_API_NO_CERT_DATA"

    cert = _cert(raw_cert.get("CertNumber"))
    if not cert:
        return None, "PSA_API_CERT_MALFORMED"

    item = {
        "Cert Number": cert,
        "Item Grade": _norm(raw_cert.get("CardGrade") or raw_cert.get("GradeDescription")),
        "Year": _norm(raw_cert.get("Year")),
        "Brand/Title": _norm(raw_cert.get("Brand")),
        "Subject": _norm(raw_cert.get("Subject")),
        "Card Number": _norm(raw_cert.get("CardNumber")),
        "Category": _norm(raw_cert.get("Category")),
        "Variety/Pedigree": _norm(raw_cert.get("Variety")),
    }
    if not item["Item Grade"]:
        return None, "PSA_API_GRADE_MISSING"
    return item, "PSA_API_ITEM_READY"


def fetch_psa_api_item(
    session: Any,
    token: str,
    cert: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Optional[Mapping[str, str]], str]:
    cert = _cert(cert)
    if not cert:
        return None, "PSA_CERT_MISSING"
    url = _api_url(cert)
    if not _safe_api_url(url):
        return None, "PSA_API_URL_REJECTED"

    try:
        response = session.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout_seconds,
        )
    except requests.RequestException as error:
        return None, f"PSA_API_EXCEPTION:{type(error).__name__}"
    except Exception as error:
        return None, f"PSA_API_EXCEPTION:{type(error).__name__}"

    try:
        status = int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    if status in {401, 403}:
        return None, f"PSA_API_AUTH_{status}"
    if status == 429:
        return None, "PSA_API_HTTP_429"
    if status != 200:
        return None, f"PSA_API_HTTP_{status}"

    try:
        payload = response.json()
    except Exception:
        return None, "PSA_API_INVALID_JSON"
    if not isinstance(payload, Mapping):
        return None, "PSA_API_PAYLOAD_NOT_OBJECT"
    return api_payload_to_item(payload)


def safe_summary() -> dict[str, Any]:
    summary = dict(html_probe.safe_summary())
    summary.update(
        {
            "mode": "READ_ONLY_CARDOVA_PAID_SOLD_OFFICIAL_PSA_API_TCGDEX_IDENTITY_PROBE",
            "psa_identity_source": "PSA_PUBLIC_API_GET_BY_CERT_NUMBER",
            "psa_html_scraping": False,
            "psa_api_bearer_auth": True,
            "psa_token_source": "MACOS_KEYCHAIN",
            "psa_token_persisted_in_output": False,
        }
    )
    return summary


def run_records(
    records: Sequence[Mapping[str, Any]],
    *,
    fetcher: Callable[[Mapping[str, Any]], tuple[Optional[Mapping[str, str]], str]],
    max_records: int,
    resolver: Callable[[Any], tuple[Any, Any]] = confirmation.resolve_global_canonical,
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]] = paid_identity._microvariant_check,
) -> Mapping[str, Any]:
    paid_identity.install_tcgdex_stack_once()
    selected = list(records[:max_records])
    blocked: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    psa_exact = 0
    macro_exact = 0
    micro_exact = 0
    circuit_open = False

    for record in selected:
        if circuit_open:
            blocked["PSA_API_CIRCUIT_OPEN"] += 1
            continue
        item, fetch_reason = fetcher(record)
        if item is None:
            blocked[fetch_reason] += 1
            if fetch_reason in {
                "PSA_API_AUTH_401",
                "PSA_API_AUTH_403",
                "PSA_API_HTTP_429",
            }:
                circuit_open = True
            continue

        surface_ok, surface_reason = html_probe._cardova_psa_surface_gate(record, item)
        if not surface_ok:
            blocked[surface_reason] += 1
            continue
        psa_exact += 1

        row, reason = html_probe.resolve_item(
            record,
            item,
            resolver=resolver,
            microvariant_checker=microvariant_checker,
        )
        if row is None:
            blocked[reason] += 1
            continue
        macro_exact += 1
        row["psa_identity_source"] = "PSA_PUBLIC_API_GET_BY_CERT_NUMBER"
        if row.get("microvariant_exact") is True:
            micro_exact += 1
        else:
            blocked[reason] += 1
        rows.append(row)

    return {
        "input_records": len(records),
        "selected_records": len(selected),
        "psa_identity_surface_exact_count": psa_exact,
        "macro_identity_exact_count": macro_exact,
        "exact_microvariant_count": micro_exact,
        "psa_api_circuit_open": circuit_open,
        "blocked": dict(sorted(blocked.items())),
        "records": rows,
    }


def load_records(path: Path) -> list[Mapping[str, Any]]:
    return html_probe.load_records(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Cardova paid SOLD identity through PSA official Public API and exact TCGdex"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_CERTS)
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--token-keychain-service", default=PSA_TOKEN_KEYCHAIN_SERVICE)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_CERTS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_CERTS}")
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")
    if not 1 <= args.timeout_seconds <= 30:
        parser.error("--timeout-seconds must be between 1 and 30")

    summary = safe_summary()
    try:
        records = load_records(args.input)
        token = load_token_from_keychain(service=args.token_keychain_service)
        session = requests.Session()

        def fetcher(record: Mapping[str, Any]):
            cert = _cert(record.get("certification_number"))
            result = fetch_psa_api_item(
                session,
                token,
                cert,
                timeout_seconds=args.timeout_seconds,
            )
            if args.delay_seconds:
                time.sleep(args.delay_seconds)
            return result

        summary.update(
            run_records(
                records,
                fetcher=fetcher,
                max_records=args.max_records,
            )
        )
        code = 0
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
