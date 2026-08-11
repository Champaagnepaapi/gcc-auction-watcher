from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Optional, Protocol

try:
    import requests
except ModuleNotFoundError:  # Offline tests inject a session.
    requests = None  # type: ignore[assignment]

from .market_values.poketrace import POKETRACE_BASE_URL


PREFLIGHT_OK = "OK"
PREFLIGHT_MISSING_API_KEY = "MISSING_API_KEY"
PREFLIGHT_TRANSPORT_ERROR = "TRANSPORT_ERROR"
PREFLIGHT_AUTH_REJECTED = "AUTH_REJECTED"
PREFLIGHT_HTTP_ERROR = "HTTP_ERROR"
PREFLIGHT_INVALID_SCHEMA = "INVALID_SCHEMA"
PREFLIGHT_INACTIVE_KEY = "INACTIVE_KEY"
PREFLIGHT_PLAN_BELOW_PRO = "PLAN_BELOW_PRO"
PREFLIGHT_UNKNOWN_PLAN = "UNKNOWN_PLAN"

_PLAN_RANK = {
    "FREE": 0,
    "PRO": 1,
    "GROWTH": 2,
    "SCALE": 3,
}


class _HttpSession(Protocol):
    def get(self, url: str, **kwargs: object) -> object:
        ...


@dataclass(frozen=True)
class PokeTracePlanPreflightConfig:
    api_key: Optional[str] = field(default=None, repr=False)
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "PokeTracePlanPreflightConfig":
        return cls(
            api_key=os.getenv("POKETRACE_API_KEY", "").strip() or None,
            timeout_seconds=float(
                os.getenv("POKETRACE_TIMEOUT_SECONDS", "15")
            ),
        )


@dataclass(frozen=True)
class PokeTracePlanPreflightResult:
    accepted: bool
    reason: str
    http_status: Optional[int] = None
    active: bool = False
    plan: Optional[str] = None
    daily_limit: Optional[int] = None
    daily_remaining: Optional[int] = None
    daily_used: Optional[int] = None
    resets_at: Optional[str] = None


def _header(headers: object, name: str) -> Optional[str]:
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if str(key).casefold() == name.casefold():
            text = str(value or "").strip()
            return text or None
    return None


def _safe_nonnegative_int(value: object) -> Optional[int]:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _safe_reset_time(value: object) -> Optional[str]:
    text = str(value or "").strip()
    if not text or len(text) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_plan(value: object) -> Optional[str]:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in _PLAN_RANK else None


def run_poketrace_plan_preflight(
    config: PokeTracePlanPreflightConfig,
    *,
    session: Optional[_HttpSession] = None,
) -> PokeTracePlanPreflightResult:
    """Validate authenticated Pro-or-higher access without retaining payloads."""

    if not config.api_key:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_MISSING_API_KEY,
        )
    if session is None:
        if requests is None:
            return PokeTracePlanPreflightResult(
                False,
                PREFLIGHT_TRANSPORT_ERROR,
            )
        session = requests.Session()

    try:
        response = session.get(
            f"{POKETRACE_BASE_URL}/auth/info",
            headers={
                "Accept": "application/json",
                "X-API-Key": config.api_key,
            },
            timeout=config.timeout_seconds,
        )
    except Exception:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_TRANSPORT_ERROR,
        )

    status = getattr(response, "status_code", None)
    status = status if isinstance(status, int) else None
    if status in {401, 403}:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_AUTH_REJECTED,
            http_status=status,
        )
    if status != 200:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_HTTP_ERROR,
            http_status=status,
        )

    try:
        payload = response.json()
    except Exception:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_INVALID_SCHEMA,
            http_status=status,
        )
    data = payload.get("data") if isinstance(payload, Mapping) else None
    user = data.get("user") if isinstance(data, Mapping) else None
    if not isinstance(data, Mapping) or not isinstance(user, Mapping):
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_INVALID_SCHEMA,
            http_status=status,
        )

    active = data.get("active") is True
    headers = getattr(response, "headers", None)
    raw_plan = user.get("plan") or _header(headers, "X-Plan")
    plan = _normalized_plan(raw_plan)
    daily_limit = _safe_nonnegative_int(
        user.get("limit") or _header(headers, "X-RateLimit-Limit")
    )
    daily_remaining = _safe_nonnegative_int(
        user.get("remaining")
        if user.get("remaining") is not None
        else _header(headers, "X-RateLimit-Remaining")
    )
    resets_at = _safe_reset_time(
        user.get("resetsAt") or _header(headers, "X-RateLimit-Reset")
    )
    daily_used = (
        max(0, daily_limit - daily_remaining)
        if daily_limit is not None and daily_remaining is not None
        else None
    )
    common = {
        "http_status": status,
        "active": active,
        "plan": plan,
        "daily_limit": daily_limit,
        "daily_remaining": daily_remaining,
        "daily_used": daily_used,
        "resets_at": resets_at,
    }
    if not active:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_INACTIVE_KEY,
            **common,
        )
    if plan is None:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_UNKNOWN_PLAN,
            **common,
        )
    if _PLAN_RANK[plan] < _PLAN_RANK["PRO"]:
        return PokeTracePlanPreflightResult(
            False,
            PREFLIGHT_PLAN_BELOW_PRO,
            **common,
        )
    return PokeTracePlanPreflightResult(
        True,
        PREFLIGHT_OK,
        **common,
    )


def _shown(value: object) -> str:
    return str(value) if value is not None else "UNAVAILABLE"


def render_poketrace_plan_preflight(
    result: PokeTracePlanPreflightResult,
) -> str:
    return "\n".join(
        (
            "=== V5 POKETRACE PLAN PREFLIGHT ===",
            f"HTTP status: {_shown(result.http_status)}",
            f"normalized plan: {_shown(result.plan)}",
            f"daily request limit: {_shown(result.daily_limit)}",
            f"daily requests used: {_shown(result.daily_used)}",
            f"daily requests remaining: {_shown(result.daily_remaining)}",
            f"daily reset UTC: {_shown(result.resets_at)}",
            f"Pro-or-higher accepted: {'YES' if result.accepted else 'NO'}",
            f"preflight reason: {result.reason}",
        )
    )


def main() -> int:
    result = run_poketrace_plan_preflight(
        PokeTracePlanPreflightConfig.from_env()
    )
    print(render_poketrace_plan_preflight(result))
    return 0 if result.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
