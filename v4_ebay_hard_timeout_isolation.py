"""Hard-isolate V4 eBay scraping from Playwright/driver deadlocks.

Playwright's own navigation timeout only helps while the sync RPC can return to
Python. If the driver/browser IPC wedges, the whole V4 process can otherwise
remain blocked until GitHub's six-hour job ceiling. This module runs each
bounded eBay SOLD scrape in a disposable child process and kills the whole
child process group on a hard deadline.

A validated result is delivered through a dedicated pipe before browser
teardown. Browser cleanup then gets only a short grace period: cleanup hangs
are force-killed without discarding already-computed SOLD evidence. If no valid
result arrives before the scrape deadline, failure remains provider-unavailable,
never a clean no-match. Matching, valuation and notification semantics remain
owned by watcher.py.
"""
from __future__ import annotations

import json
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import fields
from datetime import datetime
from typing import Any

import watcher


_INSTALLED = False
_ORIGINAL_SCRAPE_EBAY_SOLD = None
_DEFAULT_HARD_TIMEOUT_SECONDS = 30
_MIN_HARD_TIMEOUT_SECONDS = 12
_DEFAULT_CLEANUP_GRACE_SECONDS = 2.0
_MIN_CLEANUP_GRACE_SECONDS = 0.25
_MAX_CLEANUP_GRACE_SECONDS = 5.0
_MAX_EARLY_RESULT_BYTES = 262_144
_RESULT_FD_ENV = "V4_EBAY_RESULT_FD"
_STAGE_LINE_RE = re.compile(r"^EBAY_STAGE\|([a-z0-9_]{1,48})\|(\d{1,9})$")
_STAGE_SUMMARY_ORDER = (
    "worker",
    "resilience_install",
    "playwright",
    "browser_launch",
    "context_create",
    "page_create",
    "scrape",
    "navigation",
    "page_wait",
    "items_count",
    "items_bulk_text",
    "items_item_text",
    "body_count",
    "body_inner_text",
    "body_text_content",
    "other_count",
    "other_inner_text",
    "page_content",
    "context_close",
    "browser_close",
)
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


def _cleanup_grace_seconds() -> float:
    raw = os.getenv(
        "V4_EBAY_CLEANUP_GRACE_SECONDS", str(_DEFAULT_CLEANUP_GRACE_SECONDS)
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_CLEANUP_GRACE_SECONDS
    return min(
        _MAX_CLEANUP_GRACE_SECONDS,
        max(_MIN_CLEANUP_GRACE_SECONDS, value),
    )


def _worker_env(*, result_fd: int | None = None) -> dict[str, str]:
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
        "V4_EBAY_STAGE_TIMING_ENABLED",
        "V4_EBAY_STAGE_TIMING_LOG_SUCCESS",
    ):
        if key in os.environ:
            output[key] = value
    # Prevent the child navigation-resilience installer from recursively
    # enabling this process-isolation layer again.
    output["V4_EBAY_ISOLATED_WORKER"] = "1"
    if result_fd is not None:
        output[_RESULT_FD_ENV] = str(result_fd)
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
                proven_commercial_dimensions=tuple(
                    item.get("proven_commercial_dimensions") or ()
                ),
                identity_provenance=str(item.get("identity_provenance") or ""),
            )
        )
    return watcher.ExternalScrapeResult(
        sales=sales,
        status=status,
        note=str(payload.get("note") or ""),
    )


def _stderr_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _stderr_from_file(handle) -> str:
    try:
        handle.flush()
        handle.seek(0)
        return _stderr_text(handle.read())
    except Exception:
        return ""


def _stage_markers(stderr: Any) -> list[tuple[str, int]]:
    """Parse only whitelisted technical markers; ignore every other stderr line."""
    markers: list[tuple[str, int]] = []
    for line in _stderr_text(stderr).splitlines():
        match = _STAGE_LINE_RE.fullmatch(line.strip())
        if match is None:
            continue
        markers.append((match.group(1), int(match.group(2))))
    return markers


def _stage_timing_summary(stderr: Any) -> str:
    markers = _stage_markers(stderr)
    if not markers:
        return ""

    starts: dict[str, list[int]] = {}
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    errors: dict[str, int] = {}
    for name, elapsed_ms in markers:
        if name.endswith("_start"):
            base = name[:-6]
            starts.setdefault(base, []).append(elapsed_ms)
            continue
        if name.endswith("_done") or name.endswith("_error"):
            base = name.rsplit("_", 1)[0]
            pending = starts.get(base)
            if not pending:
                continue
            started_ms = pending.pop()
            totals[base] = totals.get(base, 0) + max(0, elapsed_ms - started_ms)
            counts[base] = counts.get(base, 0) + 1
            if name.endswith("_error"):
                errors[base] = errors.get(base, 0) + 1

    last_name, last_ms = markers[-1]
    parts = [f"elapsed={last_ms}ms"]
    for stage in _STAGE_SUMMARY_ORDER:
        if counts.get(stage):
            parts.append(f"{stage}={totals[stage]}ms/{counts[stage]}")
            if stage == "body_text_content":
                parts.append(f"body_text_content_errors={errors.get(stage, 0)}")
    parts.append(f"last={last_name}@{last_ms}ms")
    return " | ".join(parts)


