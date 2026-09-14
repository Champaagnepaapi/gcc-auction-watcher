"""Deterministic PriceCharting identity proof, separate from retrieval scores."""
import re
from urllib.parse import unquote, urlsplit

import watcher


def norm(value):
    return watcher._normalized_identity_value(value)


def category_from_url(url):
    match = re.search(r"/game/([^/]+)/", urlsplit(str(url)).path)
    return unquote(match.group(1)).replace("-", " ") if match else ""


def set_label(value):
    text = norm(value)
    text = re.sub(r"^pokemon\s+", "", text)
    text = re.sub(r"^(?:japanese|english|french|german|spanish|italian)\s+", "", text)
    # Provider release-family scaffolding, never a card-by-card alias.
    return re.sub(r"^(?:scarlet violet|sword shield|sun moon)\s+", "", text)


def exact_identity(lot, row):
    identity = watcher.extract_card_identity(lot)
    expected_name = norm(identity.get("core") or lot.title)
    expected_set = set_label(lot.card_set or identity.get("series"))
    number = str(lot.card_number or identity.get("ref") or "").lstrip("#").strip()
    product = str(row.get("product-name") or "")
    console = str(row.get("console-name") or "")
    if not expected_name or not expected_set or not number or not console:
        return False
    match = re.fullmatch(r"\s*(.*?)\s*#\s*([A-Za-z0-9]+(?:/[A-Za-z0-9-]+)?)\s*(.*?)\s*", product)
    if not match:
        return False
    name, actual_number, suffix = match.groups()
    left, _, right = number.partition("/")
    actual_left, _, actual_right = actual_number.partition("/")
    if norm(left).lstrip("0") != norm(actual_left).lstrip("0"):
        return False
    if actual_right and norm(actual_right) != norm(right):
        return False
    if right and not right.isdigit() and norm(right) != norm(actual_right):
        return False
    # Public H1 may repeat the category after the collector number. It must
    # agree with the URL category; it cannot be overridden by that URL.
    categories = [console]
    if suffix:
        suffix = suffix.strip(" ()")
        if not norm(suffix).startswith("pokemon "):
            return False
        categories.append(suffix)
    expected_dims = watcher.expected_commercial_dimensions(lot)
    expected_language = expected_dims.get("language")
    if not expected_language or "__conflict__" in expected_dims.values():
        return False
    for category in categories:
        languages = watcher._commercial_dimension_candidates(category).get("language", set())
        if languages != {expected_language}:
            return False
        actual_set = set_label(category)
        # Japanese provider promo pages pool set labels, but the full printed
        # promo namespace (e.g. 214/S-P) remains compulsory and exact above.
        promo = (expected_language == "japanese" and right and not right.isdigit()
                 and actual_set == "promo" and "promo" in expected_set)
        if actual_set != expected_set and not promo:
            return False
    observed = watcher._commercial_dimension_candidates(name)
    expected = {k: v for k, v in expected_dims.items() if k != "language"}
    if observed != {k: {v} for k, v in expected.items()}:
        return False
    # Only dedicated bracketed material annotations are removable from a name.
    # Unknown words in a bracket stay blocking; substring/name scores are not proof.
    for bracket in re.findall(r"\[([^\]]+)\]", name):
        residual = norm(bracket)
        for dimension, patterns in watcher.COMMERCIAL_DIMENSION_PATTERNS.items():
            if dimension != "language":
                for pattern in patterns.values():
                    residual = re.sub(pattern, " ", residual)
        if residual.strip():
            return False
    name = re.sub(r"\[[^\]]+\]", "", name)
    return norm(name) == expected_name
