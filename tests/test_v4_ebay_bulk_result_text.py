import unittest

from v4_ebay_bulk_result_text import BulkTextItemLocator, EbayBulkTextPageProxy


class _Item:
    def __init__(self, text):
        self.text = text
        self.inner_text_calls = 0

    def inner_text(self, *args, **kwargs):
        self.inner_text_calls += 1
        return self.text


class _Items:
    def __init__(self, texts, *, bulk_error=False, bulk_value=None):
        self.items = [_Item(text) for text in texts]
        self.bulk_error = bulk_error
        self.bulk_value = bulk_value
        self.bulk_calls = 0
        self.nth_calls = 0

    def count(self):
        return len(self.items)

    def all_inner_texts(self):
        self.bulk_calls += 1
        if self.bulk_error:
            raise RuntimeError("bulk unavailable")
        if self.bulk_value is not None:
            return self.bulk_value
        return [item.text for item in self.items]

    def nth(self, index):
        self.nth_calls += 1
        return self.items[index]


class _Body:
    def __init__(self, text="body text", *, error=None):
        self.text = text
        self.error = error
        self.inner_text_calls = 0

    def inner_text(self, *args, **kwargs):
        self.inner_text_calls += 1
        if self.error is not None:
            raise self.error
        return self.text


class _Page:
    def __init__(self, items, body=None):
        self.items = items
        self.body = body or _Body()
        self.calls = []
        self.url = "https://www.ebay.fr/sch/i.html"

    def locator(self, selector, *args, **kwargs):
        self.calls.append(selector)
        if selector == "li.s-item":
            return self.items
        if selector == "body":
            return self.body
        raise AssertionError(selector)

    def goto(self, *args, **kwargs):
        return "goto-result"


class EbayBulkResultTextTests(unittest.TestCase):
    def test_bulk_text_is_loaded_once_and_serves_all_indexed_reads(self):
        delegate = _Items(["first", "second", "third"])
        locator = BulkTextItemLocator(delegate)

        values = [locator.nth(i).inner_text(timeout=600) for i in range(3)]

        self.assertEqual(values, ["first", "second", "third"])
        self.assertEqual(delegate.bulk_calls, 1)
        self.assertEqual(delegate.nth_calls, 3)
        self.assertEqual([item.inner_text_calls for item in delegate.items], [0, 0, 0])

    def test_bulk_failure_falls_back_to_original_per_item_inner_text(self):
        delegate = _Items(["first", "second"], bulk_error=True)
        locator = BulkTextItemLocator(delegate)

        values = [locator.nth(i).inner_text(timeout=600) for i in range(2)]

        self.assertEqual(values, ["first", "second"])
        self.assertEqual(delegate.bulk_calls, 1)
        self.assertEqual([item.inner_text_calls for item in delegate.items], [1, 1])

    def test_partial_bulk_result_falls_back_only_for_missing_index(self):
        delegate = _Items(["first", "second"], bulk_value=["first"])
        locator = BulkTextItemLocator(delegate)

        first = locator.nth(0).inner_text(timeout=600)
        second = locator.nth(1).inner_text(timeout=600)

        self.assertEqual((first, second), ("first", "second"))
        self.assertEqual(delegate.bulk_calls, 1)
        self.assertEqual(delegate.items[0].inner_text_calls, 0)
        self.assertEqual(delegate.items[1].inner_text_calls, 1)

    def test_non_list_bulk_result_fails_closed_to_original_path(self):
        delegate = _Items(["first"], bulk_value=("first",))
        locator = BulkTextItemLocator(delegate)

        self.assertEqual(locator.nth(0).inner_text(timeout=600), "first")
        self.assertEqual(delegate.bulk_calls, 1)
        self.assertEqual(delegate.items[0].inner_text_calls, 1)

    def test_normal_body_text_passes_through_without_touching_items(self):
        delegate = _Items(["Pokemon card\n42,00 EUR"])
        body_delegate = _Body("normal body")
        page = _Page(delegate, body_delegate)
        proxy = EbayBulkTextPageProxy(page)

        body = proxy.locator("body")

        self.assertEqual(body.inner_text(timeout=2500), "normal body")
        self.assertEqual(body_delegate.inner_text_calls, 1)
        self.assertEqual(delegate.bulk_calls, 0)

    def test_body_timeout_recovers_from_readable_structured_eur_rows(self):
        delegate = _Items(
            [
                "Pokemon Pikachu PSA 10\n42,00 EUR\nVendu 1 sept. 2026",
                "Pokemon Eevee PSA 9\n35,00 €\nVendu 31 août 2026",
            ]
        )
        body_delegate = _Body(error=TimeoutError("body timeout"))
        proxy = EbayBulkTextPageProxy(_Page(delegate, body_delegate))

        recovered = proxy.locator("body").inner_text(timeout=2500)

        self.assertIn("42,00 EUR", recovered)
        self.assertIn("35,00 €", recovered)
        self.assertEqual(body_delegate.inner_text_calls, 1)
        self.assertEqual(delegate.bulk_calls, 1)
        self.assertEqual([item.inner_text_calls for item in delegate.items], [0, 0])

    def test_body_timeout_with_empty_or_non_price_rows_stays_fail_closed(self):
        for texts in ([], ["Pardon our interruption"], ["Pokemon result without price"]):
            with self.subTest(texts=texts):
                delegate = _Items(texts)
                body_delegate = _Body(error=TimeoutError("body timeout"))
                proxy = EbayBulkTextPageProxy(_Page(delegate, body_delegate))

                with self.assertRaises(TimeoutError):
                    proxy.locator("body").inner_text(timeout=2500)

                self.assertEqual(delegate.bulk_calls, 1)

    def test_body_timeout_with_bulk_failure_stays_fail_closed(self):
        delegate = _Items(["Pokemon Pikachu\n42,00 EUR"], bulk_error=True)
        body_delegate = _Body(error=TimeoutError("body timeout"))
        proxy = EbayBulkTextPageProxy(_Page(delegate, body_delegate))

        with self.assertRaises(TimeoutError):
            proxy.locator("body").inner_text(timeout=2500)

        self.assertEqual(delegate.bulk_calls, 1)

    def test_non_timeout_body_error_propagates_without_structured_salvage(self):
        delegate = _Items(["Pokemon Pikachu\n42,00 EUR"])
        body_delegate = _Body(error=RuntimeError("body failed"))
        proxy = EbayBulkTextPageProxy(_Page(delegate, body_delegate))

        with self.assertRaisesRegex(RuntimeError, "body failed"):
            proxy.locator("body").inner_text(timeout=2500)

        self.assertEqual(delegate.bulk_calls, 0)

    def test_page_proxy_keeps_result_locator_and_other_page_behavior(self):
        delegate = _Items(["first"])
        page = _Page(delegate)
        proxy = EbayBulkTextPageProxy(page)

        cards = proxy.locator("li.s-item")
        body = proxy.locator("body")

        self.assertIsInstance(cards, BulkTextItemLocator)
        self.assertEqual(body.inner_text(), "body text")
        self.assertEqual(proxy.url, page.url)
        self.assertEqual(proxy.goto("url"), "goto-result")


if __name__ == "__main__":
    unittest.main()
