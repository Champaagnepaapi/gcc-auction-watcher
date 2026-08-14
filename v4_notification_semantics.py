from __future__ import annotations

from email.header import Header

import watcher


_ORIGINAL_NOTIFY = watcher.notify
_INSTALLED = False


def opportunity_title(op: watcher.Opportunity, decision: watcher.NotificationDecision) -> str | None:
    """Return a safer title override for ordinary opportunity notifications.

    Final-alert, external-rescue and grade-arbitrage titles keep their existing
    semantics. A GCC-only or external-pending valuation must not be presented as
    an externally confirmed "FORTE OPPORTUNITÉ".
    """
    if decision.final_alert or op.valuation_path == watcher.PATH_EXTERNAL_RESCUE:
        return None
    if op.estimate.grade_arbitrage:
        return None

    prefix = "GCC AUCTION" if op.lot.source_type == "auction" else "GCC PRIX FIXE"
    if op.valuation_path == watcher.PATH_GCC_EXTERNAL_CONFIRMED:
        return f"{prefix} — FORTE OPPORTUNITÉ CONFIRMÉE"
    if op.valuation_path == watcher.PATH_EXTERNAL_PENDING:
        return f"{prefix} — OPPORTUNITÉ GCC — EXTERNE EN ATTENTE"
    if op.valuation_path == watcher.PATH_GCC_ONLY:
        return f"{prefix} — OPPORTUNITÉ GCC — EXTERNE NON CONFIRMÉ"
    return None


def _rewrite_notification_payload(data: object, title: str) -> object:
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return data
        first_break = text.find("\n")
        rewritten = title if first_break < 0 else title + text[first_break:]
        return rewritten.encode("utf-8")
    if isinstance(data, str):
        first_break = data.find("\n")
        return title if first_break < 0 else title + data[first_break:]
    return data


def notify_with_external_confirmation_semantics(
    op: watcher.Opportunity,
    decision: watcher.NotificationDecision,
) -> None:
    """Preserve V4 economics and only correct the user-facing ntfy title.

    The original notifier remains authoritative for message contents, timing,
    state and notification decisions. The synchronous POST is intercepted only
    long enough to replace the first message line + HTTP Title header.
    """
    desired_title = opportunity_title(op, decision)
    if not desired_title or not watcher.NTFY_TOPIC:
        return _ORIGINAL_NOTIFY(op, decision)

    original_post = watcher.requests.post

    def post_with_safe_title(url, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers["Title"] = Header(desired_title, "utf-8").encode()
        kwargs["headers"] = headers
        kwargs["data"] = _rewrite_notification_payload(kwargs.get("data"), desired_title)
        return original_post(url, *args, **kwargs)

    watcher.requests.post = post_with_safe_title
    try:
        return _ORIGINAL_NOTIFY(op, decision)
    finally:
        watcher.requests.post = original_post


def install_v4_notification_semantics() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    watcher.notify = notify_with_external_confirmation_semantics
    _INSTALLED = True
