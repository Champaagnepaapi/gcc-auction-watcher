"""Hard-isolate V4 eBay scraping from Playwright/driver deadlocks.

Playwright's own navigation timeout only helps while the sync RPC can return to
Python.  If the driver/browser IPC wedges, the whole V4 process can otherwise
remain blocked until GitHub's six-hour job ceiling.  This module runs each
bounded eBay SOLD scrape in a disposable child process and kills the whole
child process group on a hard deadline.

The failure mode is provider-unavailable, never a clean no-match.  Matching,
valuation and notification semantics remain owned by watcher.py.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import fields
from datetime import datetime
from typing import Any

import watcher


_INSTALLED = False
_ORIGINAL_SCRAPE_EBAY_SOLD = None
_DEFAULT_HARD_TIMEOUT_SECONDS = 30
_MIN_HARD_TIMEOUT_SECONDS = 12
_SENSITIVE_ENV_MARKERS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "SESSION",
    "API_KEY",
    "NTFY",
)


def _hard_timeout_seconds() -> int:
    raw = os.getenv("V4_EBAY_HARD_TIMEOUT_SECONDS", str(_DEFAULT_HARD_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_HARD_TIMEOUT_SECONDS
    return max(_MIN_HARD_TIMEOUT_SECONDS, value)


def _worker_env() -> dict[str, str]:
    """Inherit runtime needs while keeping unrelated credentials out of the child."""
    output: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
            continue
        output[key] = value
    # eBay scraper configuration is intentionally public/non-secret.
    for key in (
        "EBAY_ENABLED",
        "EBAY_MIN_COMPS",
        "EBAY_MAX_RESULTS",
        "EBAY_MAX_QUERIES_PER_CARD",
        "EBAY_MAX_QUERIES",
        "EBAY_PAGE_WAIT_MS",
        "EBAY_NAV_TIMEOUT",
        "HEADLESS",
    ):
        if key in os.environ:
            output[key] = os.environ[key]
    return output


def _lot_payload(lot: watcher.Lot) -> dict[str, Any]:
    return {field.name: getattr(lot, field.name) for field in fields(watcher.Lot)}


def _parse_datetime(raw: Any):
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _decode_result(raw: str) -> watcher.ExternalScrapeResult:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("worker payload is not an object")
    status = str(payload.get("status") or "").strip()
    if not status:
        raise ValueError("worker payload missing status")
    sales = []
    for item in payload.get("sales") or []:
        if not isinstance(item, dict):
            raise ValueError("worker sale is not an object")
        sales.append(
            watcher.ComparableSale(
                price=float(item["price"]),
                source=str(item.get("source") or "ebay"),
                grader=str(item.get("grader") or ""),
                grade=(float(item["grade"]) if item.get("grade") is not None else None),
                sold_at=_parse_datetime(item.get("sold_at")),
                context=str(item.get("context") or ""),
                exact_card=bool(item.get("exact_card", True)),
                match_score=int(item.get("match_score", 100)),
                grade_qualifier=item.get("grade_qualifier"),
                proven_commercial_dimensions=tuple(item.get("proven_commercial_dimensions") or ()),
                identity_provenance=str(item.get("identity_provenance") or ""),
            )
        )
    return watcher.ExternalScrapeResult(
        sales=sales,
        status=status,
        note=str(payload.get("note") or ""),
    )


def _kill_worker(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_isolated_ebay(lot: watcher.Lot) -> watcher.ExternalScrapeResult:
    payload = json.dumps({"lot": _lot_payload(lot)}, ensure_ascii=False)
    timeout_seconds = _hard_timeout_seconds()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "v4_ebay_isolated_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_worker_env(),
            start_new_session=True,
        )
    except Exception as exc:
        watcher.log(f"eBay isolation: worker launch failed ({type(exc).__name__})")
        return watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker launch failed"
        )

    try:
        stdout, _stderr = proc.communicate(payload, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_worker(proc)
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        watcher.log(
            f"eBay isolation: HARD TIMEOUT after {timeout_seconds}s; "
            "child browser killed, V4 continues fail-closed"
        )
        return watcher.ExternalScrapeResult(
            [],
            watcher.EXTERNAL_PROVIDER_ERROR,
            f"eBay hard timeout after {timeout_seconds}s",
        )

    if proc.returncode != 0:
        watcher.log(f"eBay isolation: worker failed exit={proc.returncode}")
        return watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker failed"
        )
    try:
        return _decode_result(stdout)
    except Exception as exc:
        watcher.log(f"eBay isolation: invalid worker result ({type(exc).__name__})")
        return watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker returned invalid data"
        )


def _isolated_scrape_ebay_sold(
    page, lot: watcher.Lot, *, with_status: bool = False
):
    # Deliberately do not pass or touch the parent Playwright page.  A wedged
    # eBay browser/driver must be disposable without poisoning the V4 scanner.
    result = _run_isolated_ebay(lot)
    return result if with_status else result.sales


def install_v4_ebay_hard_timeout_isolation() -> None:
    global _INSTALLED, _ORIGINAL_SCRAPE_EBAY_SOLD
    if _INSTALLED:
        return
    _ORIGINAL_SCRAPE_EBAY_SOLD = watcher.scrape_ebay_sold
    watcher.scrape_ebay_sold = _isolated_scrape_ebay_sold
    _INSTALLED = True
