import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401
from scripts.flipkart_challenge_one import (
    CATEGORY_DEFINITIONS,
    DEFAULT_URLS,
    detect_category_matches,
    inspect_isolated_cart,
    scan,
    slug,
)


class TestFlipkartChallengeOne(unittest.TestCase):
    def test_default_scan_covers_at_least_five_public_pages(self):
        self.assertGreaterEqual(len(DEFAULT_URLS), 5)
        self.assertTrue(all(url.startswith("https://www.flipkart.com") for url in DEFAULT_URLS))

    def test_taxonomy_contains_all_thirteen_atlas_categories(self):
        self.assertEqual(len(CATEGORY_DEFINITIONS), 13)
        self.assertEqual(
            [name for _, name, _ in CATEGORY_DEFINITIONS],
            [
                "False Urgency", "Basket Sneaking", "Confirm Shaming", "Forced Action",
                "Subscription Trap", "Interface Interference", "Bait and Switch",
                "Drip Pricing", "Disguised Advertisement", "Nagging", "Trick Question",
                "SaaS Billing", "Rogue Malware",
            ],
        )

    def test_category_heuristics_return_multiple_categories_and_never_malware(self):
        text = (
            "Only few left. Sponsored. A recommended plan is selected by default. "
            "Continue without protection. A free trial renews monthly. "
            "No, I don't want to save money. Login to continue. "
            "₹49 platform fee added at checkout. Subscription billed monthly. "
            "This prompt will be shown again if you decline."
        )
        html = (
            '<input id="protection" type="checkbox" checked>'
            '<label for="protection">Add purchase protection</label>'
        )
        matches = detect_category_matches(text, html)
        self.assertTrue(matches["DP01"])
        self.assertTrue(matches["DP02"])
        self.assertTrue(matches["DP03"])
        self.assertTrue(matches["DP04"])
        self.assertTrue(matches["DP05"])
        self.assertTrue(matches["DP06"])
        self.assertTrue(matches["DP08"])
        self.assertTrue(matches["DP10"])
        self.assertTrue(matches["DP12"])
        self.assertEqual(matches["DP09"], [])
        self.assertEqual(matches["DP13"], [])

    def test_checkbox_or_disclosure_words_alone_are_not_dark_pattern_evidence(self):
        matches = detect_category_matches(
            "Sponsored. Remind me later. Monthly offers.",
            '<input id="size" type="checkbox" checked>'
            '<label for="size">Large size</label>',
        )
        self.assertEqual(matches["DP02"], [])
        self.assertEqual(matches["DP09"], [])
        self.assertEqual(matches["DP10"], [])
        self.assertEqual(matches["DP12"], [])

    def test_isolated_cart_checks_one_product_and_never_submits_checkout(self):
        class FakeLocator:
            def __init__(self, page, selector):
                self.page = page
                self.selector = selector
                self.action = None
                self.index = 0

            @property
            def first(self):
                return self

            def nth(self, index):
                self.index = index
                return self

            def filter(self, *, has_text):
                self.action = has_text
                return self

            def count(self):
                if self.selector == 'a[href*="/p/"]':
                    return 2
                if self.selector == "Add to cart":
                    return 1 if "itm456" in self.page.url else 0
                if self.selector == "Remove":
                    return 1 if self.page.url.endswith("/viewcart") and not self.page.cart_empty else 0
                return 1

            def get_attribute(self, _name):
                return (
                    "/unavailable-phone/p/itm123"
                    if self.index == 0
                    else "/sample-phone/p/itm456"
                )

            def click(self, **_kwargs):
                if self.selector == "Add to cart":
                    self.page.add_clicked = True
                elif self.selector == "Remove":
                    self.page.remove_clicked = True

            def inner_text(self, **_kwargs):
                if self.page.cart_empty and self.page.url.endswith("/viewcart"):
                    return "Missing Cart items? Login"
                if "itm123" in self.page.url:
                    return "Currently unavailable"
                return "₹49 platform fee added at checkout"

        class FakePage:
            url = "https://www.flipkart.com/search?q=phone"

            def __init__(self):
                self.add_clicked = False
                self.remove_clicked = False
                self.cart_empty = False

            def locator(self, selector):
                return FakeLocator(self, selector)

            def get_by_text(self, text, **_kwargs):
                return FakeLocator(self, text)

            def goto(self, url, **_kwargs):
                self.url = url

            def wait_for_load_state(self, *_args, **_kwargs):
                pass

            def content(self):
                return (
                    '<input id="protection" type="checkbox" checked>'
                    '<label for="protection">Add purchase protection</label>'
                )

            def title(self):
                return "Isolated cart"

            def screenshot(self, path, **_kwargs):
                Path(path).write_bytes(b"fake-png")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "screenshots").mkdir()
            (output / "dom").mkdir()
            page = FakePage()
            events = []
            interaction, record = inspect_isolated_cart(
                page, output, 2, 2, 1_000,
                on_page=lambda item, index, total: events.append((item, index, total)),
            )

        self.assertTrue(page.add_clicked)
        self.assertTrue(page.remove_clicked)
        self.assertFalse(interaction["checkout_submitted"])
        self.assertTrue(interaction["remove_action_clicked"])
        self.assertEqual(interaction["status"], "INSPECTED")
        statuses = {item["pattern_id"]: item["status"] for item in record["category_results"]}
        self.assertEqual(statuses["DP02"], "POTENTIAL")
        self.assertEqual(statuses["DP08"], "POTENTIAL")
        self.assertEqual(events[0][1:], (2, 2))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "screenshots").mkdir()
            (output / "dom").mkdir()
            empty_page = FakePage()
            empty_page.cart_empty = True
            empty_interaction, _ = inspect_isolated_cart(empty_page, output, 2, 2, 1_000)

        self.assertEqual(empty_interaction["status"], "EMPTY")
        self.assertFalse(empty_interaction["remove_action_clicked"])

    def test_slug_is_safe_for_artifact_names(self):
        value = slug("https://www.flipkart.com/search?q=headphones")
        self.assertEqual(value, "www-flipkart-com-search-q-headphones")
        self.assertNotRegex(value, r"[^a-z0-9-]")

    def test_scan_writes_structured_report_without_network(self):
        class FakeLocator:
            def inner_text(self, **kwargs):
                return "Only 2 left! Limited time offer."

            def evaluate(self, _expression):
                return "DIV"

            @property
            def first(self):
                return self

            def count(self):
                return 0

            def filter(self, **_kwargs):
                return self

        class FakePage:
            url = "https://www.flipkart.com/"

            def set_default_timeout(self, _timeout):
                pass

            def goto(self, *_args, **_kwargs):
                pass

            def wait_for_load_state(self, *_args, **_kwargs):
                pass

            def locator(self, _selector):
                return FakeLocator()

            def title(self):
                return "Flipkart"

            def screenshot(self, path, **_kwargs):
                Path(path).write_bytes(b"fake-png")

            def content(self):
                return "<html><body>Only 2 left!</body></html>"

        class FakeContext:
            def new_page(self):
                return FakePage()

            def close(self):
                pass

        class FakeBrowser:
            def new_context(self, **_kwargs):
                return FakeContext()

            def close(self):
                pass

        class FakePlaywright:
            class chromium:
                @staticmethod
                def launch(**_kwargs):
                    return FakeBrowser()

        callbacks = []
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.flipkart_challenge_one.sync_playwright"
        ) as sync_playwright:
            sync_playwright.return_value.__enter__.return_value = FakePlaywright()
            report = scan([DEFAULT_URLS[0]], Path(directory), on_page=lambda page, index, total: callbacks.append((page, index, total)))
            saved = json.loads((Path(directory) / "report.json").read_text())

        self.assertEqual(report["summary"]["pages_scanned"], 1, report["errors"])
        self.assertEqual(saved["findings"][0]["pattern_id"], "DP01")
        self.assertEqual(saved["findings"][0]["status"], "POTENTIAL")
        self.assertIn(saved["findings"][0]["severity"], {"LOW", "MEDIUM", "HIGH"})
        self.assertGreater(saved["findings"][0]["confidence"], 0)
        self.assertTrue(saved["findings"][0]["customer_harm"])
        self.assertEqual(len(callbacks), 2)
        self.assertEqual(callbacks[0][1:], (1, 2))
        self.assertEqual(callbacks[1][1:], (2, 2))
        self.assertEqual(callbacks[1][0]["interaction"], "isolated_cart")
        self.assertEqual(len(saved["categories"]), 13)
        self.assertEqual(saved["summary"]["rogue_malware_status"], "EXCLUDED_BY_SCOPE")


if __name__ == "__main__":
    unittest.main()
