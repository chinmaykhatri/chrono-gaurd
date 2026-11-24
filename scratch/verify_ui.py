from pathlib import Path
import asyncio
from playwright.async_api import async_playwright

ADMIN_PW = (Path(__file__).resolve().parents[1] / "chronoguard" / ".admin-password").read_text(encoding="utf-8").strip()
BASE_URL = "http://127.0.0.1:5175"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        print("Navigating to console...")
        await page.goto(BASE_URL)
        await asyncio.sleep(1.0)

        # Check if on login page
        password_input = await page.query_selector('input[type="password"]')
        if password_input:
            print("Logging in with admin key...")
            await password_input.fill(ADMIN_PW)
            await page.click('button:has-text("Sign in")')
            await asyncio.sleep(2.0)

        print("Current URL:", page.url)
        await page.screenshot(path="screenshots/overview_with_probe.png")

        # Click the "Run Invalidation Probe" button
        probe_button = await page.query_selector('button:has-text("Run Invalidation Probe")')
        if probe_button:
            print("Clicking 'Run Invalidation Probe' button...")
            await probe_button.click()
            # Wait for probe result
            await page.wait_for_selector('text=VERIFIED HEALTHY', timeout=10000)
            print("Probe verified successfully!")
            await asyncio.sleep(1.0)
            await page.screenshot(path="screenshots/probe_verified.png")
        else:
            print("Probe button not found!")

        # Navigate to /feed
        print("Navigating to /feed...")
        await page.goto(f"{BASE_URL}/feed")
        await asyncio.sleep(1.5)

        # Click first Trace button if available
        trace_button = await page.query_selector('button:has-text("Trace")')
        if trace_button:
            print("Opening request lifecycle trace...")
            await trace_button.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path="screenshots/feed_lifecycle.png")
            print("Lifecycle screenshot saved.")
        else:
            print("No trace buttons on feed yet.")

        # Navigate to /cache
        print("Navigating to /cache...")
        await page.goto(f"{BASE_URL}/cache")
        await asyncio.sleep(1.5)
        # Click on first cached answer if available
        cache_link = await page.query_selector('table[data-table="cache"] tbody tr a')
        if cache_link:
            print("Opening cache detail...")
            await cache_link.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path="screenshots/cache_detail_diff.png")
            print("Cache detail screenshot saved.")

        await browser.close()
        print("All browser checks completed successfully!")

if __name__ == "__main__":
    asyncio.run(run())