def _success_timing_log_enabled() -> bool:
    return os.getenv("V4_EBAY_STAGE_TIMING_LOG_SUCCESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _kill_worker(proc: subprocess.Popen) -> None:
    # start_new_session=True makes the worker PID the process-group ID. Use the
    # known PGID directly so Chromium descendants can still be killed even if
    # the Python group leader has already exited.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
        return
    except ProcessLookupError:
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _wait_after_kill(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _read_early_result(result_fd: int, timeout_seconds: float) -> str:
    """Read exactly one newline-delimited result, bounded by the scrape deadline."""
    deadline = time.monotonic() + timeout_seconds
    data = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("eBay result deadline exceeded")
        readable, _, _ = select.select([result_fd], [], [], remaining)
        if not readable:
            raise TimeoutError("eBay result deadline exceeded")
        chunk = os.read(result_fd, 65_536)
        if not chunk:
            raise EOFError("eBay worker closed result pipe before result")
        data.extend(chunk)
        if len(data) > _MAX_EARLY_RESULT_BYTES:
            raise ValueError("eBay worker result exceeds bounded protocol size")
        newline = data.find(b"\n")
        if newline < 0:
            continue
        if data[newline + 1 :].strip():
            raise ValueError("eBay worker emitted multiple result payloads")
        return bytes(data[:newline]).decode("utf-8")


def _finish_cleanup_after_result(proc: subprocess.Popen) -> bool:
    """Return True when teardown had to be force-killed after a valid result."""
    try:
        proc.wait(timeout=_cleanup_grace_seconds())
        return False
    except subprocess.TimeoutExpired:
        _kill_worker(proc)
        _wait_after_kill(proc)
        return True


def _run_isolated_ebay(lot: watcher.Lot) -> watcher.ExternalScrapeResult:
    payload = json.dumps({"lot": _lot_payload(lot)}, ensure_ascii=False)
    timeout_seconds = _hard_timeout_seconds()
    result_read_fd, result_write_fd = os.pipe()
    stderr_file = tempfile.TemporaryFile(mode="w+b")
    proc = None
    try:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "v4_ebay_isolated_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                text=True,
                env=_worker_env(result_fd=result_write_fd),
                pass_fds=(result_write_fd,),
                start_new_session=True,
            )
        except Exception as exc:
            watcher.log(f"eBay isolation: worker launch failed ({type(exc).__name__})")
            return watcher.ExternalScrapeResult(
                [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker launch failed"
            )
        finally:
            try:
                os.close(result_write_fd)
            except OSError:
                pass

        try:
            if proc.stdin is None:
                raise RuntimeError("eBay isolated worker stdin unavailable")
            proc.stdin.write(payload)
            proc.stdin.close()
        except Exception as exc:
            _kill_worker(proc)
            _wait_after_kill(proc)
            watcher.log(f"eBay isolation: worker input failed ({type(exc).__name__})")
            return watcher.ExternalScrapeResult(
                [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker input failed"
            )

        try:
            raw_result = _read_early_result(result_read_fd, timeout_seconds)
        except TimeoutError:
            _kill_worker(proc)
            _wait_after_kill(proc)
            timing = _stage_timing_summary(_stderr_from_file(stderr_file))
            timing_suffix = f" | {timing}" if timing else ""
            watcher.log(
                f"eBay isolation: HARD TIMEOUT before valid result after {timeout_seconds}s; "
                "child browser killed, V4 continues fail-closed"
                f"{timing_suffix}"
            )
            return watcher.ExternalScrapeResult(
                [],
                watcher.EXTERNAL_PROVIDER_ERROR,
                f"eBay hard timeout after {timeout_seconds}s",
            )
        except Exception as exc:
            _kill_worker(proc)
            _wait_after_kill(proc)
            timing = _stage_timing_summary(_stderr_from_file(stderr_file))
            timing_suffix = f" | {timing}" if timing else ""
            watcher.log(
                f"eBay isolation: worker ended before valid result ({type(exc).__name__})"
                f"{timing_suffix}"
            )
            return watcher.ExternalScrapeResult(
                [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker returned no valid result"
            )

        try:
            result = _decode_result(raw_result)
        except Exception as exc:
            _kill_worker(proc)
            _wait_after_kill(proc)
            watcher.log(f"eBay isolation: invalid early result ({type(exc).__name__})")
            return watcher.ExternalScrapeResult(
                [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay isolated worker returned invalid data"
            )

        cleanup_forced = _finish_cleanup_after_result(proc)
        timing = _stage_timing_summary(_stderr_from_file(stderr_file))
        timing_suffix = f" | {timing}" if timing else ""
        if cleanup_forced:
            watcher.log(
                "eBay isolation: valid result preserved; browser teardown exceeded "
                f"{_cleanup_grace_seconds():.2f}s grace and process group was killed"
                f"{timing_suffix}"
            )
        elif proc.returncode not in (None, 0):
            watcher.log(
                f"eBay isolation: worker teardown exit={proc.returncode} after valid result"
                f"{timing_suffix}"
            )
        elif timing and _success_timing_log_enabled():
            watcher.log(f"eBay isolation timing: {timing}")
        return result
    finally:
        try:
            os.close(result_read_fd)
        except OSError:
            pass
        try:
            stderr_file.close()
        except Exception:
            pass


def _isolated_scrape_ebay_sold(
    page, lot: watcher.Lot, *, with_status: bool = False
):
    # Deliberately do not pass or touch the parent Playwright page. A wedged
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
