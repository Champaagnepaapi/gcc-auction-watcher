from __future__ import annotations

from . import source_scout_language_entrypoint as language
from . import source_scout_opportunity_ppt_validation as base
from . import source_scout_paid_v3_entrypoint as v3


def main() -> int:
    # The opportunity harness historically referenced the quota helper through
    # v3, while the actual helper lives in source_scout_language_entrypoint.
    # Keep the validated harness unchanged and provide the correct helper only
    # for this branch-local validation run.
    had_old = hasattr(v3, "_update_quota")
    old = getattr(v3, "_update_quota", None)
    v3._update_quota = language._update_quota
    try:
        return base.main()
    finally:
        if had_old:
            v3._update_quota = old
        else:
            delattr(v3, "_update_quota")


if __name__ == "__main__":
    raise SystemExit(main())
