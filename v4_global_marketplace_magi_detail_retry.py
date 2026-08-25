"""One bounded retry for Magi current-product detail retrieval.

Identity logic is unchanged. The existing detail loader is called once normally;
only an exception triggers one second read of the same public item URL. A second
failure propagates to the scanner and remains ``detail_error``.
"""
from __future__ import annotations

import v4_global_retrieval_hardening as retrieval_v1


_ORIGINAL_DETAIL = None
_INSTALLED = False


def magi_detail_once_retry(page, ask):
    assert _ORIGINAL_DETAIL is not None
    try:
        return _ORIGINAL_DETAIL(page, ask)
    except Exception:
        # Keep retry bounded and on the exact same public detail URL.  No search,
        # identity fallback, session mutation or transaction is introduced.
        try:
            page.wait_for_timeout(250)
        except Exception:
            pass
        return _ORIGINAL_DETAIL(page, ask)


def install_global_marketplace_magi_detail_retry() -> None:
    global _ORIGINAL_DETAIL, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_DETAIL = retrieval_v1.magi_detail_only
    retrieval_v1.magi_detail_only = magi_detail_once_retry
    _INSTALLED = True
