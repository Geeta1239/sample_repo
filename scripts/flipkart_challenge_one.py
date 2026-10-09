"""Read-only Flipkart Challenge One inspection across all 13 categories.

The scanner visits public pages only, records visible text/HTML/screenshots, and
returns conservative candidates for the repository's 13-category atlas. It does
not log in, submit forms, change delivery settings, add products to a cart, or
enter personal data. Results are review candidates, not legal conclusions.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

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
CATEGORY_SEVERITY = {
    "DP01": "MEDIUM", "DP02": "HIGH", "DP03": "MEDIUM", "DP04": "HIGH",
    "DP05": "HIGH", "DP06": "MEDIUM", "DP07": "HIGH", "DP08": "HIGH",
    "DP09": "LOW", "DP10": "LOW", "DP11": "MEDIUM", "DP12": "HIGH", "DP13": "EXCLUDED",
}
CATEGORY_HARM = {
    "DP01": "May rush a customer into a decision before they can compare options or verify the claim.",
    "DP02": "May add an optional cost or commitment without a clear affirmative choice.",
    "DP03": "May use guilt or embarrassment to steer a customer toward an optional action.",
    "DP04": "May make an unrelated action a condition of access, purchase, or continuation.",
    "DP05": "May make recurring commitment easier to start than to stop.",
    "DP06": "May obscure a lower-commitment choice through visual hierarchy or interaction design.",
    "DP07": "May redirect a customer from an advertised outcome to a different or more expensive one.",
    "DP08": "May delay the complete payable price until late in the decision journey.",
    "DP09": "May make commercial persuasion look like independent information.",
    "DP10": "May repeatedly interrupt or pressure a customer after they decline a prompt.",
    "DP11": "May make the consequence of a choice difficult for a reasonable customer to understand.",
    "DP12": "May obscure renewal, recurring billing, or the path to control an ongoing charge.",
    "DP13": "Excluded by the safe scanning boundary; no malicious behavior is created or tested.",
}


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


def _preselected_addons(html: str) -> list[str]:
    evidence: list[str] = []
    addon_terms = re.compile(
        r"\b(?:donation|contribution|insurance|protection|extended warranty|gift wrap|add[- ]?on)\b",
        re.IGNORECASE,
    )
    checked_input = re.compile(
        r"<input\b(?=[^>]*\btype\s*=\s*['\"]?checkbox\b)"
        r"(?=[^>]*\bchecked(?:\s|=|/?>))[^>]*>",
        re.IGNORECASE,
    )
    for match in checked_input.finditer(html):
        input_tag = match.group(0)
        input_id = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", input_tag, re.IGNORECASE)
        if input_id:
            label = re.search(
                rf"<label\b(?=[^>]*\bfor\s*=\s*['\"]{re.escape(input_id.group(1))}['\"])[^>]*>"
                rf"(.*?)</label>",
                html,
                re.IGNORECASE | re.DOTALL,
            )
        else:
            label = None
        label_text = ""
        if label:
            label_text = html_lib.unescape(re.sub(r"<[^>]+>", " ", label.group(1)))
            label_text = re.sub(r"\s+", " ", label_text).strip()
        if label_text and addon_terms.search(label_text):
            evidence.append(f"Preselected checkbox: {label_text}")
    return evidence


def detect_category_matches(visible_text: str, html: str = "") -> dict[str, list[str]]:
    """Apply transparent, conservative heuristics to all 13 categories.

    The output is intentionally evidence-first: each value is source text that
    triggered a candidate. Categories without a trigger are still represented
    in the final report as NOT_OBSERVED.
    """
    matches: dict[str, list[str]] = {category_id: [] for category_id, _, _ in CATEGORY_DEFINITIONS}
    matches["DP01"] = _false_urgency(visible_text)
    matches["DP02"] = _preselected_addons(html)
    matches["DP03"] = _regex_matches(
        visible_text,
        [r"(?:no|yes),?\s+i\s+(?:don't|do not|can't|cannot|won't|will not)",
         r"(?:refuse|decline|skip)[^\n]{0,80}(?:save|benefit|smart|miss)",
         r"(?:don't|do not)\s+want\s+to\s+(?:save|keep|enjoy)[^\n]{0,60}(?:money|benefit|offer)"])
    matches["DP04"] = _regex_matches(
        visible_text,
        [r"(?:must|required|mandatory)\s+(?:login|log in|sign in|create an account|register)",
         r"(?:login|log in|sign in)\s+to\s+(?:continue|view|buy|see|access)",
         r"(?:verify|enter)\s+(?:phone|email)\s+to\s+(?:continue|view|buy)",
         r"(?:please\s+)?(?:login|log in|sign in)\s+(?:or|to)\s+(?:continue|proceed|checkout)"])
    matches["DP05"] = _regex_matches(
        visible_text,
        [r"free\s+(?:trial|membership|delivery)[^\n]{0,100}(?:renew|cancel|billing)",
         r"(?:auto(?:matic)?[- ]?renew|recurring|renewal)[^\n]{0,100}(?:subscription|membership|trial)",
         r"cancel(?:lation)?\s+(?:is|made|available|only)",
         r"(?:trial|membership|subscription)[^\n]{0,100}(?:charged|charge|billed|billing)\s+(?:automatically|after)"])
    matches["DP06"] = _regex_matches(
        visible_text,
        [r"(?:recommended|best value|top pick)[^\n]{0,100}(?:selected by default|preselected)",
         r"(?:continue without|skip|not now)[^\n]{0,100}(?:membership|offer|protection)"])
    matches["DP07"] = _regex_matches(
        visible_text,
        [r"(?:unavailable|out of stock|no longer available)[^\n]{0,100}(?:upgrade|instead|similar)",
         r"(?:advertised|selected|displayed)\s+(?:price|offer)[^\n]{0,100}(?:changed|different|upgrade)"])
    matches["DP08"] = _regex_matches(
        visible_text,
        [r"(?:₹|rs\.?)\s*\d[\d,.]*\s+(?:platform|handling|convenience|service)\s+fee[^\n]{0,100}(?:added|at checkout|additional)",
         r"(?:delivery|shipping)\s+(?:fee|charge|charges?)[^\n]{0,100}(?:added|at checkout|additional)",
         r"additional\s+(?:charges?|fees?)[^\n]{0,100}(?:checkout|order total|payable)",
         r"(?:fee|charge)\s*(?:of|:|[-–])\s*(?:₹|rs\.?)\s*\d[\d,.]*[^\n]{0,100}(?:added|at checkout|additional)"])
    # A visible "Sponsored" or "Advertisement" disclosure is not evidence that
    # an ad is disguised; this text-only scanner cannot compare visual styling.
    matches["DP09"] = []
    matches["DP10"] = _regex_matches(
        visible_text,
        [r"(?:asked|shown|prompted)\s+again[^\n]{0,100}(?:dismiss|declin|later|not now)",
         r"(?:don't miss|never miss)[^\n]{0,100}(?:update|alert|notification|offer)[^\n]{0,100}(?:again|repeated)"])
    matches["DP11"] = _regex_matches(
        visible_text,
        [r"(?:no,?\s+i\s+don't|do not not|without not|not unsubscribe)",
         r"(?:learn more|continue)\s*(?:>|→)?\s*(?:agree|accept|subscribe)"])
    matches["DP12"] = _regex_matches(
        visible_text,
        [r"(?:per\s+month|per\s+year)\b",
         r"(?:subscription|membership)\s+(?:plan|billing|price)",
         r"(?:auto(?:matic)?[- ]?renew|recurring)\s+(?:payment|charge|billing)",
         r"(?:monthly|annual|yearly)\s+(?:subscription|membership|billing|plan)",
         r"(?:subscription|membership)[^\n]{0,40}(?:billed|charged)\s+(?:monthly|annually|yearly)"])
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
            "severity": CATEGORY_SEVERITY[category_id],
            "confidence": round(min(0.98, 0.55 + (0.1 * min(len(evidence), 4))), 2) if evidence else 0.0,
            "customer_harm": CATEGORY_HARM[category_id],
            "recommendation": "Make the choice, price, and consequence clear, neutral, and easy to review.",
        })
    return results


def inspect_isolated_cart(
    page,
    output_root: Path,
    index: int,
    total: int,
    timeout_ms: int,
    on_page: Callable[[dict[str, Any], int, int], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    interaction: dict[str, Any] = {
        "status": "SKIPPED",
        "message": "No public product could be selected for the isolated cart check.",
        "checkout_submitted": False,
    }
    page_record: dict[str, Any] = {
        "url_requested": "Flipkart isolated cart check",
        "index": index,
        "interaction": "isolated_cart",
    }
    cart_record = None
    try:
        current_url = urlparse(page.url)
        if "/p/" in current_url.path:
            candidate_urls = [page.url]
        else:
            product_links = page.locator('a[href*="/p/"]')
            if product_links.count() == 0:
                page_record["status"] = "SKIPPED"
                page_record["message"] = interaction["message"]
                return interaction, cart_record
            candidate_urls = []
            for link_index in range(min(product_links.count(), 8)):
                href = product_links.nth(link_index).get_attribute("href") or ""
                candidate_url = urljoin(page.url, href)
                parsed_candidate = urlparse(candidate_url)
                if (
                    parsed_candidate.scheme == "https"
                    and (parsed_candidate.hostname or "").endswith(".flipkart.com")
                    and candidate_url not in candidate_urls
                ):
                    candidate_urls.append(candidate_url)

        product_url = ""
        add_to_cart = None
        for candidate_url in candidate_urls:
            page.goto(candidate_url, wait_until="domcontentloaded", timeout=timeout_ms)
            product_text = page.locator("body").inner_text(timeout=timeout_ms)
            if re.search(r"\b(?:out of stock|currently unavailable|sold out)\b", product_text, re.IGNORECASE):
                continue
            candidate_action = page.get_by_text("Add to cart", exact=True).first
            if candidate_action.count() > 0:
                product_url = candidate_url
                add_to_cart = candidate_action
                break

        if add_to_cart is None:
            interaction["message"] = (
                "No sampled public product was both available and exposed an Add to cart action."
            )
            page_record.update({"status": "SKIPPED", "message": interaction["message"]})
            return interaction, cart_record

        interaction["product_url"] = product_url
        add_to_cart.click(timeout=min(timeout_ms, 10_000))
        interaction["add_action_clicked"] = True
        cart_url = "https://www.flipkart.com/viewcart"
        page.goto(cart_url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except PlaywrightTimeoutError:
            pass

        visible_text = page.locator("body").inner_text(timeout=timeout_ms)
        html = page.content()
        name = f"{index:02d}-isolated-cart"
        screenshot_path = output_root / "screenshots" / f"{name}.png"
        html_path = output_root / "dom" / f"{name}.html"
        text_path = output_root / "dom" / f"{name}-text.json"
        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(html, encoding="utf-8")
        write_json(text_path, {"url": page.url, "title": page.title(), "visible_text": visible_text})
        matches = detect_category_matches(visible_text, html)
        category_results = build_category_results(
            matches, page.url, artifact_path(screenshot_path), artifact_path(text_path)
        )
        cart_empty = bool(re.search(
            r"(?:missing cart items|your cart is empty|cart is empty)",
            visible_text,
            re.IGNORECASE,
        ))
        page_record.update({
            "url_final": page.url,
            "title": page.title(),
            "visible_text_characters": len(visible_text),
            "screenshot": artifact_path(screenshot_path),
            "dom_html": artifact_path(html_path),
            "dom_text": artifact_path(text_path),
            "category_results": category_results,
        })
        cart_record = page_record
        interaction.update({
            "status": "EMPTY" if cart_empty else "INSPECTED",
            "cart_url": page.url,
            "message": (
                "The cart remained empty, so no cart-level controls were available to inspect."
                if cart_empty
                else "Inspected the isolated cart; checkout and payment were not submitted."
            ),
        })
        page_record["status"] = interaction["status"]

        remove_action = page.get_by_text("Remove", exact=True).first
        if not cart_empty and remove_action.count() > 0:
            remove_action.click(timeout=min(timeout_ms, 10_000))
            interaction["remove_action_clicked"] = True
        else:
            interaction["remove_action_clicked"] = False
            if not cart_empty:
                interaction["status"] = "REMOVE_UNAVAILABLE"
                page_record["status"] = interaction["status"]
                interaction["message"] = (
                    "A cart state was captured, but no Remove action was available. "
                    "The temporary browser context will be discarded."
                )
    except Exception as exc:
        interaction.update({"status": "ERROR", "message": f"{type(exc).__name__}: {exc}"})
        page_record.update({"status": "ERROR", "error": interaction["message"]})
    finally:
        if on_page:
            on_page(page_record, index, total)
    return interaction, cart_record


def scan(urls: list[str], output_root: Path, timeout_ms: int = 45_000, on_page: Callable[[dict[str, Any], int, int], None] | None = None) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    screenshots = output_root / "screenshots"
    dom = output_root / "dom"
    screenshots.mkdir(exist_ok=True)
    dom.mkdir(exist_ok=True)
    report: dict[str, Any] = {
        "scan": {
            "target": "https://www.flipkart.com",
            "mode": "public-page inspection with isolated cart check",
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
            if on_page:
                on_page(page_record, index, len(urls) + 1)

        cart_interaction, cart_record = inspect_isolated_cart(
            page, output_root, len(urls) + 1, len(urls) + 1, timeout_ms, on_page
        )
        report["cart_interaction"] = cart_interaction
        if cart_record is not None:
            report["pages"].append(cart_record)
            report["findings"].extend(
                result for result in cart_record["category_results"] if result["status"] == "POTENTIAL"
            )
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
        "cart_interaction_status": cart_interaction["status"],
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
