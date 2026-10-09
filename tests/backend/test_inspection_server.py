import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import _bootstrap  # noqa: F401
from app.database import repository

with patch.object(repository, "ScanDatabase", return_value=MagicMock()):
    from backend import inspection_server
from scripts.flipkart_challenge_one import DEFAULT_URLS


class TestFlipkartDashboardScan(unittest.TestCase):
    def test_homepage_scans_the_default_six_page_sample(self):
        target = "https://www.flipkart.com"
        events = []

        def fake_scan(urls, _output_root, on_page):
            self.assertEqual(urls, DEFAULT_URLS)
            pages = []
            for index, url in enumerate(urls, start=1):
                page = {
                    "url_requested": url,
                    "url_final": url,
                    "title": f"Flipkart page {index}",
                    "category_results": [],
                }
                pages.append(page)
                on_page(page, index, len(urls))
            return {
                "scan": {"started_at": "2026-10-09T00:00:00+00:00"},
                "categories": [],
                "pages": pages,
                "summary": {"pages_scanned": len(pages)},
            }

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(inspection_server, "LIVE_ROOT", Path(directory)), \
             patch.object(inspection_server, "scan_flipkart", side_effect=fake_scan), \
             patch.object(inspection_server, "STORE", MagicMock()), \
             patch.object(inspection_server, "DATABASE", MagicMock()):
            handler = object.__new__(inspection_server.Handler)
            report = handler.run_flipkart_scan(
                target,
                emit=lambda event, payload: events.append((event, payload)),
            )

        self.assertEqual(len(report["pages"]), 6)
        self.assertEqual(report["scan"]["target"], target)
        started = next(payload for event, payload in events if event == "started")
        completed = next(payload for event, payload in events if event == "complete")
        self.assertEqual(started["total"], 7)
        self.assertEqual(completed["total"], 7)
        self.assertEqual(completed["completed"], 7)

    def test_generic_scanner_redirects_flipkart_to_flipkart_scanner(self):
        target = "https://www.flipkart.com"
        handler = object.__new__(inspection_server.Handler)
        handler.run_flipkart_scan = MagicMock(return_value={"scan": {"target": target}})

        with patch.object(inspection_server, "validate_public_target"):
            result = handler.run_scan(target)

        self.assertEqual(result["scan"]["target"], target)
        handler.run_flipkart_scan.assert_called_once_with(target, emit=None)

    def test_generic_scanner_routes_public_target_to_single_page_inspector(self):
        target = "https://example.com/products"
        handler = object.__new__(inspection_server.Handler)
        handler.run_public_page_scan = MagicMock(return_value={"scan": {"target": target}})

        with patch.object(inspection_server, "validate_public_target"):
            result = handler.run_scan(target)

        self.assertEqual(result["scan"]["target"], target)
        handler.run_public_page_scan.assert_called_once_with(target, emit=None, scan_id=None)

    def test_public_target_validation_allows_demo_and_rejects_private_addresses(self):
        self.assertTrue(inspection_server.validate_public_target("http://127.0.0.1:3000"))
        self.assertTrue(inspection_server.validate_public_target("http://localhost:3001"))
        with self.assertRaisesRegex(ValueError, "standard HTTP/HTTPS ports"):
            inspection_server.validate_public_target("http://localhost:3002")
        with patch.object(
            inspection_server.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.5", 443))],
        ):
            with self.assertRaisesRegex(ValueError, "Private, local"):
                inspection_server.validate_public_target("https://internal.example")

    def test_public_page_scan_builds_evidence_classification_risk_and_mapping(self):
        target = "https://example.com/products"
        page = MagicMock()
        page.url = target
        page.title.return_value = "Example products"
        response = MagicMock()
        response.status = 200
        page.goto.return_value = response
        page.locator.return_value.inner_text.return_value = "Only few left"
        page.content.return_value = "<html><body>Only few left</body></html>"
        page.screenshot.return_value = b"fake-png"
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright_context = MagicMock()
        playwright_context.__enter__.return_value = playwright
        store = MagicMock()
        store.get.return_value = None
        database = MagicMock()

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(inspection_server, "LIVE_ROOT", Path(directory)), \
             patch.object(inspection_server, "validate_public_target"), \
             patch.object(inspection_server, "detect_category_matches", return_value={
                 category_id: (["Only few left"] if category_id == "DP01" else [])
                 for category_id, _, _ in inspection_server.CATEGORY_DEFINITIONS
             }), \
             patch.object(inspection_server, "sync_playwright", return_value=playwright_context), \
             patch.object(inspection_server, "launch_browser", return_value=browser), \
             patch.object(inspection_server, "STORE", store), \
             patch.object(inspection_server, "DATABASE", database):
            handler = object.__new__(inspection_server.Handler)
            report = handler.run_public_page_scan(target)

        self.assertEqual(report["scan"]["mode"], "Generic public single-page inspection")
        self.assertEqual(report["scan"]["inspection_status"], "INSPECTED")
        self.assertEqual(len(report["pages"]), 1)
        self.assertEqual(report["summary"]["captured_findings"], 1)
        self.assertEqual(report["summary"]["verified_findings"], 0)
        finding = report["findings"][0]
        self.assertEqual(finding["name"], "False Urgency")
        self.assertEqual(finding["m2_findings"][0]["status"], "CANDIDATE")
        self.assertGreater(report["risk"]["risk_score"], 0)
        self.assertEqual(
            finding["compliance"]["source"],
            "Generic public-page 13-category heuristic mapping",
        )
        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_empty_public_page_is_reported_without_claiming_no_patterns(self):
        target = "https://www.amazon.in/"
        page = MagicMock()
        page.url = target
        page.title.return_value = ""
        response = MagicMock()
        response.status = 202
        page.goto.return_value = response
        page.locator.return_value.inner_text.return_value = ""
        page.content.return_value = "<html><body></body></html>"
        page.screenshot.return_value = b"fake-png"
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.new_context.return_value = context
        playwright_context = MagicMock()
        playwright_context.__enter__.return_value = MagicMock()
        store = MagicMock()
        store.get.return_value = None
        events = []

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(inspection_server, "LIVE_ROOT", Path(directory)), \
             patch.object(inspection_server, "validate_public_target"), \
             patch.object(inspection_server, "detect_category_matches") as detect, \
             patch.object(inspection_server, "sync_playwright", return_value=playwright_context), \
             patch.object(inspection_server, "launch_browser", return_value=browser), \
             patch.object(inspection_server, "STORE", store), \
             patch.object(inspection_server, "DATABASE", MagicMock()):
            handler = object.__new__(inspection_server.Handler)
            report = handler.run_public_page_scan(
                target,
                emit=lambda event, payload: events.append((event, payload)),
            )

        detect.assert_not_called()
        self.assertEqual(report["scan"]["inspection_status"], "NO_CONTENT")
        self.assertEqual(report["scan"]["http_status"], 202)
        self.assertEqual(report["pages"][0]["status"], "NO_CONTENT")
        self.assertEqual(report["summary"]["categories_assessed"], 0)
        self.assertEqual(report["summary"]["captured_findings"], 0)
        self.assertIn("no visible page content", report["scan"]["message"])
        complete = next(payload for event, payload in events if event == "complete")
        self.assertIn("HTTP 202", complete["message"])

    def test_flipkart_candidates_get_language_classification_risk_and_heuristic_mapping(self):
        target = "https://www.flipkart.com/search?q=headphones"
        category_result = {
            "pattern_id": "DP01",
            "pattern_name": "False Urgency",
            "status": "POTENTIAL",
            "page_url": target,
            "evidence_text": ["Only few left"],
            "screenshot": "missing-screenshot.png",
        }
        page = {
            "url_requested": target,
            "url_final": target,
            "title": "Headphones",
            "category_results": [category_result],
        }

        def fake_scan(urls, _output_root, on_page):
            self.assertEqual(urls, [target])
            on_page(page, 1, 2)
            return {
                "scan": {"started_at": "2026-10-09T00:00:00+00:00"},
                "categories": [],
                "pages": [page],
                "findings": [category_result],
                "cart_interaction": {"status": "SKIPPED"},
                "summary": {"pages_scanned": 1},
            }

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(inspection_server, "LIVE_ROOT", Path(directory)), \
             patch.object(inspection_server, "scan_flipkart", side_effect=fake_scan), \
             patch.object(inspection_server, "STORE", MagicMock()), \
             patch.object(inspection_server, "DATABASE", MagicMock()):
            handler = object.__new__(inspection_server.Handler)
            report = handler.run_flipkart_scan(target)

        finding = report["findings"][0]
        self.assertEqual(finding["m2_status"], "CLASSIFIED")
        self.assertEqual(finding["m2_findings"][0]["name"], "False Urgency")
        self.assertEqual(finding["m2_findings"][0]["status"], "CANDIDATE")
        self.assertEqual(report["risk"]["risk_score"], 0.95)
        self.assertEqual(report["summary"]["m2_classified_findings"], 1)
        self.assertEqual(report["summary"]["m2_verified_findings"], 0)
        self.assertEqual(report["compliance"]["mapped_findings"], 1)
        self.assertEqual(finding["compliance"]["category"], "False Urgency")
        self.assertEqual(finding["compliance"]["status"], "CANDIDATE")

    def test_scans_the_exact_flipkart_url_entered_in_dashboard(self):
        target = "https://www.flipkart.com/example-product/p/itm123?pid=ABC123"
        events = []

        def fake_scan(urls, _output_root, on_page):
            self.assertEqual(urls, [target])
            page = {
                "url_requested": target,
                "url_final": target,
                "title": "Example product",
                "category_results": [],
            }
            on_page(page, 1, len(urls))
            return {
                "scan": {"started_at": "2026-10-09T00:00:00+00:00"},
                "categories": [],
                "pages": [page],
                "summary": {"pages_scanned": 1},
            }

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(inspection_server, "LIVE_ROOT", Path(directory)), \
             patch.object(inspection_server, "scan_flipkart", side_effect=fake_scan), \
             patch.object(inspection_server, "STORE", MagicMock()), \
             patch.object(inspection_server, "DATABASE", MagicMock()):
            handler = object.__new__(inspection_server.Handler)
            report = handler.run_flipkart_scan(
                target,
                emit=lambda event, payload: events.append((event, payload)),
            )

        self.assertEqual(report["scan"]["target"], target)
        started = next(payload for event, payload in events if event == "started")
        completed = next(payload for event, payload in events if event == "complete")
        self.assertEqual(started["total"], 2)
        self.assertEqual(completed["total"], 2)
        self.assertEqual(completed["completed"], 2)


if __name__ == "__main__":
    unittest.main()
