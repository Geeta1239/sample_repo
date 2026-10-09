import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401
from scripts.flipkart_challenge_one import CATEGORY_DEFINITIONS, DEFAULT_URLS, detect_category_matches, scan, slug


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
            "Only few left. Sponsored. Most popular. Platform fee. Free trial renews monthly. "
            "Remind me later. No, I don't want to save money. Login to continue."
        )
        matches = detect_category_matches(text)
        self.assertTrue(matches["DP01"])
        self.assertTrue(matches["DP03"])
        self.assertTrue(matches["DP04"])
        self.assertTrue(matches["DP05"])
        self.assertTrue(matches["DP06"])
        self.assertTrue(matches["DP08"])
        self.assertTrue(matches["DP09"])
        self.assertTrue(matches["DP10"])
        self.assertTrue(matches["DP12"])
        self.assertEqual(matches["DP13"], [])

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

        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.flipkart_challenge_one.sync_playwright"
        ) as sync_playwright:
            sync_playwright.return_value.__enter__.return_value = FakePlaywright()
            report = scan([DEFAULT_URLS[0]], Path(directory))
            saved = json.loads((Path(directory) / "report.json").read_text())

        self.assertEqual(report["summary"]["pages_scanned"], 1, report["errors"])
        self.assertEqual(saved["findings"][0]["pattern_id"], "DP01")
        self.assertEqual(saved["findings"][0]["status"], "POTENTIAL")
        self.assertEqual(len(saved["categories"]), 13)
        self.assertEqual(saved["summary"]["rogue_malware_status"], "EXCLUDED_BY_SCOPE")


if __name__ == "__main__":
    unittest.main()
