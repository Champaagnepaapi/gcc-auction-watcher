from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Sequence

import robot_kb_multisource_harvest as harvest
import robot_kb_multisource_p3_compat as p3_compat
import robot_kb_multisource_provider_bounds as provider_bounds
import robot_kb_multisource_paid_fairness as paid_fairness
import robot_kb_public_market_resilience as public_resilience


_ORIGINAL_FINGERPRINT = harvest.fingerprint


def semantic_marketplace_fingerprint(value: object) -> str:
    """Ignore observation time when deciding whether a listing materially changed.

    Robot KB keeps the first fixed/listing baseline and subsequent economic or
    identity changes. Merely observing the same ASK again later must not create
    another listing snapshot. Price, evidence type, end time and identity remain
    part of the fingerprint.
    """

    if isinstance(value, Mapping) and "evidence_type" in value and "source_id" in value:
        stable: dict[str, Any] = dict(value)
        stable.pop("observed_at", None)
        return _ORIGINAL_FINGERPRINT(stable)
    return _ORIGINAL_FINGERPRINT(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    harvest.fingerprint = semantic_marketplace_fingerprint
    p3_compat.install(harvest)
    provider_bounds.install(harvest)
    paid_fairness.install(harvest)
    public_resilience.install(harvest)
    return harvest.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
