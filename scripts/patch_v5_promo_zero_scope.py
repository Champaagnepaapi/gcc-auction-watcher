from pathlib import Path

path = Path('v5/card_identity_catalog.py')
text = path.read_text(encoding='utf-8')
old = '''        promo_like = re.fullmatch(r"([A-Za-z]+)0*(\\d+)([A-Za-z]*)", local)\n        if promo_like:\n            prefix, digits, suffix = promo_like.groups()\n            candidates.append(local.upper())\n            candidates.append(\n                f"{prefix.upper()}{int(digits)}{suffix.upper()}"\n            )\n'''
new = '''        promo_like = re.fullmatch(r"([A-Za-z]+)0*(\\d+)([A-Za-z]*)", local)\n        if promo_like:\n            prefix, digits, suffix = promo_like.groups()\n            candidates.append(local.upper())\n            if prefix.upper() in _PROMO_PREFIX_TO_TCGDEX_SET_ID:\n                candidates.append(\n                    f"{prefix.upper()}{int(digits)}{suffix.upper()}"\n                )\n'''
if text.count(old) != 1:
    raise SystemExit(f'unexpected promo candidate block count: {text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('scoped zero normalization to versioned promo prefixes only')
# trigger after one-shot workflow exists
