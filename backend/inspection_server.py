from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import shutil
import subprocess
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.api.scan_orchestrator import ScanStore, validate_scan_request  # noqa: E402
from app.compliance.mapping import attach_compliance, attach_flipkart_heuristic_mapping, summarize_compliance  # noqa: E402
from app.database.repository import ScanDatabase  # noqa: E402
from app.integration.m1_m2_adapter import classify_m1_finding  # noqa: E402
from app.risk.scoring import calculate_risk  # noqa: E402
from scripts.flipkart_challenge_one import (  # noqa: E402
    CATEGORY_DEFINITIONS,
    DEFAULT_URLS,
    build_category_results,
    detect_category_matches,
    scan as scan_flipkart,
)


HOST = os.environ.get("INSPECTION_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("INSPECTION_API_PORT", "5051"))
DEFAULT_TARGET = os.environ.get("SHADOWBAIT_TARGET_URL", "http://127.0.0.1:3000").rstrip("/")
EVIDENCE_ROOT = Path(os.environ.get("SHADOWBAIT_EVIDENCE_DIR", str(REPO_ROOT / "evidence"))).resolve()
LIVE_ROOT = EVIDENCE_ROOT / "live-scans"
LIVE_ROOT.mkdir(parents=True, exist_ok=True)
STORE = ScanStore()
DATABASE = ScanDatabase(os.environ.get("SHADOWBAIT_DB_PATH", str(EVIDENCE_ROOT / "shadowbait.sqlite3")))

FINDINGS = [
    {"id": "DP01", "name": "False Urgency", "route": "/product", "selector": "#scarcity-text", "related": "#offer-timer", "evidence": "“ONLY 2 LEFT!” appears beside a countdown timer.", "why": "Captured to prove scarcity text and a time-pressure signal are visible together.", "harm": "Pressures customers to buy before comparing options or verifying the claim.", "ethical": "Show truthful stock and a fixed, clearly stated offer end time."},
    {"id": "DP02", "name": "Basket Sneaking", "route": "/checkout", "selector": "#donation", "evidence": "Optional ₹50 donation checkbox starts checked.", "why": "Captured before interaction to preserve the original checked state.", "harm": "Adds an optional charge without an explicit affirmative choice.", "ethical": "Start optional add-ons unchecked and explain them plainly."},
    {"id": "DP03", "name": "Confirm Shaming", "route": "/checkout", "selector": "#confirm-shaming", "evidence": "“No, I don’t want to save money.”", "why": "Captured because the decline wording itself is the evidence.", "harm": "Uses guilt to steer customers toward an optional transaction.", "ethical": "Use neutral choices such as Continue without donation."},
    {"id": "DP05", "name": "Subscription Trap", "route": "/subscribe", "selector": '[data-ccpa-pattern="SUBSCRIPTION_TRAP"]', "evidence": "Automatic renewal is selected and cancellation is routed elsewhere.", "why": "Captured to compare the easy signup path with the separate cancellation flow.", "harm": "Makes recurring billing easier to start than to stop.", "ethical": "Offer cancellation with the same visibility and simplicity as sign-up."},
    {"id": "DP06", "name": "Interface Interference", "route": "/interface-interference", "selector": '[data-ccpa-pattern="INTERFACE_INTERFERENCE"]', "evidence": "Recommended plan is prominent while Basic is visually muted.", "why": "Captured to compare the visual hierarchy of the two consequential choices.", "harm": "Obscures the customer’s lower-commitment choice.", "ethical": "Give both consequential choices equal prominence and clarity."},
    {"id": "DP07", "name": "Bait and Switch", "route": "/bait-switch", "selector": "#bait-switch-status", "evidence": "₹799 selection becomes an unavailable ₹1,999 upgrade at the final step.", "why": "Captured to preserve both the selected offer and the changed final outcome.", "harm": "Wastes time and redirects purchase intent toward a more expensive item.", "ethical": "Keep the advertised outcome available or disclose changes immediately."},
    {"id": "DP08", "name": "Drip Pricing", "route": "/checkout", "selector": '[data-ccpa-pattern="DRIP_PRICING"]', "evidence": "Delivery, platform, and handling fees appear in the later checkout summary.", "why": "Captured to show the product price beside the later fee breakdown and total.", "harm": "Delays accurate price comparison until late in the journey.", "ethical": "Show the complete payable estimate beside the product price."},
]
FINDING_BY_ID = {item["id"]: item for item in FINDINGS}


def sse(handler: BaseHTTPRequestHandler, event: str, payload: dict) -> None:
    body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
    handler.wfile.write(body)
    handler.wfile.flush()


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def validate_public_target(target: str) -> bool:
    """Allow public HTTP(S) pages, with the known local demo as the sole exception."""
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Target must be an absolute http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError("Target URLs must not contain embedded credentials.")

    hostname = parsed.hostname.rstrip(".").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if (
        parsed.scheme == "http"
        and hostname in {"localhost", "127.0.0.1"}
        and port in {3000, 3001}
    ):
        return True
    if port not in {80, 443}:
        raise ValueError("Only public websites on standard HTTP/HTTPS ports can be inspected.")

    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not resolve public target host: {hostname}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private, local, and non-public network targets cannot be inspected.")
    return True


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip("/"))
    return value.strip("-").lower() or "home"


def repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def launch_browser(playwright):
    options = {}
    custom_path = os.environ.get("SHADOWBAIT_CHROMIUM_PATH")
    if custom_path:
        options["executable_path"] = custom_path
    return playwright.chromium.launch(**options)


def load_report(scan_id: str) -> dict | None:
    path = LIVE_ROOT / scan_id / "report.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def record_or_disk(scan_id: str):
    record = STORE.get(scan_id)
    if record:
        return record
    report = load_report(scan_id)
    if not report:
        return None
    scan = report.get("scan", {})
    pattern_ids = scan.get("pattern_ids") or [f.get("id") for f in FINDINGS]
    record = STORE.create(scan_id, scan.get("target", ""), pattern_ids)
    STORE.update(scan_id, status="COMPLETED", started_at=scan.get("started_at"), finished_at=scan.get("finished_at"), report=report)
    return STORE.get(scan_id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[inspection-api] " + fmt % args, flush=True)

    def _headers(self, content_type: str = "application/json") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 15_000_000:
            raise ValueError("request body must be a non-empty JSON object")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must contain valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._headers()
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/artifact-scan":
            try:
                self._handle_artifact_scan(self._read_json())
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": f"artifact scan failed: {exc}"})
            return
        if parsed.path != "/api/scans":
            self.send_error(404)
            return
        try:
            payload = self._read_json()
            target, pattern_ids = validate_scan_request(payload, set(FINDING_BY_ID))
            validate_public_target(target)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return

        scan_id = "live-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        record = STORE.create(scan_id, target, pattern_ids)
        DATABASE.create_scan(scan_id, target, pattern_ids)
        Thread(target=self._run_background_scan, args=(scan_id, target, pattern_ids), daemon=True).start()
        self._json(202, {"scan_id": scan_id, "status": record.status, "target": target, "pattern_ids": pattern_ids, "status_url": f"/api/scans/{scan_id}", "report_url": f"/api/scans/{scan_id}/report"})

    def _handle_artifact_scan(self, payload: dict) -> None:
        kind = str(payload.get("kind", "")).lower().strip()
        filename = str(payload.get("filename", "upload"))[:180]
        encoded = str(payload.get("data", ""))
        if kind not in {"screenshot", "file"}:
            raise ValueError("kind must be screenshot or file")
        if not encoded:
            raise ValueError("data must contain a base64-encoded upload")
        if "," in encoded and encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("data must be valid base64") from exc
        if not raw or len(raw) > 10_000_000:
            raise ValueError("upload must be between 1 byte and 10 MB")
        scan_id = "artifact-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out_dir = LIVE_ROOT / scan_id
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower() or (".png" if kind == "screenshot" else ".bin")
        artifact_path = out_dir / f"input{suffix}"
        artifact_path.write_bytes(raw)
        extracted = ""
        if kind == "screenshot":
            tesseract = shutil.which("tesseract")
            if tesseract:
                result = subprocess.run([tesseract, str(artifact_path), "stdout"], capture_output=True, text=True, timeout=45, check=False)
                extracted = result.stdout.strip()
            if not extracted:
                extracted = "No readable text was extracted from the screenshot. Review the captured image manually."
        elif suffix == ".pdf" and shutil.which("pdftotext"):
            result = subprocess.run(["pdftotext", str(artifact_path), "-"], capture_output=True, text=True, timeout=45, check=False)
            extracted = result.stdout.strip()
        else:
            extracted = raw.decode("utf-8", errors="replace")
        from scripts.flipkart_challenge_one import build_category_results, detect_category_matches
        html = extracted if suffix in {".html", ".htm", ".xml", ".svg"} else ""
        matches = detect_category_matches(extracted, html)
        screenshot_value = data_url(raw) if kind == "screenshot" else ""
        category_results = build_category_results(matches, f"upload://{filename}", repo_path(artifact_path), repo_path(artifact_path))
        findings = []
        for item in category_results:
            if item["status"] != "POTENTIAL":
                continue
            findings.append({**item, "id": item["pattern_id"], "name": item["pattern_name"], "route": f"upload://{filename}", "selector": "OCR text" if kind == "screenshot" else "file content", "screenshot": screenshot_value, "screenshot_file": repo_path(artifact_path) if kind == "screenshot" else "", "observed_text": "; ".join(item["evidence_text"]), "evidence": "; ".join(item["evidence_text"]), "harm": item["customer_harm"], "fix": item["recommendation"]})
        report = {"scan": {"scan_id": scan_id, "target": f"upload://{filename}", "mode": f"{kind} artifact scan", "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "pattern_ids": [item[0] for item in CATEGORY_DEFINITIONS]}, "categories": [{"pattern_id": item[0], "pattern_name": item[1], "family": item[2]} for item in CATEGORY_DEFINITIONS], "pages": [{"index": 1, "url_final": f"upload://{filename}", "title": filename, "category_results": category_results, "visible_text_characters": len(extracted), "artifact": repo_path(artifact_path)}], "findings": findings, "summary": {"pages_scanned": 1, "pages_requested": 1, "taxonomy_categories": len(CATEGORY_DEFINITIONS), "potential_matches": len(findings), "input_kind": kind, "filename": filename, "ocr_characters": len(extracted) if kind == "screenshot" else 0, "rogue_malware_status": "EXCLUDED_BY_SCOPE"}}
        write_json(out_dir / "report.json", report)
        STORE.create(scan_id, report["scan"]["target"], report["scan"]["pattern_ids"])
        STORE.update(scan_id, status="COMPLETED", started_at=report["scan"]["started_at"], finished_at=report["scan"]["finished_at"], report=report)
        DATABASE.create_scan(scan_id, report["scan"]["target"], report["scan"]["pattern_ids"])
        DATABASE.save_report(report)
        self._json(200, {"scan_id": scan_id, "report": report, "message": f"{kind.title()} analyzed across all 13 categories."})

    def _run_background_scan(self, scan_id: str, target: str, pattern_ids: list[str]) -> None:
        try:
            self.run_scan(target, scan_id=scan_id, pattern_ids=pattern_ids)
        except Exception as exc:
            STORE.update(scan_id, status="FAILED", error=str(exc), finished_at=datetime.now(timezone.utc).isoformat())
            DATABASE.update_scan(scan_id, status="FAILED", error=str(exc), finished_at=datetime.now(timezone.utc).isoformat())
            print(f"[inspection-api] scan {scan_id} failed: {exc}", flush=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True, "target": DEFAULT_TARGET, "evidence_root": repo_path(EVIDENCE_ROOT), "orchestration_api": True})
            return
        if parsed.path == "/api/scans":
            self._json(200, {"scans": DATABASE.list_scans()})
            return
        if parsed.path.startswith("/api/scans/"):
            self._get_scan_resource(parsed.path)
            return
        if parsed.path != "/api/inspection/stream":
            self.send_error(404)
            return
        query = parse_qs(parsed.query)
        target = query.get("target", [DEFAULT_TARGET])[0].rstrip("/")
        try:
            validate_public_target(target)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self.send_response(200)
        self._headers("text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            runner = self.run_flipkart_scan if self.is_flipkart_target(target) else self.run_scan
            runner(target, emit=lambda event, payload: sse(self, event, payload))
            self.close_connection = True
        except Exception as exc:
            try:
                sse(self, "error", {"message": str(exc)})
                self.close_connection = True
            except BrokenPipeError:
                pass

    @staticmethod
    def is_flipkart_target(target: str) -> bool:
        hostname = (urlparse(target).hostname or "").lower()
        return hostname in {"flipkart.com", "www.flipkart.com"} or hostname.endswith(".flipkart.com")

    def _run_public_scan(self, target: str, urls: list[str], emit=None, mode: str = "generalized live URL scan") -> dict:
        """Run the generalized public-page scanner through the dashboard SSE contract."""
        scan_id = "public-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out_dir = LIVE_ROOT / scan_id
        pattern_ids = [category_id for category_id, _, _ in CATEGORY_DEFINITIONS]
        parsed_target = urlparse(target)
        urls = DEFAULT_URLS if parsed_target.path in {"", "/"} else [target]
        total_steps = len(urls) + 1
        if emit:
            message = (
                "Chromium browser started for the six-page Flipkart sample scan and isolated cart check."
                if len(urls) > 1
                else "Chromium browser started for the requested Flipkart page and isolated cart check."
            )
            emit("started", {"scan_id": scan_id, "target": target, "browser": "Chromium", "viewport": {"width": 1440, "height": 1000}, "total": total_steps, "pattern_ids": pattern_ids, "mode": "Flipkart 13-category scan with isolated cart check", "message": message})
        streamed_findings = []
        def on_page(page: dict, index: int, total: int) -> None:
            page_url = page.get("url_final", page.get("url_requested", ""))
            if emit:
                page_status = page.get("status") or ("ERROR" if page.get("error") else "INSPECTED")
                emit("stage", {"completed": index, "total": total_steps, "page_index": index, "page_url": page_url, "page_title": page.get("title", ""), "page_status": page_status, "message": page.get("message") or f"Inspected Flipkart page {index}/{total_steps}: {page_url}"})
            for item in page.get("category_results", []):
                if item.get("status") != "POTENTIAL":
                    continue
                screenshot_file = REPO_ROOT / item["screenshot"]
                screenshot_value = data_url(screenshot_file.read_bytes()) if screenshot_file.is_file() else item.get("screenshot", "")
                finding = {**item, "id": item["pattern_id"], "name": item["pattern_name"], "route": item["page_url"], "selector": "body", "screenshot": screenshot_value, "screenshot_file": item.get("screenshot"), "observed_text": "; ".join(item.get("evidence_text", [])), "evidence": "; ".join(item.get("evidence_text", [])), "harm": "May influence a customer decision through pressure, confusion, cost, or reduced choice.", "fix": "Make the choice, cost, and consequence clear and neutral."}
                m2_findings = classify_m1_finding(finding)
                if finding.get("status") == "POTENTIAL":
                    for m2_finding in m2_findings:
                        m2_finding["status"] = "CANDIDATE"
                finding["m2_status"] = "CLASSIFIED" if m2_findings else "NOT_IN_M2_SCOPE"
                finding["m2_findings"] = m2_findings
                finding = attach_flipkart_heuristic_mapping(finding)
                streamed_findings.append(finding)
                if emit:
                    emit("finding", {"completed": index, "total": total, "finding": finding, "message": f"Potential {finding['name']} found on {page_url}."})
                    emit("classification", {"completed": index, "total": total_steps, "pattern_id": finding["id"], "status": finding["m2_status"], "findings": m2_findings, "message": f"M2 classification {finding['m2_status'].lower()} for {finding['name']}."})
        raw = scan_flipkart(urls, out_dir, on_page=on_page)
        pages = raw.get("pages", [])
        findings = streamed_findings
        m2_findings = [item for finding in findings for item in finding.get("m2_findings", [])]
        report = {"findings": findings}
        risk = calculate_risk(report)
        compliance = summarize_compliance(findings)
        summary = {
            **raw.get("summary", {}),
            "captured_findings": len(findings),
            "pages_scanned": len(pages),
            "flipkart_13_category_scan": True,
            "cart_interaction_status": raw.get("cart_interaction", {}).get("status", "UNKNOWN"),
            "m2_classified_findings": len(m2_findings),
            "m2_verified_findings": sum(1 for item in m2_findings if item.get("status") == "VERIFIED"),
            "m2_detection_sources": {
                source: sum(1 for item in m2_findings if item.get("detection_source") == source)
                for source in sorted({item.get("detection_source") for item in m2_findings if item.get("detection_source")})
            },
            "compliance_mapped_findings": compliance["mapped_findings"],
            "compliance_verified_mappings": compliance["verified_mappings"],
            **{key: value for key, value in risk.items() if key != "scored_findings"},
        }
        finished_at = raw.get("scan", {}).get("finished_at") or datetime.now(timezone.utc).isoformat()
        report = {"scan": {**raw.get("scan", {}), "scan_id": scan_id, "target": target, "pattern_ids": pattern_ids, "finished_at": finished_at}, "categories": raw.get("categories", []), "pages": pages, "findings": findings, "cart_interaction": raw.get("cart_interaction", {}), "risk": risk, "compliance": compliance, "summary": summary}
        out_dir.mkdir(parents=True, exist_ok=True)
        for path in (out_dir / "scan.json", out_dir / "report.json", out_dir / "response.json"):
            write_json(path, report)
        STORE.create(scan_id, target, pattern_ids)
        STORE.update(scan_id, status="COMPLETED", started_at=report["scan"].get("started_at"), finished_at=finished_at, report=report)
        DATABASE.create_scan(scan_id, target, pattern_ids)
        DATABASE.save_report(report)
        if emit:
            emit("complete", {"scan_id": scan_id, "completed": total_steps, "total": total_steps, "findings": findings, "summary": summary, "finished_at": finished_at, "message": "Flipkart page and isolated cart scan complete — 13-category evidence is ready for review."})
        return report

    def run_flipkart_scan(self, target: str, emit=None) -> dict:
        return self._run_public_scan(target, DEFAULT_URLS, emit=emit, mode="Flipkart 13-category read-only scan")

    def run_generalized_scan(self, target: str, emit=None) -> dict:
        return self.run_public_page_scan(target, emit=emit)

    def _get_scan_resource(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) not in {3, 4} or parts[0:2] != ["api", "scans"]:
            self.send_error(404)
            return
        scan_id = parts[2]
        record = record_or_disk(scan_id)
        if record is None:
            database_scan = DATABASE.get_scan(scan_id)
            if database_scan is None:
                self._json(404, {"error": "scan not found", "scan_id": scan_id})
                return
            self._json(200, database_scan)
            return
        resource = parts[3] if len(parts) == 4 else None
        if resource is None:
            self._json(200, record.summary())
        elif resource == "report":
            self._json(200, record.report or {})
        elif resource == "findings":
            report = record.report or {}
            self._json(200, {"scan_id": scan_id, "status": record.status, "findings": report.get("findings", [])})
        elif resource == "evidence":
            report = record.report or {}
            self._json(200, {"scan_id": scan_id, "status": record.status, "evidence": [{"pattern_id": item.get("id"), "route": item.get("route"), "selector": item.get("selector"), "screenshot": item.get("screenshot_file"), "dom_html": item.get("dom_html_file"), "dom_text": item.get("dom_text_file")} for item in report.get("findings", [])]})
        else:
            self.send_error(404)

    def run_scan(self, target: str, emit=None, scan_id: str | None = None, pattern_ids: list[str] | None = None) -> dict:
        validate_public_target(target)
        if self.is_flipkart_target(target):
            return self.run_flipkart_scan(target, emit=emit)

        parsed_target = urlparse(target)
        if not (
            (parsed_target.hostname or "").lower() in {"localhost", "127.0.0.1"}
            and (parsed_target.port or 80) == 3000
        ):
            return self.run_public_page_scan(target, emit=emit, scan_id=scan_id)

        scan_id = scan_id or "live-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        pattern_ids = pattern_ids or list(FINDING_BY_ID)
        selected_findings = [FINDING_BY_ID[item] for item in pattern_ids]
        if STORE.get(scan_id) is None:
            STORE.create(scan_id, target, pattern_ids)
            DATABASE.create_scan(scan_id, target, pattern_ids)
        out_dir = LIVE_ROOT / scan_id
        screenshots_dir = out_dir / "screenshots"
        dom_dir = out_dir / "dom"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        dom_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()
        scan_meta = {"scan_id": scan_id, "target": target, "browser": "Chromium", "viewport": {"width": 1440, "height": 1000}, "started_at": started_at, "output_root": repo_path(out_dir), "pattern_ids": pattern_ids}
        if STORE.get(scan_id):
            STORE.update(scan_id, status="RUNNING", started_at=started_at)
        DATABASE.update_scan(scan_id, status="RUNNING", started_at=started_at)
        if emit:
            emit("started", {**scan_meta, "total": len(selected_findings), "message": "Chromium browser started with a fresh context."})
        captured = []
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
            page = context.new_page()
            for index, finding in enumerate(selected_findings):
                if emit:
                    emit("stage", {"completed": index, "total": len(selected_findings), "pattern_id": finding["id"], "route": finding["route"], "selector": finding["selector"], "message": f"Opening {finding['route']} and reading {finding['selector']}"})
                page.goto(target + finding["route"], wait_until="networkidle")
                locator = page.locator(finding["selector"]).first
                if locator.count() == 0:
                    raise RuntimeError(f"{finding['id']}: selector not found: {finding['selector']}")
                visible = locator.is_visible()
                text = locator.inner_text() if locator.evaluate("el => el.tagName !== 'INPUT'") else ""
                element_state = locator.evaluate("""el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return { tag: el.tagName, visible: !!(r.width && r.height), checked: typeof el.checked === 'boolean' ? el.checked : null, bounding_box: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) }, computed: { color: s.color, backgroundColor: s.backgroundColor, display: s.display } }; }""")
                if finding["id"] == "DP02":
                    text = page.locator("label[for=donation]").inner_text()
                if finding["id"] == "DP08":
                    text = page.locator(".drip-tag").inner_text()
                route_slug = slug(finding["route"])
                screenshot_path = screenshots_dir / f"{finding['id'].lower()}-{slug(finding['name'])}.png"
                screenshot = page.screenshot(path=str(screenshot_path), full_page=True)
                html_path = dom_dir / f"{route_slug}.html"
                text_path = dom_dir / f"{route_slug}-text.json"
                html_path.write_text(page.content(), encoding="utf-8")
                write_json(text_path, {"route": finding["route"], "url": page.url, "title": page.title(), "visible_text": page.locator("body").inner_text()})
                result = {**finding, "status": "VERIFIED", "visible": visible, "observed_text": text, "element_state": element_state, "screenshot": data_url(screenshot), "screenshot_file": repo_path(screenshot_path), "dom_html_file": repo_path(html_path), "dom_text_file": repo_path(text_path), "captured_at": datetime.now(timezone.utc).isoformat()}
                if finding["id"] == "DP02":
                    page.locator("#donation").uncheck()
                    after_path = screenshots_dir / "dp02-after-uncheck.png"
                    after = page.screenshot(path=str(after_path), full_page=True)
                    result["after_screenshot"] = data_url(after)
                    result["after_screenshot_file"] = repo_path(after_path)
                    result["state_transition"] = "checked=true → checked=false"
                if finding["id"] == "DP05":
                    page.goto(target + "/cancel", wait_until="networkidle")
                    related_path = screenshots_dir / "dp05-cancellation-flow.png"
                    related = page.screenshot(path=str(related_path), full_page=True)
                    result["after_screenshot"] = data_url(related)
                    result["after_screenshot_file"] = repo_path(related_path)
                    result["state_transition"] = "/subscribe → /cancel"
                m2_findings = classify_m1_finding(result)
                result["m2_status"] = "CLASSIFIED" if m2_findings else "NOT_IN_M2_SCOPE"
                result["m2_findings"] = m2_findings
                result = attach_compliance(result)
                captured.append(result)
                if emit:
                    emit("finding", {"completed": index + 1, "total": len(selected_findings), "finding": result, "message": f"Captured {finding['id']} screenshot and saved evidence."})
                    emit("classification", {"completed": index + 1, "total": len(selected_findings), "pattern_id": finding["id"], "status": result["m2_status"], "findings": m2_findings, "message": f"M2 classification {result['m2_status'].lower()} for {finding['id']}."})
            context.close()
            browser.close()
        finished_at = datetime.now(timezone.utc).isoformat()
        all_m2 = [item for finding in captured for item in finding.get("m2_findings", [])]
        report = {"scan": {**scan_meta, "finished_at": finished_at}, "findings": captured, "summary": {"verified_findings": len(captured), "pages_scanned": len(set(item["route"] for item in captured)), "m2_classified_findings": len(all_m2), "m2_verified_findings": sum(1 for item in all_m2 if item.get("status") == "VERIFIED"), "m2_detection_sources": {source: sum(1 for item in all_m2 if item.get("detection_source") == source) for source in sorted({item.get("detection_source") for item in all_m2})}}}
        report["risk"] = calculate_risk(report)
        report["summary"].update({key: value for key, value in report["risk"].items() if key != "scored_findings"})
        report["compliance"] = summarize_compliance(captured)
        report["summary"]["compliance_mapped_findings"] = report["compliance"]["mapped_findings"]
        report["summary"]["compliance_verified_mappings"] = report["compliance"]["verified_mappings"]
        scan_path = out_dir / "scan.json"
        report_path = out_dir / "report.json"
        response_path = out_dir / "response.json"
        for path in (scan_path, report_path, response_path):
            write_json(path, report)
        if STORE.get(scan_id):
            STORE.update(scan_id, status="COMPLETED", finished_at=finished_at, report=report)
        DATABASE.save_report(report)
        if emit:
            emit("complete", {"scan_id": scan_id, "completed": len(captured), "total": len(selected_findings), "findings": captured, "summary": report["summary"], "scan_file": repo_path(scan_path), "report_file": repo_path(report_path), "response_file": repo_path(response_path), "finished_at": finished_at, "message": "Inspection complete — live evidence and M2 classifications ready and saved."})
        return report

    def run_public_page_scan(self, target: str, emit=None, scan_id: str | None = None) -> dict:
        """Capture one public page without clicking, submitting, or following links."""
        validate_public_target(target)
        scan_id = scan_id or "public-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        pattern_ids = [category_id for category_id, _, _ in CATEGORY_DEFINITIONS]
        out_dir = LIVE_ROOT / scan_id
        screenshots_dir = out_dir / "screenshots"
        dom_dir = out_dir / "dom"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        dom_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()
        scan_meta = {
            "scan_id": scan_id,
            "target": target,
            "mode": "Generic public single-page inspection",
            "browser": "Chromium",
            "viewport": {"width": 1440, "height": 1000},
            "started_at": started_at,
            "output_root": repo_path(out_dir),
            "pattern_ids": pattern_ids,
        }
        if STORE.get(scan_id) is None:
            STORE.create(scan_id, target, pattern_ids)
            DATABASE.create_scan(scan_id, target, pattern_ids)
        STORE.update(scan_id, status="RUNNING", started_at=started_at)
        DATABASE.update_scan(scan_id, status="RUNNING", started_at=started_at)
        if emit:
            emit("started", {
                **scan_meta,
                "total": 1,
                "message": "Opening one public page in a read-only browser context.",
            })

        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                color_scheme="light",
            )

            def guard_request(route) -> None:
                request_url = route.request.url
                if urlparse(request_url).scheme not in {"http", "https"}:
                    route.continue_()
                    return
                try:
                    validate_public_target(request_url)
                except ValueError:
                    route.abort("blockedbyclient")
                    return
                route.continue_()

            context.route("**/*", guard_request)
            page = context.new_page()
            page.set_default_timeout(20_000)
            response = page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            response_status = response.status if response else None
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except PlaywrightTimeoutError:
                pass

            visible_text = page.locator("body").inner_text(timeout=20_000)
            html = page.content()
            page_blocked = response_status in {401, 403, 429}
            no_content = not visible_text.strip()
            inspection_status = (
                "BLOCKED" if page_blocked else "NO_CONTENT" if no_content else "INSPECTED"
            )
            if page_blocked:
                message = (
                    f"The website returned HTTP {response_status}; access was denied or "
                    "rate-limited, so no pattern analysis was performed."
                )
            elif no_content:
                status_description = (
                    f"HTTP {response_status}" if response_status is not None else "an empty response"
                )
                message = (
                    f"The website returned {status_description} with no visible page content. "
                    "It may be applying bot protection or requiring a supported browser session; "
                    "no pattern analysis was performed."
                )
            else:
                message = f"Captured and analyzed one public page (HTTP {response_status or 'unknown'})."
            screenshot_path = screenshots_dir / "01-page.png"
            html_path = dom_dir / "01-page.html"
            text_path = dom_dir / "01-page-text.json"
            screenshot = page.screenshot(path=str(screenshot_path), full_page=True)
            html_path.write_text(html, encoding="utf-8")
            write_json(text_path, {
                "url": page.url,
                "title": page.title(),
                "visible_text": visible_text,
            })
            if page_blocked or no_content:
                category_results = []
            else:
                matches = detect_category_matches(visible_text, html)
                category_results = build_category_results(
                    matches,
                    page.url,
                    repo_path(screenshot_path),
                    repo_path(text_path),
                )
            page_record = {
                "url_requested": target,
                "url_final": page.url,
                "title": page.title(),
                "status": inspection_status,
                "http_status": response_status,
                "visible_text_characters": len(visible_text),
                "screenshot": repo_path(screenshot_path),
                "dom_html": repo_path(html_path),
                "dom_text": repo_path(text_path),
                "category_results": category_results,
            }
            context.close()
            browser.close()

        findings = []
        for item in category_results:
            if item["status"] != "POTENTIAL":
                continue
            evidence_text = item["evidence_text"]
            finding = {
                **item,
                "id": item["pattern_id"],
                "name": item["pattern_name"],
                "route": page.url,
                "selector": "body",
                "screenshot": data_url(screenshot),
                "screenshot_file": item["screenshot"],
                "observed_text": "; ".join(evidence_text),
                "evidence": "; ".join(evidence_text),
                "harm": "May influence a customer decision through pressure, confusion, cost, or reduced choice.",
                "fix": "Make the choice, cost, and consequence clear and neutral.",
            }
            m2_findings = classify_m1_finding(finding)
            for m2_finding in m2_findings:
                m2_finding["status"] = "CANDIDATE"
            finding["m2_status"] = "CLASSIFIED" if m2_findings else "NOT_IN_M2_SCOPE"
            finding["m2_findings"] = m2_findings
            finding = attach_flipkart_heuristic_mapping(
                finding,
                source="Generic public-page 13-category heuristic mapping",
            )
            findings.append(finding)
            if emit:
                emit("finding", {
                    "completed": 1,
                    "total": 1,
                    "finding": finding,
                    "message": f"Potential {finding['name']} signal captured on {page.url}.",
                })
                emit("classification", {
                    "completed": 1,
                    "total": 1,
                    "pattern_id": finding["id"],
                    "status": finding["m2_status"],
                    "findings": m2_findings,
                    "message": f"M2 classification {finding['m2_status'].lower()} for {finding['name']}.",
                })
        if inspection_status == "INSPECTED" and not findings:
            message = (
                "The page loaded, but no heuristic signals were captured in its visible content. "
                "This does not establish that those patterns are absent."
            )
        finished_at = datetime.now(timezone.utc).isoformat()
        scan_meta["inspection_status"] = inspection_status
        scan_meta["http_status"] = response_status
        scan_meta["message"] = message
        risk = calculate_risk({"findings": findings})
        compliance = summarize_compliance(findings)
        m2_findings = [item for finding in findings for item in finding["m2_findings"]]
        summary = {
            "captured_findings": len(findings),
            "pages_scanned": 1,
            "categories_assessed": len(CATEGORY_DEFINITIONS) if inspection_status == "INSPECTED" else 0,
            "inspection_status": inspection_status,
            "http_status": response_status,
            "m2_classified_findings": len(m2_findings),
            "m2_verified_findings": 0,
            "compliance_mapped_findings": compliance["mapped_findings"],
            "compliance_verified_mappings": 0,
            **{key: value for key, value in risk.items() if key != "scored_findings"},
        }
        report = {
            "scan": {**scan_meta, "finished_at": finished_at},
            "categories": [
                {"pattern_id": item[0], "pattern_name": item[1], "family": item[2]}
                for item in CATEGORY_DEFINITIONS
            ],
            "pages": [page_record],
            "findings": findings,
            "risk": risk,
            "compliance": compliance,
            "summary": summary,
        }
        for filename in ("scan.json", "report.json", "response.json"):
            write_json(out_dir / filename, report)
        STORE.update(scan_id, status="COMPLETED", finished_at=finished_at, report=report)
        DATABASE.save_report(report)
        if emit:
            emit("stage", {
                "completed": 1,
                "total": 1,
                "page_index": 1,
                "page_url": page.url,
                "page_title": page_record["title"],
                "page_status": inspection_status,
                "message": message,
            })
            emit("complete", {
                "scan_id": scan_id,
                "completed": 1,
                "total": 1,
                "findings": findings,
                "summary": summary,
                "finished_at": finished_at,
                "scan": report["scan"],
                "message": message,
            })
        return report


if __name__ == "__main__":
    print(f"Inspection API listening on http://{HOST}:{PORT}; target={DEFAULT_TARGET}; evidence={EVIDENCE_ROOT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
