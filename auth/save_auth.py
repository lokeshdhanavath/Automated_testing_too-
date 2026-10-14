"""
One-time setup: log in to APEX and save the authenticated browser state
(cookies + localStorage) to auth/apex_state.json.

Run this manually whenever:
  - credentials change
  - the saved state expires (typically ~hours)

Usage:
    python auth/save_auth.py
"""
import sys
from pathlib import Path

# Add project root to path so 'utils' and 'pages' can be imported
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from utils import config
from pages.login_page import LoginPage

AUTH_DIR = ROOT / "auth"
AUTH_DIR.mkdir(exist_ok=True)
STATE_PATH = AUTH_DIR / "apex_state.json"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
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

        print("Logging in to save authenticated state...")
        LoginPage(page).open().login()
        print("Login succeeded. URL:", page.url)

        # Save cookies + localStorage for reuse in tests
        context.storage_state(path=str(STATE_PATH))
        print("Saved auth state:", STATE_PATH)

        context.close()
        browser.close()


if __name__ == "__main__":
    main()