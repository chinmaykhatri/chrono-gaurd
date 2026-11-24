from pathlib import Path
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        c = await b.new_context(viewport={'width': 1400, 'height': 900})
        page = await c.new_page()
        await page.goto('http://127.0.0.1:5175/')
        pw = await page.query_selector('input[type="password"]')
        if pw:
            await pw.fill((Path(__file__).resolve().parents[1] / "chronoguard" / ".admin-password").read_text(encoding="utf-8").strip())
            await page.click('button:has-text("Sign in")')
            await asyncio.sleep(1.5)
        await page.goto('http://127.0.0.1:5175/cache/cache-py-django')
        await asyncio.sleep(2.0)
        await page.screenshot(path='screenshots/cache_detail_diff.png')
        await b.close()
        print('Captured cache detail diff screenshot')

if __name__ == '__main__':
    asyncio.run(main())

