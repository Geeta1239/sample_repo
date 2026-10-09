"""Read-only Flipkart Challenge One inspection.

The scanner visits public pages only, records visible text/HTML/screenshots, and
runs the existing False Urgency detector. It does not log in, submit forms,
change delivery settings, add products to a cart, or enter personal data.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
from app.detection.urgency_detector import detect_false_urgency  # noqa: E402
from app.nlp.preprocessing import segment_text  # noqa: E402

DEFAULT_URLS = [
    "https://www.flipkart.com/",
    "https://www.flipkart.com/search?q=headphones",
    "https://www.flipkart.com/mobile-phones-store",
    "https://www.flipkart.com/clothing-and-accessories/pr?sid=clo",
    "https://www.flipkart.com/electronics",
    "https://www.flipkart.com/search?q=iphone",
]


def slug(url: str) -> str:
    value = re.sub(r"^https?://", "", url)
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:120] or "page"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def artifact_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def launch_browser(playwright):
    executable = __import__("os").environ.get("SHADOWBAIT_CHROMIUM_PATH")
    options = {"executable_path": executable} if executable else {}
    return playwright.chromium.launch(**options)


def scan(urls: list[str], output_root: Path, timeout_ms: int = 45_000) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    screenshots = output_root / "screenshots"
    dom = output_root / "dom"
    screenshots.mkdir(exist_ok=True)
    dom.mkdir(exist_ok=True)
    report: dict[str, Any] = {
        "scan": {
            "target": "https://www.flipkart.com",
            "mode": "read-only public inspection",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pages_requested": len(urls),
            "browser": "Chromium",
        },
        "pages": [],
        "findings": [],
        "errors": [],
    }

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        for index, url in enumerate(urls, start=1):
            page_record: dict[str, Any] = {"url_requested": url, "index": index}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except PlaywrightTimeoutError:
                    # Dynamic storefronts can keep connections open; DOM content is enough.
                    pass
                visible_text = page.locator("body").inner_text(timeout=timeout_ms)
                name = f"{index:02d}-{slug(page.url)}"
                screenshot_path = screenshots / f"{name}.png"
                html_path = dom / f"{name}.html"
                text_path = dom / f"{name}-text.json"
                page.screenshot(path=str(screenshot_path), full_page=True)
                html_path.write_text(page.content(), encoding="utf-8")
                write_json(text_path, {"url": page.url, "title": page.title(), "visible_text": visible_text})

                matches = detect_false_urgency(segment_text(visible_text))
                page_record.update(
                    {
                        "url_final": page.url,
                        "title": page.title(),
                        "visible_text_characters": len(visible_text),
                        "screenshot": artifact_path(screenshot_path),
                        "dom_html": artifact_path(html_path),
                        "dom_text": artifact_path(text_path),
                        "detected_false_urgency": [
                            {
                                "evidence_text": match.evidence_text,
                                "categories": match.categories,
                                "rule_confidence": match.rule_confidence,
                            }
                            for match in matches
                        ],
                    }
                )
                report["pages"].append(page_record)
                for match in matches:
                    report["findings"].append(
                        {
                            "pattern_id": "DP01",
                            "pattern_name": "False Urgency",
                            "status": "POTENTIAL",
                            "page_url": page.url,
                            "evidence_text": match.evidence_text,
                            "categories": match.categories,
                            "rule_confidence": match.rule_confidence,
                            "screenshot": artifact_path(screenshot_path),
                            "dom_text": artifact_path(text_path),
                            "interpretation": "A detector candidate requiring human review; not a legal conclusion.",
                            "ethical_recommendation": "Show truthful stock and fixed, clearly stated offer end times.",
                        }
                    )
            except Exception as exc:  # keep the six-page scan useful if one page fails
                page_record["error"] = f"{type(exc).__name__}: {exc}"
                report["errors"].append(page_record)

        context.close()
        browser.close()

    report["scan"].update(
        {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "pages_scanned": len(report["pages"]),
            "errors": len(report["errors"]),
        }
    )
    report["summary"] = {
        "pages_scanned": len(report["pages"]),
        "pages_requested": len(urls),
        "potential_false_urgency_findings": len(report["findings"]),
        "errors": len(report["errors"]),
    }
    write_json(output_root / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "evidence/live-scans/flipkart-challenge-one")
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--url", action="append", dest="urls", help="Override the default public URL list; repeatable.")
    args = parser.parse_args()
    report = scan(args.urls or DEFAULT_URLS, args.output.resolve(), args.timeout_ms)
    print(json.dumps(report["summary"], indent=2))
    print(f"report={args.output.resolve() / 'report.json'}")
    return 0 if report["pages"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
