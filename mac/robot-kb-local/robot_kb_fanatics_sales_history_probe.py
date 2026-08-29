#!/usr/bin/env python3
"""Anonymous read-only probe for Fanatics Collect Sales History.

This is a schema-discovery tool, not a SALE_TRANSACTION writer.

Why this exists:
- Fanatics Collect publicly states that Sold Items cover sales across its markets;
- Fanatics also states unpaid sales are removed from Sales History;
- the repository already has deterministic Fanatics -> TCGdex identity resolvers;
- before coupling those pieces, we need the current public Sales History data shape.

Safety:
- fresh anonymous browser context only; no cookies/session/login/keychain/API key;
- one bounded public search page, a few bounded scrolls, no clicks or form submits;
- no anti-bot/WAF bypass, stealth, proxy or private-session reuse;
- network response headers are never captured;
- JSON bodies are captured only for Fanatics-owned hosts and are recursively
  sanitized/capped before writing the diagnostic report;
- no Robot KB access or mutation, no V4 economic use, no notification and no
  purchase/bid/checkout/payment path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse


SALES_HISTORY_ORIGIN = "https://sales-history.fanaticscollect.com"
DEFAULT_QUERY = "Pokemon"
DEFAULT_SCROLL_ROUNDS = 3
MAX_SCROLL_ROUNDS = 6
DEFAULT_WAIT_MS = 1200
MAX_WAIT_MS = 5000
MAX_RESPONSES = 120
MAX_CAPTURED_JSON = 30
MAX_JSON_TEXT_BYTES = 250_000
MAX_CANDIDATES = 50
MAX_DOM_LINES = 80
MAX_STRING = 600
MAX_LIST_ITEMS = 25
MAX_MAPPING_ITEMS = 80
MAX_JSON_DEPTH = 7

_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[_-])(?:authorization|auth|token|secret|password|passwd|cookie|session|"
    r"email|phone|address|account|user|customer|apikey|api_key|key)(?:$|[_-])",
    re.I,
)
_ANTIBOT_MARKERS = (
    "captcha",
    "access denied",
    "verify you are human",
    "pardon our interruption",
    "too many requests",
    "just a moment...",
    "attention required",
    "cloudflare",
    "perimeterx",
    "datadome",
)
_TITLE_KEYS = (
    "title",
    "itemTitle",
    "item_title",
    "name",
    "displayName",
    "display_name",
)
_PRICE_KEYS = (
    "purchasePrice",
    "purchase_price",
    "salePrice",
    "sale_price",
    "soldPrice",
    "sold_price",
    "finalPrice",
    "final_price",
    "price",
)
_ID_KEYS = (
    "id",
    "itemId",
    "item_id",
    "listingId",
    "listing_id",
    "auctionId",
    "auction_id",
    "inventoryId",
    "inventory_id",
)
_DATE_KEYS = (
    "soldAt",
    "sold_at",
    "purchaseDate",
    "purchase_date",
    "saleDate",
    "sale_date",
    "closedAt",
    "closed_at",
    "endedAt",
    "ended_at",
    "createdAt",
    "created_at",
)


@dataclass(frozen=True)
class ResponseMeta:
    url: str
    status: int
    method: str
    resource_type: str
    content_type: str
    body_captured: bool = False
    candidate_objects: int = 0


def search_url(query: str) -> str:
    clean = " ".join(str(query or "").split()).strip()
    if len(clean) < 2:
        raise ValueError("Fanatics Sales History query must contain at least 2 characters")
    return f"{SALES_HISTORY_ORIGIN}/?title={quote_plus(clean)}&sort=purchasePrice%2Cdesc"


def _sensitive_key(key: object) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key or "")).casefold()
    normalized = re.sub(r"[^a-z0-9_-]+", "_", normalized)
    return bool(_SENSITIVE_KEY_RE.search(normalized))


def sanitized_url(raw: str) -> str:
    try:
        parsed = urlparse(str(raw or ""))
    except ValueError:
        return ""
    safe_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        safe_pairs.append((key, "[REDACTED]" if _sensitive_key(key) else value[:200]))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(safe_pairs, doseq=True),
            "",
        )
    )


def fanatics_owned_host(raw: str) -> bool:
    try:
        host = (urlparse(str(raw or "")).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return host == "fanaticscollect.com" or host.endswith(".fanaticscollect.com")


def sanitize_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_JSON_DEPTH:
        return "[DEPTH_LIMIT]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_STRING] + ("…" if len(value) > MAX_STRING else "")
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= MAX_MAPPING_ITEMS:
                output["[MAPPING_TRUNCATED]"] = True
                break
            key_text = str(key)[:120]
            output[key_text] = "[REDACTED]" if _sensitive_key(key_text) else sanitize_json(
                child, depth=depth + 1
            )
        return output
    if isinstance(value, (list, tuple)):
        output = [sanitize_json(child, depth=depth + 1) for child in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            output.append("[LIST_TRUNCATED]")
        return output
    return str(value)[:MAX_STRING]


def _first(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return None


def _looks_like_sale_object(mapping: Mapping[str, Any]) -> bool:
    title = _first(mapping, _TITLE_KEYS)
    price = _first(mapping, _PRICE_KEYS)
    if not isinstance(title, str) or len(title.strip()) < 4 or price is None:
        return False
    # Do not mistake obvious aggregate/statistic objects for item-level rows.
    lower_keys = {str(key).casefold() for key in mapping}
    if any(token in key for key in lower_keys for token in ("average", "median", "percentile")):
        return False
    return True


def _sale_projection(mapping: Mapping[str, Any], *, source_url: str) -> Mapping[str, Any]:
    keep: dict[str, Any] = {
        "source_response_url": source_url,
        "title": _first(mapping, _TITLE_KEYS),
        "price": _first(mapping, _PRICE_KEYS),
        "id": _first(mapping, _ID_KEYS),
        "date": _first(mapping, _DATE_KEYS),
    }
    # Preserve a small set of identity/status fields when the public API exposes
    # them, without copying the whole provider object into the report.
    for key in (
        "grade",
        "grader",
        "gradingCompany",
        "certNumber",
        "certificationNumber",
        "year",
        "language",
        "category",
        "status",
        "saleType",
        "marketplace",
        "currency",
        "url",
        "slug",
    ):
        if key in mapping and mapping[key] not in (None, "", [], {}):
            keep[key] = sanitize_json(mapping[key])
    return {key: sanitize_json(value) for key, value in keep.items() if value not in (None, "")}


def extract_sale_candidates(value: Any, *, source_url: str) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def walk(node: Any, depth: int = 0) -> None:
        if depth >= MAX_JSON_DEPTH or len(output) >= MAX_CANDIDATES:
            return
        if isinstance(node, Mapping):
            if _looks_like_sale_object(node):
                projected = _sale_projection(node, source_url=source_url)
                key = json.dumps(projected, sort_keys=True, ensure_ascii=False, default=str)
                if key not in seen:
                    seen.add(key)
                    output.append(projected)
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, (list, tuple)):
            for child in node[:MAX_LIST_ITEMS * 4]:
                walk(child, depth + 1)

    walk(value)
    return output


def interesting_dom_lines(body: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in str(body or "").splitlines():
        line = " ".join(raw.split()).strip()
        if not line or line in seen:
            continue
        lower = line.casefold()
        if not (
            "$" in line
            or "pokemon" in lower
            or "pokémon" in lower
            or "psa" in lower
            or "sold" in lower
            or "sale" in lower
        ):
            continue
        seen.add(line)
        output.append(line[:MAX_STRING])
        if len(output) >= MAX_DOM_LINES:
            break
    return output


def safe_summary(query: str) -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_FANATICS_SALES_HISTORY_PROBE",
        "query": query,
        "public_anonymous_session": True,
        "credentials_used": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "genuine_sale_evidence_promoted": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_probe(
    page: Any,
    *,
    query: str,
    scroll_rounds: int,
    wait_ms: int,
) -> Mapping[str, Any]:
    summary = safe_summary(query)
    responses: list[ResponseMeta] = []
    captured_json: list[Mapping[str, Any]] = []
    candidates: list[Mapping[str, Any]] = []
    candidate_keys: set[str] = set()

    def on_response(response: Any) -> None:
        if len(responses) >= MAX_RESPONSES:
            return
        try:
            request = response.request
            method = str(getattr(request, "method", "") or "")
            resource_type = str(getattr(request, "resource_type", "") or "")
            url = sanitized_url(str(response.url))
            status = int(response.status)
            headers = response.headers if isinstance(response.headers, Mapping) else {}
            content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().casefold()
        except Exception:
            return

        captured = False
        object_count = 0
        if (
            len(captured_json) < MAX_CAPTURED_JSON
            and fanatics_owned_host(url)
            and ("json" in content_type or resource_type in {"xhr", "fetch"})
        ):
            try:
                text = response.text()
                if len(text.encode("utf-8", errors="ignore")) <= MAX_JSON_TEXT_BYTES:
                    parsed = json.loads(text)
                    safe = sanitize_json(parsed)
                    found = extract_sale_candidates(parsed, source_url=url)
                    for row in found:
                        key = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
                        if key in candidate_keys:
                            continue
                        candidate_keys.add(key)
                        candidates.append(row)
                        if len(candidates) >= MAX_CANDIDATES:
                            break
                    captured_json.append(
                        {
                            "url": url,
                            "status": status,
                            "content_type": content_type,
                            "shape": safe,
                            "candidate_objects": len(found),
                        }
                    )
                    captured = True
                    object_count = len(found)
            except Exception:
                pass

        responses.append(
            ResponseMeta(
                url=url,
                status=status,
                method=method,
                resource_type=resource_type,
                content_type=content_type,
                body_captured=captured,
                candidate_objects=object_count,
            )
        )

    page.on("response", on_response)
    target = search_url(query)
    response = page.goto(target, wait_until="domcontentloaded", timeout=25_000)
    page_status = 0
    if response is not None:
        try:
            page_status = int(response.status)
        except Exception:
            page_status = 0
    page.wait_for_timeout(wait_ms)
    for _ in range(scroll_rounds):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(wait_ms)

    body = page.locator("body").inner_text(timeout=7_000)
    lower = body.casefold()
    anti_bot = any(marker in lower for marker in _ANTIBOT_MARKERS)
    try:
        anchors = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => ({href:a.href, text:(a.innerText||'').trim()}))"
        )
    except Exception:
        anchors = []
    safe_links = []
    for row in anchors if isinstance(anchors, list) else []:
        if not isinstance(row, Mapping):
            continue
        href = sanitized_url(str(row.get("href") or ""))
        text = " ".join(str(row.get("text") or "").split())[:250]
        if not href or href.startswith("javascript:"):
            continue
        if "fanaticscollect" not in href.casefold() and not text:
            continue
        safe_links.append({"href": href, "text": text})
        if len(safe_links) >= 80:
            break

    summary.update(
        {
            "search_url": target,
            "page_http_status": page_status,
            "anti_bot_detected": anti_bot,
            "responses_seen": len(responses),
            "responses_truncated": len(responses) >= MAX_RESPONSES,
            "response_hosts": sorted(
                {
                    (urlparse(row.url).hostname or "")
                    for row in responses
                    if row.url
                }
            ),
            "responses": [asdict(row) for row in responses],
            "captured_json": captured_json,
            "candidate_objects": candidates[:MAX_CANDIDATES],
            "candidate_object_count": len(candidates),
            "dom_lines": interesting_dom_lines(body),
            "links": safe_links,
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Anonymous read-only schema probe for Fanatics Collect Sales History"
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scroll-rounds", type=int, default=DEFAULT_SCROLL_ROUNDS)
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS)
    args = parser.parse_args(argv)
    if not 0 <= args.scroll_rounds <= MAX_SCROLL_ROUNDS:
        parser.error(f"--scroll-rounds must be between 0 and {MAX_SCROLL_ROUNDS}")
    if not 250 <= args.wait_ms <= MAX_WAIT_MS:
        parser.error(f"--wait-ms must be between 250 and {MAX_WAIT_MS}")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                # Always isolate this probe from the user's browser profile and
                # cookies. It must prove what is publicly accessible anonymously.
                context = browser.new_context(locale="en-US")
                page = context.new_page()
                payload = run_probe(
                    page,
                    query=args.query,
                    scroll_rounds=args.scroll_rounds,
                    wait_ms=args.wait_ms,
                )
            finally:
                browser.close()
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1 if payload.get("anti_bot_detected") else 0
    except Exception as exc:
        payload = safe_summary(args.query)
        payload["error"] = f"{type(exc).__name__}: {exc}"
        try:
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
