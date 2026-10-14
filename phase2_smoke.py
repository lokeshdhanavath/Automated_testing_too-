from pathlib import Path
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://oracleapex.com/ords/r/lokesh354/timesheet-application/login"
SHOT_DIR = Path("screenshots")
SHOT_DIR.mkdir(exist_ok=True)
SHOT = SHOT_DIR / "phase2_login_page.png"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)   # visible browser
    context = browser.new_context()
    page = context.new_page()

    print("Opening:", LOGIN_URL)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

    page.wait_for_timeout(3000)  # let APEX finish rendering

    print("Page title:", page.title())
    print("URL:", page.url)

    page.screenshot(path=str(SHOT), full_page=True)
    print("Screenshot saved:", SHOT.resolve())

    browser.close()