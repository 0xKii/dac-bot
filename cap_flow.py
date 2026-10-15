#!/usr/bin/env python3
"""cap_flow.py — browser mode: refresh game session (CAP) + daily check-in.
Run under: xvfb-run -a /usr/bin/python3 cap_flow.py
Writes result JSON to flow_result.json."""
import asyncio, json, sys
from playwright.async_api import async_playwright

SESSION_ID = open("/root/dac-bot/session.txt").read().strip()
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
BASE = "https://interstellar.dachain.io"
RESULT = {"game_session": None, "checkin": None, "error": None}

async def main():
    events = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome", headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900})
        await ctx.add_cookies([{"name": "sessionid", "value": SESSION_ID,
                                "domain": "interstellar.dachain.io", "path": "/"}])
        page = await ctx.new_page()

        async def on_resp(r):
            u = r.url
            if u.endswith("/api/v1/game/session/") and r.request.method == "POST":
                try:
                    body = json.loads(await r.text())
                    RESULT["game_session"] = body.get("data", {}).get("until") or body.get("error", {}).get("code")
                except Exception:
                    pass
            if u.endswith("/api/v1/checkin/") and r.request.method == "POST":
                try:
                    body = json.loads(await r.text())
                    RESULT["checkin"] = "OK" if body.get("success") else body.get("error", {}).get("code")
                except Exception:
                    RESULT["checkin"] = "parse_err"
        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        # 1) game session refresh (CAP auto-solves on /game/)
        try:
            await page.goto(f"{BASE}/game/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(16000)
        except Exception as e:
            RESULT["error"] = f"game goto: {str(e)[:100]}"

        # 2) daily check-in on landing
        try:
            await page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(9000)
            for sel in ["text=CHECK IN · +10 QE", "button:has-text('CHECK IN')", "text=CHECK IN"]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2500):
                        await el.click(timeout=6000)
                        break
                except Exception:
                    continue
            await page.wait_for_timeout(22000)  # CAP PoW + POST
        except Exception as e:
            RESULT["error"] = (RESULT["error"] or "") + f" | checkin: {str(e)[:100]}"

        await browser.close()

    with open("/root/dac-bot/flow_result.json", "w") as f:
        json.dump(RESULT, f, indent=1)
    print(json.dumps(RESULT))

asyncio.run(main())
