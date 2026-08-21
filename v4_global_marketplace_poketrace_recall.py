from __future__ import annotations

from collections import Counter
from typing import Mapping, Optional

import v4_canonical_multimarket as multimarket
import v4_poketrace_market_retrieval as retrieval


_ORIGINAL_GET = None
_INSTALLED = False


def _record_final_candidates(candidates) -> None:
    if not retrieval._diagnostics_enabled():
        return
    lot = retrieval._ACTIVE_DIAGNOSTIC_LOT.get()
    canonical = retrieval._ACTIVE_DIAGNOSTIC_CANONICAL.get()
    diagnostic = retrieval._ACTIVE_DIAGNOSTIC_RESULT.get()
    if lot is None or canonical is None or diagnostic is None:
        return
    reasons = Counter(
        retrieval._diagnostic_rejection_reason(lot, canonical, candidate)
        for candidate in candidates
    )
    diagnostic["provider_candidates"] = len(candidates)
    diagnostic["candidate_gate_counts"] = dict(sorted(reasons.items()))


def _fallback_params(
    params: Optional[Mapping[str, object]],
    *,
    search: str,
    game: str,
) -> dict[str, object]:
    output = dict(params or {})
    output.pop("card_number", None)
    output["search"] = search
    output["game"] = game
    return output


def _global_recall_paced_get(
    budget: multimarket.RequestBudget,
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
):
    assert _ORIGINAL_GET is not None
    primary = _ORIGINAL_GET(budget, url, params=params)

    context = retrieval._ACTIVE_CONTEXT.get()
    if context is None or not url.rstrip("/").endswith("/cards"):
        return primary

    status, payload, _headers = primary
    candidates = multimarket._extract_list_payload(payload)
    if status != 200 or candidates:
        return primary

    searches = (
        f"{context.search_name} {context.card_number}".strip(),
        context.card_number,
    )
    for search in dict.fromkeys(value for value in searches if value):
        response = retrieval._ORIGINAL_PACED_GET(
            budget,
            url,
            params=_fallback_params(params, search=search, game=context.game),
        )
        fallback_status, fallback_payload, _ = response
        if fallback_status != 200:
            continue
        fallback_candidates = multimarket._extract_list_payload(fallback_payload)
        if fallback_candidates:
            _record_final_candidates(fallback_candidates)
            return response

    _record_final_candidates([])
    return primary


def install_global_marketplace_poketrace_recall() -> None:
    global _ORIGINAL_GET, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_GET = multimarket._paced_poketrace_get
    multimarket._paced_poketrace_get = _global_recall_paced_get
    _INSTALLED = True
