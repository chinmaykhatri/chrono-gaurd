"""Exercise the authenticated console in Chromium against the local replay deployment."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "Overview": "Freshness overview", "Playground": "Playground", "Live feed": "Live feed",
    "Cache explorer": "Cache explorer", "Fact ledger": "Fact ledger", "Policies": "Policies",
    "Costs & latency": "Costs & latency", "ROI report": "Return on Investment",
    "Evaluation lab": "Evaluation lab", "Settings": "Settings",
}


def run(origin, password, images=None):
    if urlsplit(origin).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Use the loopback replay deployment.")
    checks, errors = [], []

    def passed(name):
        checks.append(name)
        print("PASS", name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1, timezone_id="UTC")
        page.set_default_timeout(20000)
        page.on("pageerror", lambda err: errors.append(str(err)))

        def check_http(response):
            path = urlsplit(response.url).path
            if response.status >= 400 and (path, response.status) != ("/api/v1/auth/session", 401):
                errors.append(f"{response.status} {path}")

        page.on("response", check_http)
        nav = page.get_by_role("navigation", name="Main navigation")

        def visit(label):
            nav.get_by_role("link", name=label, exact=True).click()
            expect(page.get_by_role("heading", level=1, name=PAGES[label], exact=True)).to_be_visible()
            expect(page.get_by_role("alert")).to_have_count(0)

        def capture(name):
            if images:
                images.mkdir(parents=True, exist_ok=True)
                if gpu:
                    expect(page.locator(".chronometer")).to_have_attribute("data-engine", "webgl")
                page.evaluate("document.fonts.ready")
                page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")
                page.screenshot(path=images / (name + ".png"), animations="disabled")

        page.goto(origin, wait_until="domcontentloaded")
        password_field = page.get_by_label("Admin password")
        expect(password_field).to_be_visible()
        gpu = page.evaluate("!!document.createElement('canvas').getContext('webgl2')")
        if gpu:
            expect(page.locator(".chronometer")).to_have_attribute("data-engine", "webgl", timeout=20000)
        passed("Render the verification clock")
        capture("sign-in")
        password_field.fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(nav).to_be_visible()
        passed("Sign in")
        for label in PAGES:
            visit(label)
            passed("Open " + label)
        visit("Overview")
        expect(page.locator(".stats")).to_be_visible()
        face = page.locator(".instrument-field")
        face.focus()
        face.press("ArrowRight")
        assert float(face.evaluate("el => parseFloat(el.style.getPropertyValue('--dial-yaw'))")) > 0
        face.press("Home")
        bounds = face.bounding_box()
        x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 65, y, steps=4)
        page.mouse.up()
        assert float(face.evaluate("el => parseFloat(el.style.getPropertyValue('--dial-yaw'))")) > 0.5
        page.get_by_role("button", name="Reset clock view").click()
        page.get_by_role("button", name="Pause rotation").click()
        expect(page.locator(".chronometer")).to_have_attribute("data-motion", "still")
        page.get_by_role("button", name="Resume rotation").click()
        page.evaluate("window.scrollTo(0, 180)")
        expect(face).not_to_have_css("--dial-yaw", "0rad")
        assert float(face.evaluate("el => parseFloat(getComputedStyle(el).getPropertyValue('--dial-yaw'))")) > 0.01
        page.evaluate("window.scrollTo(0, 0)")
        expect(face).to_have_css("--dial-yaw", "0rad")
        passed("Rotate by keyboard, pointer and scroll, pause and reset")
        capture("overview")
        visit("Settings")
        page.get_by_label("Freeze at local time").fill("2030-01-02T09:17")
        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/v1/clock" and r.request.method == "POST") as frozen:
            page.get_by_role("button", name="Freeze clock").click()
        assert frozen.value.ok
        try:
            visit("Overview")
            expect(page.locator(".instrument-time time")).to_have_text("09:17 UTC", timeout=12000)
        finally:
            visit("Settings")
            with page.expect_response(lambda r: urlsplit(r.url).path == "/api/v1/clock" and r.request.method == "POST") as reset:
                page.get_by_role("button", name="Reset to real time").click()
            assert reset.value.ok
        passed("Display the gateway's frozen UTC time and restore real time")
        visit("Playground")
        page.get_by_label("Message", exact=True).fill("What is the latest major Go release?")
        page.get_by_role("button", name="Send request").click()
        expect(page.locator(".message.assistant .answer-text")).to_contain_text("Go 1.24", timeout=20000)
        expect(page.locator(".annotation-summary")).to_be_visible()
        for tab in ("Evidence", "Trace", "Raw", "Claims"):
            page.get_by_role("navigation", name="Response details").get_by_role("button", name=tab).click()
            expect(page.get_by_role("alert")).to_have_count(0)
        passed("Send a Playground request and inspect the answer")
        visit("Cache explorer")
        page.locator('main a[href^="/cache/"]').first.click()
        expect(page.get_by_text("Claim manifest", exact=True)).to_be_visible()
        passed("Open a persisted cache manifest")
        visit("Fact ledger")
        page.locator('main a[href^="/facts/"]').filter(has_text="interactive-replay").first.click()
        expect(page.locator('main a[href^="https://go.dev/"]').first).to_be_visible()
        with page.expect_response(lambda r: "/reverify" in r.url and r.request.method == "POST") as recheck:
            page.get_by_role("button", name="Re-verify fact").click()
        assert recheck.value.ok, recheck.value.status
        passed("Read the fact evidence and reverify a linked entry")
        visit("Policies")
        page.get_by_role("button", name="Edit policy").first.click()
        with page.expect_response(lambda r: "/api/v1/policies/" in r.url and r.request.method == "PUT") as update:
            page.get_by_role("button", name="Save policy").click()
        assert update.value.ok, update.value.status
        passed("Save the existing operator policy")
        visit("Evaluation lab")
        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/v1/eval/runs" and r.request.method == "POST") as evaluation:
            page.get_by_role("button", name="Run release replay").click()
        assert evaluation.value.ok, evaluation.value.status
        page.locator('main a[href^="/eval/runs/"]').first.click()
        expect(page.get_by_role("img", name="Stale cache hits versus evidence credits in the controlled replay")).to_be_visible()
        with page.expect_download() as exported:
            page.get_by_role("button", name="Export raw traces").click()
        report = json.loads(Path(exported.value.path()).read_text(encoding="utf-8"))
        assert len(report["variants"]) == 8 and len(report["rows"]) == 584 * 8
        passed("Run the evaluation and export all 4,672 observations")
        visit("ROI report")
        with page.expect_download() as exported:
            page.get_by_role("button", name="Export JSON").click()
        roi = json.loads(Path(exported.value.path()).read_text(encoding="utf-8"))
        assert roi["requests_observed"] > 0
        passed("Export ROI data from recorded requests")
        page.set_viewport_size({"width": 390, "height": 844})
        for label in PAGES:
            page.get_by_role("button", name="Open navigation").click()
            visit(label)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), label
            if label == "Overview":
                expect(page.locator(".stats")).to_be_visible()
                capture("mobile-overview")
        passed("Open all ten pages using the mobile navigation")
        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(password_field).to_be_visible()
        passed("Sign out")
        assert not errors, errors
        browser_version = browser.version
        browser.close()
        fallback = playwright.chromium.launch(args=["--disable-webgl"])
        accessible = fallback.new_page(reduced_motion="reduce", viewport={"width": 390, "height": 844})
        accessible.goto(origin, wait_until="domcontentloaded")
        expect(accessible.locator(".chronometer")).to_have_attribute("data-motion", "still")
        expect(accessible.locator(".fallback-dial")).to_be_visible()
        expect(accessible.get_by_role("button", name="Pause rotation")).to_have_count(0)
        accessible.locator(".instrument-field").press("ArrowRight")
        assert float(accessible.locator(".instrument-field").evaluate("el => parseFloat(el.style.getPropertyValue('--dial-yaw'))")) > 0
        fallback.close()
        passed("Use the static-face fallback with WebGL disabled and reduced motion enabled")
        return {"timestamp": datetime.now(UTC).isoformat(), "scope": "chromium_docker_replay",
                "browser": browser_version, "webgl": gpu, "passed": True, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://localhost:8080")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    report = run(args.gateway, (ROOT / ".admin-password").read_text(encoding="utf-8").strip(), args.screenshots)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
