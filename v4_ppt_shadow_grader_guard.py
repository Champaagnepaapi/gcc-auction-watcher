"""Fail-closed grader guard for the V4 PokemonPriceTracker shadow.

PokemonPriceTracker graded eBay coverage is currently documented for PSA, BGS,
CGC and SGC. Unsupported graders must never consume a PPT request/credit.
This module only changes shadow-provider scheduling; production V4 economics and
notifications remain untouched.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

import v4_ppt_shadow_language_bridge as ppt_bridge
import v4_ppt_shadow_provider as ppt_base

SUPPORTED_PPT_GRADERS = ("PSA", "BGS", "CGC", "SGC")
_GRADER_PRIORITY = {grader: index for index, grader in enumerate(SUPPORTED_PPT_GRADERS)}
_INSTALLED = False


def normalize_grader(value: object) -> str:
    return str(value or "").strip().upper()


def is_supported_ppt_grader(value: object) -> bool:
    return normalize_grader(value) in _GRADER_PRIORITY


def prioritize_shadow_candidates(candidates: Sequence[Any]) -> list[Any]:
    """Stable shadow-only ordering: supported graders first, then unsupported.

    Unsupported candidates are subsequently filtered before the collector, so
    this ordering can never alter V4 production opportunity ordering/economics.
    """

    def key(candidate: Any) -> tuple[int, int]:
        lot = getattr(candidate, "lot", None)
        grader = normalize_grader(getattr(lot, "grader", ""))
        return (_GRADER_PRIORITY.get(grader, len(_GRADER_PRIORITY)), 0)

    return sorted(list(candidates), key=key)


def guarded_fetch_snapshot(
    original_fetch: Callable[..., Any],
    identity: Any,
    grader: str,
    grade: object,
    key: str,
    budget: Any,
    session: Any,
    timeout: float,
):
    """Network hard-stop for unsupported graders, independent of caller logic."""
    normalized = normalize_grader(grader)
    if normalized not in _GRADER_PRIORITY:
        return "UNSUPPORTED_GRADER", None, [], f"PPT_GRADER_UNSUPPORTED:{normalized or 'UNKNOWN'}"
    return original_fetch(identity, grader, grade, key, budget, session, timeout)


def install_v4_ppt_shadow_grader_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_fetch = ppt_base.fetch_snapshot
    original_collect = ppt_bridge.collect_ppt_shadow_cross_language

    def fetch_snapshot_guarded(identity, grader, grade, key, budget, session, timeout):
        return guarded_fetch_snapshot(
            original_fetch, identity, grader, grade, key, budget, session, timeout
        )

    def collect_supported_first(candidates, opportunities, state, now, *, session=None):
        ordered = prioritize_shadow_candidates(candidates)
        supported = [
            candidate
            for candidate in ordered
            if is_supported_ppt_grader(getattr(getattr(candidate, "lot", None), "grader", ""))
        ]
        skipped = len(ordered) - len(supported)
        summary = original_collect(
            supported, opportunities, state, now, session=session
        )
        summary["blocked_grader"] = skipped
        root = state.get(ppt_bridge.STATE_KEY)
        if isinstance(root, dict):
            last_run = root.get("last_run")
            if isinstance(last_run, dict) and isinstance(last_run.get("summary"), dict):
                last_run["summary"]["blocked_grader"] = skipped
                last_run["supported_graders"] = list(SUPPORTED_PPT_GRADERS)
        return summary

    ppt_base.fetch_snapshot = fetch_snapshot_guarded
    ppt_bridge.collect_ppt_shadow_cross_language = collect_supported_first
    _INSTALLED = True
