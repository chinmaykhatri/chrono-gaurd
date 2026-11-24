from pathlib import Path
import os
import sys
import time
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "screenshots"))
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

PASSWORD = (Path(__file__).resolve().parents[1] / ".admin-password").read_text(encoding="utf-8").strip()
BASE_URL = "http://127.0.0.1:5175"

def run_browser_checks():
    print(f"Starting browser verification against {BASE_URL}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Step 1: Open Login Page
        print("\n[1/10] Navigating to login page...")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        login_shot = os.path.join(SCREENSHOT_DIR, "01_login.png")
        page.screenshot(path=login_shot)
        print(f"  Captured login screenshot: {login_shot}")

        # Fill in password & submit
        page.fill("#password", PASSWORD)
        page.click("button.primary")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # Step 2: Overview Page
        print("\n[2/10] Verifying Overview page...")
        overview_shot = os.path.join(SCREENSHOT_DIR, "02_overview.png")
        page.screenshot(path=overview_shot)
        print(f"  Captured overview screenshot: {overview_shot}")
        kpi_count = page.locator(".stats a").count()
        print(f"  Found {kpi_count} KPI metric cards.")

        # Step 3: Playground
        print("\n[3/10] Navigating to Playground...")
        page.click("a[href='/playground']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        pg_shot = os.path.join(SCREENSHOT_DIR, "03_playground.png")
        page.screenshot(path=pg_shot)
        print(f"  Captured Playground screenshot: {pg_shot}")

        # Step 4: Live Feed
        print("\n[4/10] Navigating to Live Feed...")
        page.click("a[href='/feed']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        feed_shot = os.path.join(SCREENSHOT_DIR, "04_feed.png")
        page.screenshot(path=feed_shot)
        print(f"  Captured Live Feed screenshot: {feed_shot}")

        # Step 5: Cache Explorer
        print("\n[5/10] Navigating to Cache Explorer...")
        page.click("a[href='/cache']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        cache_shot = os.path.join(SCREENSHOT_DIR, "05_cache.png")
        page.screenshot(path=cache_shot)
        print(f"  Captured Cache Explorer screenshot: {cache_shot}")

        # Step 6: Fact Ledger
        print("\n[6/10] Navigating to Fact Ledger...")
        page.click("a[href='/facts']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        facts_shot = os.path.join(SCREENSHOT_DIR, "06_facts.png")
        page.screenshot(path=facts_shot)
        print(f"  Captured Fact Ledger screenshot: {facts_shot}")

        # Step 7: Policies
        print("\n[7/10] Navigating to Policies...")
        page.click("a[href='/policies']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        
        # Test dry-run policy resolver
        dry_run_input = page.locator("textarea")
        if dry_run_input.count() > 0:
            dry_run_input.first.fill("What is the current price of OpenAI API?")
            page.locator("button:has-text('Resolve policy')").first.click()
            time.sleep(1)

        policies_shot = os.path.join(SCREENSHOT_DIR, "07_policies.png")
        page.screenshot(path=policies_shot)
        print(f"  Captured Policies screenshot: {policies_shot}")

        # Step 8: Costs & Latency
        print("\n[8/10] Navigating to Costs & Latency...")
        page.click("a[href='/costs']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        costs_shot = os.path.join(SCREENSHOT_DIR, "08_costs.png")
        page.screenshot(path=costs_shot)
        print(f"  Captured Costs & Latency screenshot: {costs_shot}")

        # Step 9: Evaluation Lab
        print("\n[9/10] Navigating to Evaluation Lab...")
        page.click("a[href='/eval']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        eval_shot = os.path.join(SCREENSHOT_DIR, "09_eval.png")
        page.screenshot(path=eval_shot)
        print(f"  Captured Evaluation Lab screenshot: {eval_shot}")

        # Step 10: Settings & Connection Checks
        print("\n[10/10] Navigating to Settings...")
        page.click("a[href='/settings']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        
        # Click Check connections button
        check_btn = page.locator("button:has-text('Check connections')")
        if check_btn.count() > 0:
            print("  Clicking 'Check connections'...")
            check_btn.click()
            time.sleep(3.5)

        settings_shot = os.path.join(SCREENSHOT_DIR, "10_settings.png")
        page.screenshot(path=settings_shot)
        print(f"  Captured Settings screenshot: {settings_shot}")

        # Check table contents
        connections_text = page.locator("section:has-text('Service connections')").inner_text()
        print("\nConnection Status Summary:")
        print(connections_text)

        browser.close()
        print("\nBrowser verification completed successfully! All screenshots saved.")

if __name__ == "__main__":
    run_browser_checks()

