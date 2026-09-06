#!/usr/bin/env python3
"""Bounded anonymous probe for public COMC historical-sales semantics.

This diagnostic deliberately does not write Robot KB and does not treat
``Sold Out`` or a historical chart as a completed item-level sale.  It only
observes one or more public COMC Pokémon product pages and records whether the
site exposes explicit historical sale rows (date + price) without login.

Safety:
- public ``www.comc.com`` pages only;
- fresh Playwright context, no cookies/storage/login supplied;
- no authentication headers, subscriptions, account state or bypasses;
- no purchase/cart/offer/checkout interactions;
- bounded DOM/network capture with sanitized JSON only;
- no Robot KB mutation and no V4 economic use.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ALLOWED_HOSTS = frozenset({"www.comc.com", "comc.com"})
DEFAULT_WAIT_MS = 1200
MAX_WAIT_MS = 5000
MAX_RESPONSES = 80
MAX_DOM_LINES = 80
MAX_JSON_DEPTH = 5
MAX_JSON_LIST = 30
MAX_JSON_TEXT = 500

_HISTORY_TEXT_RE = re.compile(r"(?:4\s*year\s*sales|sales\s*history|historical\s*sales|view\s*chart)", re.I)
_LOGIN_RE = re.compile(r"(?:login\s+required|log\s*in|sign\s*in|join\s+comc)", re.I)
_DATE_KEY_RE = re.compile(r"(?:sold|sale|purchase|transaction|date|time|created|completed)", re.I)
_PRICE_KEY_RE = re.compile(r"(?:price|amount|paid|value)", re.I)
_CURRENCY_RE = re.compile(r"\b(?:USD|EUR|GBP|CAD|AUD)\b", re.I)


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _allowed_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_HOSTS


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_JSON_DEPTH:
        return "<depth-capped>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_JSON_LIST:
                out["<truncated>"] = True
                break
            name = _norm(key)[:120]
            low = name.casefold()
            if any(token in low for token in ("token", "cookie", "authorization", "session", "password", "secret")):
                continue
            out[name] = _sanitize(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:MAX_JSON_LIST]]
    if isinstance(value, str):
        return value[:MAX_JSON_TEXT]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _norm(value)[:MAX_JSON_TEXT]


def _walk_objects(value: Any):
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _walk_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_objects(item)


def _item_level_sale_candidate(obj: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """Return a diagnostic candidate only when one object has date + price.

    This is intentionally not a SOLD classifier.  The live output must still be
    reviewed for final-sale/payment semantics and exact card identity.
    """
    date_fields: dict[str, Any] = {}
    price_fields: dict[str, Any] = {}
    currency_fields: dict[str, Any] = {}
    id_fields: dict[str, Any] = {}
    for key, value in obj.items():
        name = _norm(key)
        if not name:
            continue
        if _DATE_KEY_RE.search(name) and isinstance(value, (str, int, float)) and _norm(value):
            date_fields[name] = value
        if _PRICE_KEY_RE.search(name) and isinstance(value, (str, int, float)) and _norm(value):
            price_fields[name] = value
        if "currency" in name.casefold() or (isinstance(value, str) and _CURRENCY_RE.fullmatch(value.strip())):
            currency_fields[name] = value
        if any(token in name.casefold() for token in ("itemid", "item_id", "saleid", "sale_id", "transactionid", "transaction_id")):
            id_fields[name] = value
    if not date_fields or not price_fields:
        return None
    return {
        "date_fields": _sanitize(date_fields),
        "price_fields": _sanitize(price_fields),
        "currency_fields": _sanitize(currency_fields),
        "id_fields": _sanitize(id_fields),
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_COMC_SALES_HISTORY_PROBE",
        "public_anonymous_only": True,
        "credentials_used": False,
        "cookies_supplied": False,
        "authentication_headers_supplied": False,
        "sold_out_treated_as_sale": False,
        "historical_chart_treated_as_sale": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_probe(urls: Sequence[str], *, wait_ms: int) -> Mapping[str, Any]:
    for url in urls:
        if not _allowed_url(url):
            raise ValueError(f"unsupported COMC URL: {url}")

    summary = safe_summary()
    results: list[Mapping[str, Any]] = []
    all_candidate_objects: list[Mapping[str, Any]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        for url in urls:
            captured: list[dict[str, Any]] = []

            page = context.new_page()

            def on_response(response):
                if len(captured) >= MAX_RESPONSES:
                    return
                response_url = str(response.url or "")
                parsed = urlparse(response_url)
                if not ((parsed.hostname or "").lower().endswith("comc.com")):
                    return
                content_type = str(response.headers.get("content-type", "")).lower()
                if "json" not in content_type:
                    return
                try:
                    payload = response.json()
                except Exception:
                    return
                safe = _sanitize(payload)
                candidates = []
                for obj in _walk_objects(safe):
                    candidate = _item_level_sale_candidate(obj)
                    if candidate is not None:
                        candidates.append(candidate)
                        if len(all_candidate_objects) < 40:
                            all_candidate_objects.append({"response_url": response_url[:500], **candidate})
                    if len(candidates) >= 10:
                        break
                captured.append(
                    {
                        "url": response_url[:500],
                        "status": int(response.status),
                        "candidate_sale_objects": candidates,
                        "shape": safe,
                    }
                )

            page.on("response", on_response)
            response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(wait_ms)
            body_before = page.locator("body").inner_text(timeout=7000)
            history_present = bool(_HISTORY_TEXT_RE.search(body_before))

            clicked = False
            click_error = ""
            for selector in (
                "text=View Chart",
                "text=4 year sales",
                "text=Sales History",
            ):
                try:
                    locator = page.locator(selector).first
                    if locator.count() and locator.is_visible():
                        locator.click(timeout=3000)
                        clicked = True
                        page.wait_for_timeout(wait_ms)
                        break
                except Exception as exc:
                    click_error = type(exc).__name__

            try:
                body_after = page.locator("body").inner_text(timeout=7000)
            except Exception:
                body_after = body_before
            lines = [_norm(line) for line in body_after.splitlines() if _norm(line)]
            history_lines = [line for line in lines if _HISTORY_TEXT_RE.search(line) or _CURRENCY_RE.search(line)]
            login_required = bool(_LOGIN_RE.search("\n".join(history_lines[:40])))

            result = {
                "url": url,
                "page_http_status": int(response.status) if response is not None else 0,
                "final_url": str(page.url)[:500],
                "history_ui_present": history_present,
                "history_control_clicked": clicked,
                "click_error": click_error,
                "login_or_join_text_near_history": login_required,
                "history_dom_lines": history_lines[:MAX_DOM_LINES],
                "json_responses_captured": len(captured),
                "json_responses": captured,
            }
            results.append(result)
            page.close()
        context.close()
        browser.close()

    summary.update(
        {
            "urls_checked": len(urls),
            "candidate_item_level_sale_objects": all_candidate_objects,
            "candidate_item_level_sale_object_count": len(all_candidate_objects),
            "public_item_level_sale_semantics_proven": False,
            "results": results,
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only anonymous COMC historical-sales schema probe")
    parser.add_argument("--url", action="append", dest="urls", required=True)
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 250 <= args.wait_ms <= MAX_WAIT_MS:
        parser.error(f"--wait-ms must be between 250 and {MAX_WAIT_MS}")

    try:
        payload = run_probe(tuple(args.urls), wait_ms=args.wait_ms)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        try:
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
