from __future__ import annotations

from typing import Any

from . import source_scout_benchmark as scout
from . import source_scout_opportunity_benchmark as base
from . import source_scout_paid_v2_entrypoint as ppt


_ORIGINAL_SAFE_CLIENT = scout.SafeClient
_ORIGINAL_SUMMARY = scout.summary
_ORIGINAL_RUN_PPT = base._run_ppt


class OpportunitySafeClient(_ORIGINAL_SAFE_CLIENT):
    """Benchmark-only budgets: enough for 12 FR anchors, still tightly bounded."""

    def __init__(
        self,
        provider: str,
        *,
        call_cap: int,
        interval: float = 0.0,
        **kwargs: Any,
    ) -> None:
        if provider == "pokemonpricetracker":
            interval = max(interval, 2.2)
        if provider in {"tcgdex_ppt_anchor", "tcgdex_poketrace_anchor"}:
            call_cap = max(call_cap, 16)
        super().__init__(provider, call_cap=call_cap, interval=interval, **kwargs)


def _run_ppt_with_anchor_budget(panel, key):
    original = scout.SafeClient
    ppt.PPT_EVIDENCE.clear()
    ppt.PPT_JP_PROBES.clear()
    scout.SafeClient = OpportunitySafeClient
    try:
        rows, runtime = ppt.pokemonpricetracker_api(panel, key)
    finally:
        scout.SafeClient = original
    ppt._write_evidence()
    return rows, runtime


def _summary_with_anchor(provider, rows, runtime):
    summary = _ORIGINAL_SUMMARY(provider, rows, runtime)
    summary["identity_anchor"] = sum(row.identity == "ANCHOR_ONLY" for row in rows)
    return summary


def main() -> int:
    # PokeTrace creates its TCGdex FR anchor client directly, so keep the larger
    # deterministic anchor budget active during the whole benchmark. PPT has a
    # nested pacing override, replaced above with the same safe client.
    scout.SafeClient = OpportunitySafeClient
    scout.summary = _summary_with_anchor
    base._run_ppt = _run_ppt_with_anchor_budget
    try:
        return base.main()
    finally:
        base._run_ppt = _ORIGINAL_RUN_PPT
        scout.summary = _ORIGINAL_SUMMARY
        scout.SafeClient = _ORIGINAL_SAFE_CLIENT


if __name__ == "__main__":
    raise SystemExit(main())
