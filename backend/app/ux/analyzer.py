"""Evidence-first accessibility and readability heuristics.

These checks are intentionally scoped as UX observations, not WCAG certification.
They operate on structured DOM snapshots when available and on visible text for
HTML/file artifacts. Every finding includes its rule, measurement, evidence, and
an actionable recommendation.
"""
from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser
from typing import Any


def _finding(rule_id: str, category: str, name: str, severity: str, confidence: float,
             evidence: dict[str, Any], impact: str, recommendation: str,
             source: str = "DOM heuristic") -> dict[str, Any]:
    return {
        "id": rule_id,
        "type": "UX_FLAW",
        "category": category,
        "name": name,
        "severity": severity,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "status": "OBSERVED",
        "evidence": evidence,
        "impact": impact,
        "recommendation": recommendation,
        "source": source,
        "scope": "heuristic UX observation; not a full WCAG audit",
    }


def _accessible_name(element: dict[str, Any], ids: set[str]) -> str:
    if str(element.get("ariaLabel") or "").strip():
        return str(element["ariaLabel"]).strip()
    labelledby = str(element.get("ariaLabelledby") or "").split()
    if labelledby and all(item in ids for item in labelledby):
        return "labelled reference"
    text = str(element.get("text") or "").strip()
    if text:
        return re.sub(r"\s+", " ", text)
    return ""


def _parse_rgb(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", value or "")
    if match:
        return tuple(int(item) for item in match.groups())
    match = re.fullmatch(r"#([0-9a-f]{6})", (value or "").strip().lower())
    if match:
        raw = match.group(1)
        return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))
    return None


def _contrast_ratio(foreground: str, background: str) -> float | None:
    colors = [_parse_rgb(value) for value in (foreground, background)]
    if any(color is None for color in colors):
        return None
    luminances = []
    for color in colors:
        channels = []
        for channel in color or ():
            normalized = channel / 255
            channels.append(normalized / 12.92 if normalized <= 0.03928 else ((normalized + 0.055) / 1.055) ** 2.4)
        luminances.append(0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2])
    light, dark = max(luminances), min(luminances)
    return round((light + 0.05) / (dark + 0.05), 2)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]*", text or "")


