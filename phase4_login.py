import os
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.getenv("APEX_BASE_URL").rstrip("/")
USERNAME = os.getenv("APEX_USERNAME")
PASSWORD = os.getenv("APEX_PASSWORD")

assert BASE_URL and USERNAME and PASSWORD, "Missing credentials in .env"

LOGIN_URL = f"{BASE_URL}/login"

VIDEO_DIR = Path("videos"); VIDEO_DIR.mkdir(exist_ok=True)
SHOT_DIR = Path("screenshots"); SHOT_DIR.mkdir(exist_ok=True)


def wait_for_url_contains(page, fragment, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fragment in page.url:
            return True
        page.wait_for_timeout(500)
    return False


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1400, "height": 900},
        record_video_dir=str(VIDEO_DIR),
        record_video_size={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(30000)

    # ---------- LOGIN ----------
    print("Opening login page...")
    page.goto(LOGIN_URL, wait_until="load", timeout=60000)
    page.wait_for_selector("#P9999_USERNAME", state="visible", timeout=30000)
    page.wait_for_timeout(3000)   # let APEX widgets finish wiring up

    print("Filling credentials...")
    page.locator("#P9999_USERNAME").fill(USERNAME)
    page.locator("#P9999_PASSWORD").fill(PASSWORD)
    page.wait_for_timeout(500)

    print("Clicking Sign In...")
    page.locator("#B39857664851513779045").click()

    if not wait_for_url_contains(page, "/home", timeout=30):
        print("Login did not reach /home. Current URL:", page.url)
        context.close(); browser.close()
        raise SystemExit("Login failed.")

    print("After login URL:", page.url)
    page.wait_for_timeout(2000)

    # ---------- OPEN NAV MENU ----------
    print("Opening navigation menu...")
    page.locator("#t_Button_navControl").click(no_wait_after=True)
    page.wait_for_timeout(1500)

    # ---------- CLICK MY TIMESHEET ----------
    print("Clicking My Timesheet...")
    menu_link = page.locator("a.a-TreeView-label", has_text="My Timesheet").first
    menu_link.wait_for(state="visible", timeout=15000)
    menu_link.click(no_wait_after=True)

    print("Waiting for my-timesheet URL...")
    if not wait_for_url_contains(page, "my-timesheet", timeout=30):
        print("Still on:", page.url)
        context.close(); browser.close()
        raise SystemExit("Did not reach My Timesheet.")

    page.wait_for_timeout(3000)
    print("My Timesheet URL:", page.url)

    # ---------- VERIFY GRID ----------
    page.locator(".timesheet-grid").wait_for(state="visible", timeout=30000)
    print("Grid visible OK")

    weekly_total = page.locator("#weekly_total").inner_text()
    print("Weekly total:", weekly_total)

    page.screenshot(path=str(SHOT_DIR / "phase4_my_timesheet.png"), full_page=True)
    print("Screenshot saved: screenshots/phase4_my_timesheet.png")

    video = page.video
    context.close()
    browser.close()

    print("Video:", video.path())