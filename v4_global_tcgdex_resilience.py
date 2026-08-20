"""Global-only bounded resilience for transient TCGdex transport failures.

This wrapper is deliberately not installed by the canonical V4 production scanner.
It changes neither identity rules nor negative-evidence semantics: exhausted retries
still propagate as transient errors, so callers remain fail-closed.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Mapping, Optional

import requests

import v4_canonical_multimarket as canonical


_TRANSIENT_HTTP = frozenset({502, 503, 504})
_ORIGINAL_JSON_GET = None


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 2) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _is_tcgdex_url(url: object) -> bool:
    value = str(url or "").strip()
    base = canonical.TCGDEX_BASE_URL.rstrip("/")
    return value == base or value.startswith(base + "/")


def _call_with_tcgdex_resilience(
    original: Callable[..., tuple[int, object, Mapping[str, str]]],
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float,
) -> tuple[int, object, Mapping[str, str]]:
    """Retry one transient TCGdex GET at most once; never reclassify failure."""
    if not _is_tcgdex_url(url):
        return original(url, params=params, headers=headers, timeout=timeout)

    attempts = _env_int("GLOBAL_TCGDEX_MAX_ATTEMPTS", 2)
    effective_timeout = max(
        float(timeout),
        _env_float("GLOBAL_TCGDEX_REQUEST_TIMEOUT_SECONDS", 10.0, 0.5),
    )
    backoff = _env_float("GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS", 0.25, 0.0)

    for attempt in range(attempts):
        try:
            result = original(
                url,
                params=params,
                headers=headers,
                timeout=effective_timeout,
            )
        except (requests.Timeout, requests.ConnectionError):
            if attempt + 1 >= attempts:
                raise
            if backoff:
                time.sleep(backoff)
            continue

        status = int(result[0] or 0)
        if status in _TRANSIENT_HTTP and attempt + 1 < attempts:
            if backoff:
                time.sleep(backoff)
            continue
        return result

    raise RuntimeError("GLOBAL_TCGDEX_RETRY_EXHAUSTED")


def _resilient_json_get(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float,
) -> tuple[int, object, Mapping[str, str]]:
    assert _ORIGINAL_JSON_GET is not None
    return _call_with_tcgdex_resilience(
        _ORIGINAL_JSON_GET,
        url,
        params=params,
        headers=headers,
        timeout=timeout,
    )


def install_global_tcgdex_resilience() -> None:
    """Install the transport wrapper only in Global runners that opt into it."""
    global _ORIGINAL_JSON_GET
    current = canonical._json_get
    if getattr(current, "_v4_global_tcgdex_resilience", False):
        return
    _ORIGINAL_JSON_GET = current
    _resilient_json_get._v4_global_tcgdex_resilience = True  # type: ignore[attr-defined]
    canonical._json_get = _resilient_json_get