def analyze_elements(elements: list[dict[str, Any]], visible_text: str = "", *,
                     source: str = "DOM heuristic", screenshot: str = "") -> list[dict[str, Any]]:
    """Analyze a browser-collected element snapshot."""
    findings: list[dict[str, Any]] = []
    ids = {str(item.get("id")) for item in elements if item.get("id")}
    seen_ids: set[str] = set()
    headings: list[int] = []
    for element in elements:
        tag = str(element.get("tag") or "").lower()
        selector = element.get("selector") or (f"#{element['id']}" if element.get("id") else tag)
        html = str(element.get("html") or "")[:800]
        evidence_base = {"selector": selector, "html": html, "bounding_box": element.get("boundingBox"), "screenshot": screenshot}
        if element.get("id"):
            if element["id"] in seen_ids:
                findings.append(_finding("A11Y_DUPLICATE_ID", "ACCESSIBILITY", "Duplicate element ID", "HIGH", .99,
                    {**evidence_base, "id": element["id"]}, "Duplicate IDs can break label, focus, and assistive-technology references.", "Use a unique id for every element and update references." , source))
            seen_ids.add(str(element["id"]))
        if tag == "img" and element.get("visible") and not str(element.get("alt") or "").strip():
            findings.append(_finding("A11Y_MISSING_ALT", "ACCESSIBILITY", "Image without alternative text", "MEDIUM", .98,
                evidence_base, "People who cannot see the image may miss meaningful content.", "Add concise alt text, or mark the image decorative only when it conveys no information.", source))
        if tag in {"input", "select", "textarea"} and element.get("visible") and not _accessible_name(element, ids):
            findings.append(_finding("A11Y_MISSING_LABEL", "ACCESSIBILITY", "Form control without an accessible name", "HIGH", .98,
                {**evidence_base, "type": element.get("inputType")}, "Screen-reader and voice-control users may not know what this field requires.", "Add a visible label or a valid aria-label/aria-labelledby reference.", source))
        if tag in {"button", "a"} and element.get("visible") and not _accessible_name(element, ids):
            rule = "A11Y_UNNAMED_BUTTON" if tag == "button" else "A11Y_LINK_NO_NAME"
            name = "Button without an accessible name" if tag == "button" else "Link without an accessible name"
            findings.append(_finding(rule, "ACCESSIBILITY", name, "HIGH", .98, evidence_base,
                "Users relying on assistive technology may not understand or operate this control.", "Provide visible text or an accessible name that describes the action or destination.", source))
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            headings.append(int(tag[1]))
        box = element.get("boundingBox") or {}
        if tag in {"button", "a", "input", "select", "textarea"} and element.get("visible"):
            width, height = float(box.get("width") or 0), float(box.get("height") or 0)
            if 0 < width < 24 or 0 < height < 24:
                findings.append(_finding("A11Y_SMALL_TARGET", "ACCESSIBILITY", "Small interactive target", "MEDIUM", .94,
                    {**evidence_base, "width": width, "height": height, "minimum": 24}, "Small controls are harder to activate accurately, especially on touch devices.", "Provide a larger hit area; use at least 24 CSS pixels as a conservative heuristic.", source))
        ratio = _contrast_ratio(str(element.get("color") or ""), str(element.get("backgroundColor") or ""))
        if ratio is not None and element.get("visible") and tag not in {"img", "svg"}:
            font_size = float(re.sub(r"[^0-9.]", "", str(element.get("fontSize") or "16")) or 16)
            threshold = 3.0 if font_size >= 18 else 4.5
            if ratio < threshold and (str(element.get("text") or "").strip() or tag in {"button", "a", "input"}):
                findings.append(_finding("A11Y_LOW_CONTRAST", "ACCESSIBILITY", "Likely low text contrast", "MEDIUM", .95,
                    {**evidence_base, "observed_value": ratio, "threshold": threshold, "measurement": "contrast ratio"}, "Low contrast makes text or controls difficult to read for people with low vision or poor display conditions.", "Increase foreground/background contrast; verify the final design with a WCAG contrast tool.", source))
        if tag in {"p", "label", "button", "a"}:
            text = str(element.get("text") or "").strip()
            if text and text.isupper() and len(_words(text)) >= 5:
                findings.append(_finding("READ_ALL_CAPS_BLOCK", "READABILITY", "Large all-caps text block", "LOW", .88,
                    {**evidence_base, "text": text[:300]}, "All-caps passages are slower to scan and harder to read for many users.", "Use sentence case for explanatory copy and reserve all caps for short labels.", source))
            words = _words(text)
            if len(words) > 30:
                findings.append(_finding("READ_LONG_SENTENCE", "READABILITY", "Long interface instruction", "MEDIUM", .92,
                    {**evidence_base, "word_count": len(words), "threshold": 30, "text": text[:400]}, "Long instructions increase cognitive load and make important consequences easier to miss.", "Break the instruction into shorter sentences or concise steps.", source))
        font_size = float(re.sub(r"[^0-9.]", "", str(element.get("fontSize") or "16")) or 16)
        if tag in {"p", "label", "button", "a", "input"} and element.get("visible") and font_size < 12:
            findings.append(_finding("READ_SMALL_TEXT", "READABILITY", "Very small interface text", "MEDIUM", .93,
                {**evidence_base, "font_size_px": font_size, "threshold_px": 12}, "Small text is difficult to read and can hide instructions or consequences.", "Use a larger text size for body copy, labels, and actionable controls.", source))
    if headings:
        previous = headings[0]
        for level in headings[1:]:
            if level > previous + 1:
                findings.append(_finding("A11Y_HEADING_ORDER", "ACCESSIBILITY", "Skipped heading level", "LOW", .9,
                    {"heading_levels": headings, "observed_transition": f"h{previous} → h{level}", "screenshot": screenshot}, "Inconsistent heading structure makes page hierarchy harder to navigate with assistive technology.", "Use heading levels in a logical order without skipping levels.", source))
                break
            previous = level
    for element in elements:
        tag = str(element.get("tag") or "").lower()
        text = str(element.get("text") or "").strip().lower()
        if tag == "button" and text in {"continue", "submit", "next", "go", "ok"}:
            findings.append(_finding("READ_AMBIGUOUS_BUTTON", "READABILITY", "Ambiguous action label", "MEDIUM", .82,
                {"selector": element.get("selector") or "button", "text": element.get("text"), "screenshot": screenshot}, "Users may not know what outcome this action produces.", "Use an outcome-oriented label such as ‘Continue without membership’ or ‘Save changes’.", source))
    # OCR, Markdown, TXT, and PDF extraction may have no element structure;
    # still assess readable prose without pretending to know its DOM semantics.
    text_blocks = [block.strip() for block in re.split(r"(?<=[.!?])\s+|\n+", visible_text or "") if block.strip()]
    if not any(item.get("id") == "READ_LONG_SENTENCE" for item in findings):
        for block in text_blocks:
            words = _words(block)
            if len(words) > 30:
                findings.append(_finding("READ_LONG_SENTENCE", "READABILITY", "Long interface instruction", "MEDIUM", .82,
                    {"text": block[:400], "word_count": len(words), "threshold": 30, "screenshot": screenshot}, "Long instructions increase cognitive load and make important consequences easier to miss.", "Break the instruction into shorter sentences or concise steps.", source))
                break
    if not any(item.get("id") == "READ_ALL_CAPS_BLOCK" for item in findings):
        for block in text_blocks:
            if block.isupper() and len(_words(block)) >= 5:
                findings.append(_finding("READ_ALL_CAPS_BLOCK", "READABILITY", "Large all-caps text block", "LOW", .78,
                    {"text": block[:300], "screenshot": screenshot}, "All-caps passages are slower to scan and harder to read for many users.", "Use sentence case for explanatory copy and reserve all caps for short labels.", source))
                break
    return findings


