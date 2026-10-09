"""Read-only Flipkart Challenge One inspection across all 13 categories.

The scanner visits public pages only, records visible text/HTML/screenshots, and
returns conservative candidates for the repository's 13-category atlas. It does
not log in, submit forms, change delivery settings, add products to a cart, or
enter personal data. Results are review candidates, not legal conclusions.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

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

# Exact order and labels from prototype/src/main.jsx's 13-category guideline atlas.
CATEGORY_DEFINITIONS = [
    ("DP01", "False Urgency", "Pressure"),
    ("DP02", "Basket Sneaking", "Consent"),
    ("DP03", "Confirm Shaming", "Language"),
    ("DP04", "Forced Action", "Commitment"),
    ("DP05", "Subscription Trap", "Commitment"),
    ("DP06", "Interface Interference", "Choice"),
    ("DP07", "Bait and Switch", "Expectation"),
    ("DP08", "Drip Pricing", "Transparency"),
    ("DP09", "Disguised Advertisement", "Persuasion"),
    ("DP10", "Nagging", "Persistence"),
    ("DP11", "Trick Question", "Clarity"),
    ("DP12", "SaaS Billing", "Recurring billing"),
    ("DP13", "Rogue Malware", "Safety boundary"),
]
CATEGORY_BY_ID = {item[0]: item for item in CATEGORY_DEFINITIONS}


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
    executable = os.environ.get("SHADOWBAIT_CHROMIUM_PATH")
    options = {"executable_path": executable} if executable else {}
    return playwright.chromium.launch(**options)


def _regex_matches(text: str, patterns: list[str]) -> list[str]:
    """Return short source snippets for matching patterns, preserving evidence text."""
    results: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 70)
            end = min(len(text), match.end() + 90)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            if snippet and snippet not in results:
                results.append(snippet)
    return results[:8]


def _false_urgency(text: str) -> list[str]:
    return [match.evidence_text for match in detect_false_urgency(segment_text(text))]


def detect_category_matches(visible_text: str, html: str = "") -> dict[str, list[str]]:
    """Apply transparent, conservative heuristics to all 13 categories.

    The output is intentionally evidence-first: each value is source text that
    triggered a candidate. Categories without a trigger are still represented
    in the final report as NOT_OBSERVED.
    """
    text = f"{visible_text}\n{html}"
    matches: dict[str, list[str]] = {category_id: [] for category_id, _, _ in CATEGORY_DEFINITIONS}
    matches["DP01"] = _false_urgency(visible_text)
    matches["DP02"] = _regex_matches(
        text,
        [r"checked[^>]{0,180}(?:donation|contribution|add[- ]?on|insurance|protection)",
         r"(?:donation|contribution|add[- ]?on|insurance|protection)[^<]{0,120}checked",
         r"optional[^\n]{0,100}(?:added|included|selected)"])
    matches["DP03"] = _regex_matches(
        visible_text,
        [r"(?:no|yes),?\s+i\s+(?:don't|do not|can't|cannot|won't|will not)",
         r"(?:refuse|decline|skip)[^\n]{0,80}(?:save|benefit|smart|miss)"])
    matches["DP04"] = _regex_matches(
        visible_text,
        [r"(?:must|required|mandatory)\s+(?:login|log in|sign in|create an account|register)",
         r"(?:login|log in|sign in)\s+to\s+(?:continue|view|buy|see|access)",
         r"(?:verify|enter)\s+(?:phone|email)\s+to\s+(?:continue|view|buy)"])
    matches["DP05"] = _regex_matches(
        visible_text,
        [r"free\s+(?:trial|membership|delivery)[^\n]{0,100}(?:renew|cancel|billing)",
         r"(?:auto(?:matic)?[- ]?renew|recurring|renewal)[^\n]{0,100}(?:subscription|membership|trial)",
         r"cancel(?:lation)?\s+(?:is|made|available|only)"])
    matches["DP06"] = _regex_matches(
        visible_text,
        [r"(?:most popular|recommended|best value|top pick|assured)",
         r"(?:continue without|skip|not now)[^\n]{0,100}(?:membership|offer|protection)"])
    matches["DP07"] = _regex_matches(
        visible_text,
        [r"(?:unavailable|out of stock|no longer available)[^\n]{0,100}(?:upgrade|instead|similar)",
         r"(?:advertised|selected|displayed)\s+(?:price|offer)[^\n]{0,100}(?:changed|different|upgrade)"])
    matches["DP08"] = _regex_matches(
        visible_text,
        [r"(?:platform|handling|convenience|service)\s+fee",
         r"(?:delivery|shipping)\s+(?:fee|charge)[^\n]{0,100}(?:total|checkout)",
         r"additional\s+(?:charges?|fees?)"])
    matches["DP09"] = _regex_matches(
        visible_text,
        [r"\bsponsored\b", r"\badvertisement\b", r"\bpromoted\b"])
    matches["DP10"] = _regex_matches(
        visible_text,
        [r"(?:remind me later|enable notifications|turn on notifications)",
         r"(?:don't miss|never miss)[^\n]{0,100}(?:update|alert|notification|offer)"])
    matches["DP11"] = _regex_matches(
        visible_text,
        [r"(?:no,?\s+i\s+don't|do not not|without not|not unsubscribe)",
         r"(?:learn more|continue)\s*(?:>|→)?\s*(?:agree|accept|subscribe)"])
    matches["DP12"] = _regex_matches(
        visible_text,
        [r"(?:per\s+month|per\s+year|monthly|annual|yearly)\b",
         r"(?:subscription|membership)\s+(?:plan|billing|price)",
         r"(?:auto(?:matic)?[- ]?renew|recurring)\s+(?:payment|charge|billing)"])
    # DP13 is an explicit safety boundary. The scanner never probes or creates
    # malware behavior; therefore it is always reported as EXCLUDED_BY_SCOPE.
    return {key: list(dict.fromkeys(value)) for key, value in matches.items()}


def build_category_results(matches: dict[str, list[str]], page_url: str, screenshot: str, dom_text: str) -> list[dict[str, Any]]:
    results = []
    for category_id, name, family in CATEGORY_DEFINITIONS:
        evidence = matches.get(category_id, [])
        if category_id == "DP13":
            status = "EXCLUDED_BY_SCOPE"
            interpretation = "This safe scanner does not create, probe, or execute malware behavior."
        else:
            status = "POTENTIAL" if evidence else "NOT_OBSERVED"
            interpretation = (
                "Heuristic candidate requiring human review; not a legal conclusion."
                if evidence else "No matching signal was observed in the captured public page text."
            )
        results.append({
            "pattern_id": category_id,
            "pattern_name": name,
            "family": family,
            "status": status,
            "page_url": page_url,
            "evidence_text": evidence,
            "screenshot": screenshot,
            "dom_text": dom_text,
            "interpretation": interpretation,
        })
    return results


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
            "taxonomy": "13-category guideline atlas",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pages_requested": len(urls),
            "browser": "Chromium",
        },
        "categories": [
            {"pattern_id": category_id, "pattern_name": name, "family": family}
            for category_id, name, family in CATEGORY_DEFINITIONS
        ],
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
                    pass
                visible_text = page.locator("body").inner_text(timeout=timeout_ms)
                html = page.content()
                name = f"{index:02d}-{slug(page.url)}"
                screenshot_path = screenshots / f"{name}.png"
                html_path = dom / f"{name}.html"
                text_path = dom / f"{name}-text.json"
                page.screenshot(path=str(screenshot_path), full_page=True)
                html_path.write_text(html, encoding="utf-8")
                write_json(text_path, {"url": page.url, "title": page.title(), "visible_text": visible_text})
                matches = detect_category_matches(visible_text, html)
                category_results = build_category_results(
                    matches, page.url, artifact_path(screenshot_path), artifact_path(text_path)
                )
                page_record.update({
                    "url_final": page.url,
                    "title": page.title(),
                    "visible_text_characters": len(visible_text),
                    "screenshot": artifact_path(screenshot_path),
                    "dom_html": artifact_path(html_path),
                    "dom_text": artifact_path(text_path),
                    "category_results": category_results,
                })
                report["pages"].append(page_record)
                report["findings"].extend(
                    result for result in category_results if result["status"] == "POTENTIAL"
                )
            except Exception as exc:  # keep the multi-page scan useful if one page fails
                page_record["error"] = f"{type(exc).__name__}: {exc}"
                report["errors"].append(page_record)
        context.close()
        browser.close()

    potential_by_category = {
        category_id: sum(
            1 for finding in report["findings"] if finding["pattern_id"] == category_id
        )
        for category_id, _, _ in CATEGORY_DEFINITIONS
    }
    observed_category_ids = [key for key, value in potential_by_category.items() if value]
    report["scan"].update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pages_scanned": len(report["pages"]),
        "errors": len(report["errors"]),
    })
    report["summary"] = {
        "pages_scanned": len(report["pages"]),
        "pages_requested": len(urls),
        "taxonomy_categories": len(CATEGORY_DEFINITIONS),
        "potential_matches": len(report["findings"]),
        "potential_matches_by_category": potential_by_category,
        "categories_with_potential_matches": observed_category_ids,
        "categories_not_observed": [
            category_id for category_id, _, _ in CATEGORY_DEFINITIONS
            if category_id not in observed_category_ids and category_id != "DP13"
        ],
        "rogue_malware_status": "EXCLUDED_BY_SCOPE",
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
