from __future__ import annotations

from app.ux.analyzer import analyze_elements, analyze_html, not_assessable_for_screenshot


def test_html_detects_missing_label_and_alt_text():
    findings = analyze_html('<main><h1>Checkout</h1><input id="email" type="email"><img src="hero.png"></main>')
    rule_ids = {item["id"] for item in findings}
    assert "A11Y_MISSING_LABEL" in rule_ids
    assert "A11Y_MISSING_ALT" in rule_ids


def test_html_detects_ambiguous_button_and_long_copy():
    long_text = "This is a very long instruction " * 8
    findings = analyze_html(f'<p>{long_text}</p><button>Continue</button>')
    rule_ids = {item["id"] for item in findings}
    assert "READ_LONG_SENTENCE" in rule_ids
    assert "READ_AMBIGUOUS_BUTTON" in rule_ids


def test_good_form_has_no_missing_name_findings():
    findings = analyze_html('<label for="email">Email address</label><input id="email" aria-label="Email address">')
    rule_ids = {item["id"] for item in findings}
    assert "A11Y_MISSING_LABEL" not in rule_ids


def test_live_snapshot_reports_contrast_measurement():
    findings = analyze_elements([{
        "tag": "p", "id": "notice", "text": "Important notice", "visible": True,
        "selector": "#notice", "html": '<p id="notice">Important notice</p>',
        "boundingBox": {"x": 0, "y": 0, "width": 100, "height": 20},
        "fontSize": "14px", "color": "rgb(180, 180, 180)", "backgroundColor": "rgb(255, 255, 255)",
    }])
    finding = next(item for item in findings if item["id"] == "A11Y_LOW_CONTRAST")
    assert finding["evidence"]["observed_value"] < finding["evidence"]["threshold"]


def test_screenshot_marks_dom_checks_not_assessable():
    finding = not_assessable_for_screenshot("no DOM", "evidence/shot.png")[0]
    assert finding["status"] == "NOT_ASSESSABLE"
    assert finding["category"] == "SCOPE"
