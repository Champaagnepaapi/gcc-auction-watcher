from pathlib import Path

path = Path('v5/card_identity_catalog.py')
text = path.read_text(encoding='utf-8')

constants_anchor = 'POKEMON_TCG_BASE = "https://api.pokemontcg.io/v2"\n\n\n# Only languages currently exposed'
constants_replacement = '''POKEMON_TCG_BASE = "https://api.pokemontcg.io/v2"\n\n\n# Explicit, versioned eBay/collector promo prefixes -> exact TCGdex set IDs.\n# A mapping is usable only when the collector number carries the same prefix;\n# the short set label alone is never sufficient identity proof.\n_PROMO_PREFIX_TO_TCGDEX_SET_ID = {\n    "DP": "dpp",\n    "HGSS": "hgssp",\n    "BW": "bwp",\n    "XY": "xyp",\n    "SM": "smp",\n    "SWSH": "swshp",\n}\n\n\n# Only languages currently exposed'''
if text.count(constants_anchor) != 1:
    raise SystemExit(f'unexpected constants anchor count: {text.count(constants_anchor)}')
text = text.replace(constants_anchor, constants_replacement, 1)

old_candidates = '''def _local_card_number_candidates(value: str) -> Tuple[str, ...]:\n    """Return only deterministic spelling alternatives for a TCGdex localId."""\n\n    local = _local_card_number(value)\n    if not local:\n        return ()\n    candidates = [local]\n    if re.fullmatch(r"0*\\d+", local):\n        candidates.append(str(int(local)))\n    elif re.fullmatch(r"[A-Za-z]+\\d+[A-Za-z]*", local):\n        candidates.append(local.upper())\n    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))\n\n\n'''
new_candidates = '''def _local_card_number_candidates(value: str) -> Tuple[str, ...]:\n    """Return only deterministic spelling alternatives for a TCGdex localId."""\n\n    local = _local_card_number(value)\n    if not local:\n        return ()\n    candidates = [local]\n    if re.fullmatch(r"0*\\d+", local):\n        candidates.append(str(int(local)))\n    else:\n        promo_like = re.fullmatch(r"([A-Za-z]+)0*(\\d+)([A-Za-z]*)", local)\n        if promo_like:\n            prefix, digits, suffix = promo_like.groups()\n            candidates.append(local.upper())\n            candidates.append(\n                f"{prefix.upper()}{int(digits)}{suffix.upper()}"\n            )\n    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))\n\n\ndef _deterministic_promo_set_id(\n    set_name: object, card_number: object\n) -> Optional[str]:\n    """Map a short promo set label only when the number proves the same prefix."""\n\n    set_code = str(set_name or "").strip().upper()\n    target_set_id = _PROMO_PREFIX_TO_TCGDEX_SET_ID.get(set_code)\n    if not target_set_id:\n        return None\n    local_number = _local_card_number(str(card_number or "")).upper()\n    match = re.fullmatch(r"([A-Z]+)0*\\d+[A-Z]*", local_number)\n    if not match or match.group(1) != set_code:\n        return None\n    return target_set_id\n\n\n'''
if text.count(old_candidates) != 1:
    raise SystemExit(f'unexpected candidate helper count: {text.count(old_candidates)}')
text = text.replace(old_candidates, new_candidates, 1)

old_resolve = '''        normalized_set = _normalize(identity.set)\n        exact_ids: dict[str, str] = {}\n        loose_ids: dict[str, str] = {}\n\n        for language in lookup_languages:\n            for set_id, name in self._tcgdex_sets(language, identity.set or ""):\n                loose_ids.setdefault(set_id, name)\n                if (\n                    _set_name_similarity(identity.set, name) == 1.0\n                    or _normalize(set_id) == normalized_set\n                ):\n                    exact_ids.setdefault(set_id, name)\n\n        if exact_ids:\n'''
new_resolve = '''        normalized_set = _normalize(identity.set)\n        exact_ids: dict[str, str] = {}\n        loose_ids: dict[str, str] = {}\n        promo_set_id = _deterministic_promo_set_id(\n            identity.set, identity.card_number\n        )\n\n        for language in lookup_languages:\n            if promo_set_id:\n                for set_id, name in self._tcgdex_all_sets(language):\n                    if str(set_id).strip().casefold() == promo_set_id.casefold():\n                        exact_ids.setdefault(set_id, name)\n                continue\n            for set_id, name in self._tcgdex_sets(language, identity.set or ""):\n                loose_ids.setdefault(set_id, name)\n                if (\n                    _set_name_similarity(identity.set, name) == 1.0\n                    or _normalize(set_id) == normalized_set\n                ):\n                    exact_ids.setdefault(set_id, name)\n\n        if exact_ids:\n'''
if text.count(old_resolve) != 1:
    raise SystemExit(f'unexpected resolve set block count: {text.count(old_resolve)}')
text = text.replace(old_resolve, new_resolve, 1)

path.write_text(text, encoding='utf-8')
print('added deterministic promo-prefix set alias and zero-normalized localId fallback')