class _SimpleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict[str, Any]] = []
        self.elements: list[dict[str, Any]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        item = {"tag": tag, "id": data.get("id"), "text": "", "html": "", "visible": True,
                "alt": data.get("alt"), "ariaLabel": data.get("aria-label"), "ariaLabelledby": data.get("aria-labelledby"),
                "inputType": data.get("type"), "selector": f"#{data['id']}" if data.get("id") else tag}
        self.elements.append(item)
        self.stack.append(item)

    def handle_endtag(self, tag: str) -> None:
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_parts.append(data)
            if self.stack:
                self.stack[-1]["text"] += data


def analyze_html(html: str, visible_text: str | None = None, *, source: str = "HTML heuristic") -> list[dict[str, Any]]:
    parser = _SimpleHTMLParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    text = visible_text if visible_text is not None else html_lib.unescape(" ".join(parser.text_parts))
    return analyze_elements(parser.elements, text, source=source)


def not_assessable_for_screenshot(reason: str, screenshot: str = "") -> list[dict[str, Any]]:
    return [{
        "id": "UX_DOM_NOT_ASSESSABLE", "type": "UX_FLAW", "category": "SCOPE", "name": "DOM-dependent UX checks not assessable",
        "severity": "INFO", "confidence": 1.0, "status": "NOT_ASSESSABLE", "evidence": {"screenshot": screenshot, "reason": reason},
        "impact": "A screenshot cannot prove semantic labels, heading order, keyboard behavior, or ARIA relationships.",
        "recommendation": "Run the live URL or HTML analysis when DOM-level accessibility evidence is required.",
        "source": "Scope boundary", "scope": "not a defect finding",
    }]
