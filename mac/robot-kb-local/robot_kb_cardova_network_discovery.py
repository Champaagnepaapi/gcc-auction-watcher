#!/usr/bin/env python3
"""Bounded anonymous Cardova network/route discovery for Past Auctions.

Diagnostic only. It records public GET resource URLs loaded by Cardova's Past
Auctions page and scans public JavaScript bundles for Cardova auction API route
strings. It supplies no credentials/cookies/auth state, performs no POSTs and
never classifies or stores a sale.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://www.cardova.co.jp/en/auction/close?limit=24&page=1&sort=price_desc&status=close"
MAX_RESOURCES = 200
MAX_SCRIPTS = 40
MAX_SCRIPT_BYTES = 2_000_000
MAX_ROUTE_HITS = 120
ROUTE_RE = re.compile(r"(?:https://bg\.cardova\.co\.jp)?/api/v1/(?:auction|trade)/[A-Za-z0-9_?=&%./{}:$-]+")


def _allowed(url: str) -> bool:
    p = urlparse(str(url or ""))
    host = (p.hostname or "").casefold()
    return p.scheme.casefold() == "https" and (host == "cardova.co.jp" or host.endswith(".cardova.co.jp"))


def safe_summary() -> dict:
    return {
        "mode": "READ_ONLY_CARDOVA_NETWORK_DISCOVERY",
        "public_anonymous_only": True,
        "credentials_used": False,
        "cookies_supplied": False,
        "authentication_headers_supplied": False,
        "posts_issued": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run(url: str, *, wait_ms: int) -> dict:
    if not _allowed(url):
        raise ValueError(f"unsupported Cardova URL: {url}")

    resources: list[dict] = []
    route_hits: set[str] = set()
    scripts_scanned = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_response(response):
            nonlocal scripts_scanned
            response_url = str(response.url or "")
            if not _allowed(response_url):
                return
            try:
                method = str(response.request.method or "").upper()
            except Exception:
                method = ""
            if method != "GET":
                return
            if len(resources) < MAX_RESOURCES:
                try:
                    ctype = str(response.headers.get("content-type", "")).casefold()
                except Exception:
                    ctype = ""
                resources.append({"url": response_url[:700], "status": int(response.status), "content_type": ctype[:120]})
            else:
                return

            if scripts_scanned >= MAX_SCRIPTS:
                return
            try:
                ctype = str(response.headers.get("content-type", "")).casefold()
            except Exception:
                ctype = ""
            if "javascript" not in ctype and not response_url.split("?", 1)[0].endswith(".js"):
                return
            scripts_scanned += 1
            try:
                text = response.text()
            except Exception:
                return
            if len(text) > MAX_SCRIPT_BYTES:
                text = text[:MAX_SCRIPT_BYTES]
            for hit in ROUTE_RE.findall(text):
                route_hits.add(hit[:700])
                if len(route_hits) >= MAX_ROUTE_HITS:
                    break

        page.on("response", on_response)
        response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(wait_ms)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(min(wait_ms, 2000))
        except Exception:
            pass
        try:
            perf = page.evaluate("() => performance.getEntriesByType('resource').map(x => x.name)")
        except Exception:
            perf = []
        for item in perf if isinstance(perf, list) else []:
            value = str(item or "")
            if _allowed(value) and len(resources) < MAX_RESOURCES and all(r["url"] != value for r in resources):
                resources.append({"url": value[:700], "status": None, "content_type": "performance-entry"})
        page_status = int(response.status) if response is not None else 0
        final_url = str(page.url)[:700]
        context.close()
        browser.close()

    out = safe_summary()
    out.update({
        "url": url,
        "final_url": final_url,
        "page_http_status": page_status,
        "resources_seen": len(resources),
        "scripts_scanned": scripts_scanned,
        "auction_trade_route_hits": sorted(route_hits),
        "resources": resources,
    })
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--wait-ms", type=int, default=3500)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    if not 500 <= args.wait_ms <= 8000:
        ap.error("--wait-ms must be between 500 and 8000")
    try:
        payload = run(args.url, wait_ms=args.wait_ms)
        code = 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
