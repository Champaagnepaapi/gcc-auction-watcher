"""Bounded resilience for transient TCGdex transport failures.

PR #145 introduced and live-validated the Global transport wrapper. Global keeps
that exact policy. The V4 Main Scanner reuses it and adds only a process-local
run breaker so a provider-wide outage cannot multiply the retry cost across the
whole fixed queue. Identity, no-match and cache semantics remain unchanged:
exhausted failures still propagate as transient errors and a new scanner process
tries TCGdex again normally.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Mapping, Optional

import requests

import v4_canonical_multimarket as canonical
import watcher


_TRANSIENT_HTTP = frozenset({502, 503, 504})
_ORIGINAL_JSON_GET = None
_V4_ORIGINAL_RESILIENT_JSON_GET = None
_V4_RUN_OPEN = False
_V4_CONSECUTIVE_EXHAUSTED = 0

_DEFAULT_V4_RUN_BREAKER_THRESHOLD = 2
_MIN_V4_RUN_BREAKER_THRESHOLD = 2
_MAX_V4_RUN_BREAKER_THRESHOLD = 5


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


def _v4_run_breaker_threshold() -> int:
    raw = os.getenv(
        "V4_TCGDEX_RUN_BREAKER_THRESHOLD",
        str(_DEFAULT_V4_RUN_BREAKER_THRESHOLD),
    ).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_V4_RUN_BREAKER_THRESHOLD
    return max(
        _MIN_V4_RUN_BREAKER_THRESHOLD,
        min(_MAX_V4_RUN_BREAKER_THRESHOLD, value),
    )


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


def _record_v4_exhausted_failure() -> None:
    global _V4_RUN_OPEN, _V4_CONSECUTIVE_EXHAUSTED
    _V4_CONSECUTIVE_EXHAUSTED += 1
    threshold = _v4_run_breaker_threshold()
    if _V4_CONSECUTIVE_EXHAUSTED >= threshold and not _V4_RUN_OPEN:
        _V4_RUN_OPEN = True
        watcher.log(
            "TCGdex V4 run circuit: "
            f"{_V4_CONSECUTIVE_EXHAUSTED} consecutive exhausted transient calls; "
            "remaining TCGdex network calls skipped this run"
        )


def _call_with_v4_run_breaker(
    original: Callable[..., tuple[int, object, Mapping[str, str]]],
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float,
) -> tuple[int, object, Mapping[str, str]]:
    """Bound provider-wide TCGdex outage cost while preserving ERROR semantics."""
    global _V4_CONSECUTIVE_EXHAUSTED

    if not _is_tcgdex_url(url):
        return original(url, params=params, headers=headers, timeout=timeout)

    if _V4_RUN_OPEN:
        raise requests.ConnectionError(
            "V4 TCGdex run circuit open after repeated transient failures"
        )

    try:
        result = original(url, params=params, headers=headers, timeout=timeout)
    except (requests.Timeout, requests.ConnectionError):
        _record_v4_exhausted_failure()
        raise

    status = int(result[0] or 0)
    if status in _TRANSIENT_HTTP:
        _record_v4_exhausted_failure()
    else:
        # Any real provider response proves the transport route is alive again.
        # This includes a legitimate 404/no-match response, whose semantics are
        # left entirely to the canonical resolver.
        _V4_CONSECUTIVE_EXHAUSTED = 0
    return result


def _v4_guarded_json_get(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float,
) -> tuple[int, object, Mapping[str, str]]:
    assert _V4_ORIGINAL_RESILIENT_JSON_GET is not None
    return _call_with_v4_run_breaker(
        _V4_ORIGINAL_RESILIENT_JSON_GET,
        url,
        params=params,
        headers=headers,
        timeout=timeout,
    )


def reset_v4_tcgdex_run_breaker_for_tests() -> None:
    """Reset process-local breaker state; production gets a fresh process/run."""
    global _V4_RUN_OPEN, _V4_CONSECUTIVE_EXHAUSTED
    _V4_RUN_OPEN = False
    _V4_CONSECUTIVE_EXHAUSTED = 0


def install_global_tcgdex_resilience() -> None:
    """Install the proven transport wrapper in Global runners that opt into it."""
    global _ORIGINAL_JSON_GET
    current = canonical._json_get
    if getattr(current, "_v4_global_tcgdex_resilience", False) is True:
        return
    _ORIGINAL_JSON_GET = current
    _resilient_json_get._v4_global_tcgdex_resilience = True  # type: ignore[attr-defined]
    canonical._json_get = _resilient_json_get


def install_v4_tcgdex_resilience() -> None:
    """Reuse #145 retries plus a Main-Scanner-only process-local run breaker."""
    global _V4_ORIGINAL_RESILIENT_JSON_GET

    install_global_tcgdex_resilience()
    current = canonical._json_get
    if getattr(current, "_v4_tcgdex_run_breaker", False) is True:
        return

    _V4_ORIGINAL_RESILIENT_JSON_GET = current
    _v4_guarded_json_get._v4_global_tcgdex_resilience = True  # type: ignore[attr-defined]
    _v4_guarded_json_get._v4_tcgdex_run_breaker = True  # type: ignore[attr-defined]
    canonical._json_get = _v4_guarded_json_get
    watcher.log(
        "TCGdex V4 transport resilience enabled: max 2 attempts/call; run circuit "
        f"after {_v4_run_breaker_threshold()} consecutive exhausted transient calls"
    )
