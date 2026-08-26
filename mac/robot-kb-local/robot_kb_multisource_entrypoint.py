from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Sequence

import robot_kb_multisource_harvest as harvest


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
    return harvest.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
