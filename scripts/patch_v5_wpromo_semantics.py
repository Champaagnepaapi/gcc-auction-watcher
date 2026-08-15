from pathlib import Path

variant_path = Path('v5/variant_semantics.py')
variant_text = variant_path.read_text(encoding='utf-8')
old_variant = '''    if expected.promo is True:\n        value = variants.get("wPromo")\n        if isinstance(value, bool):\n            checks.append(value)\n\n    if not checks:\n'''
new_variant = '''    # TCGdex `wPromo` means a W-stamp variant, not generic promo-card\n    # membership. Generic promo status is proven from set/rarity semantics and\n    # must never be compared to this stamp-availability flag.\n    if not checks:\n'''
if variant_text.count(old_variant) != 1:
    raise SystemExit(f'unexpected wPromo compatibility block count: {variant_text.count(old_variant)}')
variant_path.write_text(variant_text.replace(old_variant, new_variant, 1), encoding='utf-8')

micro_path = Path('v5/microvariants.py')
micro_text = micro_path.read_text(encoding='utf-8')
old_micro = '''    w_promo = variants.get("wPromo")\n    if w_promo is True:\n        single_promo = True\n        promo_proven_single = True\n        if len(true_finishes) == 0:\n            finish_proven_single = True\n            finish_multiple = False\n    elif w_promo is False:\n        single_promo = False\n        promo_proven_single = True\n    else:\n        single_promo = None\n        promo_proven_single = False\n\n'''
new_micro = '''    # TCGdex documents `wPromo` as a W-stamp availability flag. It is not\n    # generic promo-card membership and it is not a physical finish family by\n    # itself. Until V5 models W stamps as a dedicated special-finish dimension,\n    # do not let this field prove generic promo status or unblock finish.\n    single_promo = None\n    promo_proven_single = False\n\n'''
if micro_text.count(old_micro) != 1:
    raise SystemExit(f'unexpected wPromo applicability block count: {micro_text.count(old_micro)}')
micro_path.write_text(micro_text.replace(old_micro, new_micro, 1), encoding='utf-8')

coverage_path = Path('tests_v5/test_identity_coverage_expansion.py')
coverage_text = coverage_path.read_text(encoding='utf-8')
start_marker = '    def test_pure_wpromo_single_finish_applicability(self):\n'
start = coverage_text.find(start_marker)
if start < 0:
    raise SystemExit('legacy pure-wPromo test not found')
end = coverage_text.find('\n\n\nif __name__ == "__main__":', start)
if end < 0:
    raise SystemExit('legacy pure-wPromo test end marker not found')
replacement = '''    def test_wpromo_stamp_does_not_prove_generic_promo_or_finish(self):\n        """TCGdex wPromo is W-stamp availability, not generic promo/finish proof."""\n        card_promo = {\n            "id": "svp-001",\n            "name": "Pikachu",\n            "variants": {\n                "firstEdition": False,\n                "holo": False,\n                "normal": False,\n                "reverse": False,\n                "wPromo": True,\n            },\n        }\n        app = tcgdex_microvariant_applicability(card_promo)\n        self.assertFalse(app.finish_proven_single)\n        self.assertFalse(app.finish_multiple_variants)\n        self.assertFalse(app.promo_proven_single)\n        self.assertIsNone(app.single_promo)\n'''
coverage_path.write_text(coverage_text[:start] + replacement + coverage_text[end:], encoding='utf-8')

print('corrected TCGdex wPromo semantics without changing generic promo/set evidence')
