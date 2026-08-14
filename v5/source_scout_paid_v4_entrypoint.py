from __future__ import annotations

from typing import Any

from . import source_scout_benchmark as scout
from . import source_scout_paid_v3_entrypoint as v3


_REAL_SAFE_CLIENT = scout.SafeClient


class ConservativeSafeClient(_REAL_SAFE_CLIENT):
    """Keep PokemonPriceTracker comfortably below the observed rate-limit edge."""

    def __init__(
        self,
        provider: str,
        *,
        call_cap: int,
        interval: float = 0.0,
        response_cap: int = 2_000_000,
        total_cap: int = 100_000_000,
        **kwargs: Any,
    ) -> None:
        if provider == "pokemonpricetracker":
            interval = max(interval, 2.20)
        super().__init__(
            provider,
            call_cap=call_cap,
            interval=interval,
            response_cap=response_cap,
            total_cap=total_cap,
            **kwargs,
        )


def main() -> int:
    # Benchmark-only pacing override. No production adapter is modified.
    scout.SafeClient = ConservativeSafeClient
    try:
        return v3.main()
    finally:
        scout.SafeClient = _REAL_SAFE_CLIENT


if __name__ == "__main__":
    raise SystemExit(main())
