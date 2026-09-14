"""Actual Chromium DOM contract; run in the browser-equipped live validation job."""
import json
import os
import unittest

from v4_global_marketplace_public_probe import PRODUCT_SNAPSHOT


@unittest.skipUnless(os.environ.get('V4_TEST_BROWSER_DOM') == '1', 'requires browser-equipped job')
class MercariDOMContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(headless=True)
        cls.addClassCleanup(cls.runtime.stop)
        cls.addClassCleanup(cls.browser.close)

    def snapshot(self, feature_html, *, title='Pikachu 025/165 PSA10', schema_title=None):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        product = {'@type':'Product','name':schema_title or title}
        html = ('<meta charset="utf-8"><main><h1>' + title + '</h1><script type="application/ld+json">' + json.dumps(product) + '</script>'
                '<div><div><div><h2>商品の情報</h2></div></div><div data-testid="item-detail-category">ポケモンカードゲーム</div></div>'
                + feature_html + '<h2>出品者</h2><a data-location="item_details:item_info:metadata_link">言語: English</a></main>')
        page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
        page.goto('https://jp.mercari.com/item/m123')
        return page.evaluate(PRODUCT_SNAPSHOT)

    def feature(self, values):
        # Observed 2026-09-13: h2 nested in two heading containers,
        # item-specific metadata links in the adjacent content container.
        return '<div><div><div><h2>商品の特徴</h2></div></div><div>' + ''.join(
            '<a data-location="item_details:item_info:metadata_link">' + value + '</a>' for value in values) + '</div></div>'

    def test_real_heading_link_structure_and_seller_scope(self):
        data = self.snapshot(self.feature(['言語: 日本語版','グレード: PSA10','種別: シングルカード 1枚']))
        self.assertEqual(data['scoped_fields']['言語'], '日本語版')
        self.assertEqual(data['scoped_fields']['カテゴリー'], 'ポケモンカードゲーム')

    def test_same_product_recommendation_cannot_supply_language(self):
        data = self.snapshot('<h2>同じ商品の出品</h2><a data-location="item_details:item_info:metadata_link">言語: 日本語版</a>')
        self.assertNotIn('言語', data['scoped_fields'])

    def test_duplicate_sections_and_values_fail_closed(self):
        section = self.feature(['言語: 日本語版'])
        self.assertNotIn('言語', self.snapshot(section + section)['scoped_fields'])
        self.assertEqual(self.snapshot(self.feature(['言語: 日本語版','言語: English']))['scoped_fields']['言語'], '__conflict__')

    def test_schema_title_must_bind_same_item(self):
        self.assertEqual(self.snapshot(self.feature(['言語: 日本語版']), schema_title='Charizard')['scoped_fields'], {})
