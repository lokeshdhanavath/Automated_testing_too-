import os
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.getenv("APEX_BASE_URL").rstrip("/")
USERNAME = os.getenv("APEX_USERNAME")
PASSWORD = os.getenv("APEX_PASSWORD")

LOGIN_URL = f"{BASE_URL}/login"
SHOT_DIR = Path("screenshots"); SHOT_DIR.mkdir(exist_ok=True)

with sync_playwright() as p:
    # Use a FRESH, temporary profile every run so no stale session interferes
    browser = p.chromium.launch(
        headless=False,
        slow_mo=300,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1400, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(30000)

    # Log all network requests so we can see if the login POST happens
    page.on("request", lambda req: print("REQ>", req.method, req.url)
            if "ords" in req.url and req.resource_type in ("xhr", "fetch", "document")
            else None)
    page.on("response", lambda res: print("RES>", res.status, res.url)
            if "ords" in res.url and res.request.resource_type in ("xhr", "fetch", "document")
            else None)

    # Log console errors from APEX
    page.on("console", lambda msg: print("CONSOLE>", msg.type, msg.text)
            if msg.type in ("error", "warning") else None)

    print("Opening login page...")
    page.goto(LOGIN_URL, wait_until="load", timeout=60000)

    # Wait for the APEX page to be REALLY ready
    print("Waiting for APEX to finish initializing...")
    page.wait_for_selector("#P9999_USERNAME", state="visible", timeout=30000)
    page.wait_for_timeout(3000)   # give APEX widgets time to wire up

    # Check for any visible spinner or overlay
    spinner_count = page.locator(".apex-loading, .u-Processing, .a-Processing").count()
    print(f"Visible spinners/overlays at start: {spinner_count}")

    print("Filling credentials via fill() ...")
    page.locator("#P9999_USERNAME").fill(USERNAME)
    page.locator("#P9999_PASSWORD").fill(PASSWORD)
    page.wait_for_timeout(1000)

    # Verify the values were actually set
    u_val = page.locator("#P9999_USERNAME").input_value()
    p_len = len(page.locator("#P9999_PASSWORD").input_value())
    print(f"Username field contains: {u_val!r}")
    print(f"Password field length: {p_len}")

    print("Clicking Sign In. Watch the browser NOW.")
    page.locator("#B39857664851513779045").click()

    # Keep open for up to 60s, printing status
    for i in range(20):
        page.wait_for_timeout(3000)
        url = page.url
        busy = page.locator(".apex-loading, .u-Processing, .a-Processing").count()
        print(f"[{i*3}s] URL={url} | visible_spinners={busy}")

    context.close()
    browser.close()