from __future__ import annotations

from . import source_scout_benchmark as scout
from . import source_scout_opportunity_benchmark as base


_ORIGINAL_SUMMARY = scout.summary


def _summary_with_anchor(provider, rows, runtime):
    summary = _ORIGINAL_SUMMARY(provider, rows, runtime)
    summary["identity_anchor"] = sum(row.identity == "ANCHOR_ONLY" for row in rows)
    return summary


def main() -> int:
    scout.summary = _summary_with_anchor
    try:
        return base.main()
    finally:
        scout.summary = _ORIGINAL_SUMMARY


if __name__ == "__main__":
    raise SystemExit(main())
