"""
Cleanup: delete any rows in the current week.

Tries several ways to select a row (checkbox → radio → row click → row
wrapper click → focus via JS), then clicks Delete, confirms the popup,
and waits for auto-refresh. No Save button involved.

Usage:
    python cleanup_now.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from urllib.parse import urlparse, parse_qs

from utils import config
from pages.login_page import LoginPage
from pages.timesheet_page import TimesheetPage


SELECTION_ATTEMPTS = [
    # 1. Checkbox in the grid
    ("checkbox in grid", lambda page: page.locator(
        ".timesheet-grid input[type='checkbox']").first.check()),
    # 2. Radio in the grid
    ("radio in grid", lambda page: page.locator(
        ".timesheet-grid input[type='radio']").first.check()),
    # 3. APEX row selector
    ("APEX row selector", lambda page: page.locator(
        ".timesheet-grid .a-GV-row-selector, .timesheet-grid td.a-GV-selector")
        .first.click()),
    # 4. Click the project cell (the row)
    ("project cell", lambda page: page.locator(
        ".project-name-cell, .project-name").first.click()),
    # 5. Click the row wrapper via JS (find the tr/div[role=row] above cell)
    ("row wrapper via JS", lambda page: page.evaluate(
        """
        () => {
            const cell = document.querySelector('.project-name');
            if (!cell) return false;
            let el = cell;
            for (let i = 0; i < 8 && el; i++) {
                if (el.tagName === 'TR'
                    || (el.getAttribute && el.getAttribute('role') === 'row')) {
                    el.click();
                    return true;
                }
                el = el.parentElement;
            }
            return false;
        }
        """)),
]


def _try_select(page) -> bool:
    for label, fn in SELECTION_ATTEMPTS:
        try:
            fn(page)
            page.wait_for_timeout(600)
            print(f"    selected via: {label}")
            return True
        except Exception as e:
            print(f"    {label} failed: {type(e).__name__}")
    return False


def _confirm_popup(page, timeout_ms=4000) -> bool:
    waited = 0
    while waited < timeout_ms:
        for sel in [
            ".ui-dialog button:has-text('OK')",
            ".a-Dialog button:has-text('OK')",
            "button:has-text('OK')",
            "button:has-text('Yes')",
            "button:has-text('Confirm')",
            "button:has-text('Delete')",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(no_wait_after=True)
                    print(f"    confirmed: {sel}")
                    page.wait_for_timeout(2500)
                    return True
            except Exception:
                pass
        page.wait_for_timeout(300)
        waited += 300
    return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1500, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        print("[1] Login...")
        LoginPage(page).open().login()
        qs = parse_qs(urlparse(page.url).query)
        session_token = (qs.get("session") or [""])[0]

        print("[2] Go to My Timesheet / current week...")
        page.goto(
            f"{config.BASE_URL}/my-timesheet1?session={session_token}",
            wait_until="load", timeout=60000,
        )
        page.locator("#p4-current").click(no_wait_after=True)
        page.wait_for_timeout(3000)
        tp = TimesheetPage(page)
        tp.wait_until_loaded()

        rows = tp.count_project_rows()
        print(f"[2] rows on entry: {rows}")
        if rows == 0:
            print("[done] Already clean.")
            context.close(); browser.close(); return

        # ---------- Delete each row ----------
        for i in range(rows):
            print(f"\n[3] Deleting row {i+1}/{rows}")

            if not _try_select(page):
                print("    [fail] no selection worked")
                break

            print("    clicking #delete_project_btn...")
            try:
                page.locator("#delete_project_btn").click(no_wait_after=True)
            except Exception as e:
                print(f"    delete click failed: {e}")
                break

            page.wait_for_timeout(1200)

            # If nothing happened, a popup ("select a row first") may have shown.
            # Detect and dismiss it, then try a JS-forced selection.
            body = page.locator("body").inner_text()
            if "select a project row" in body.lower():
                print("    popup says: select a project row first — "
                      "trying JS row selection")
                _confirm_popup(page)
                # Try again with JS
                try:
                    page.evaluate(
                        """
                        () => {
                            const cell = document.querySelector('.project-name');
                            let el = cell;
                            for (let i = 0; i < 10 && el; i++) {
                                if (el.tagName === 'TR'
                                    || el.getAttribute?.('role') === 'row') {
                                    el.click();
                                    el.dispatchEvent(new MouseEvent('mousedown',
                                        {bubbles: true}));
                                    el.dispatchEvent(new MouseEvent('mouseup',
                                        {bubbles: true}));
                                    return true;
                                }
                                el = el.parentElement;
                            }
                            return false;
                        }
                        """
                    )
                    page.wait_for_timeout(800)
                    page.locator("#delete_project_btn").click(no_wait_after=True)
                    page.wait_for_timeout(1200)
                except Exception:
                    pass

            _confirm_popup(page)

            # Wait for row count to drop (up to 12s)
            for _ in range(24):
                if tp.count_project_rows() < rows - i:
                    break
                page.wait_for_timeout(500)

            print(f"    rows now: {tp.count_project_rows()}")
            if tp.count_project_rows() == 0:
                break

        # ---------- Verify ----------
        print("\n[5] Reload and verify...")
        page.goto(
            f"{config.BASE_URL}/my-timesheet1?session={session_token}",
            wait_until="load", timeout=60000,
        )
        page.locator("#p4-current").click(no_wait_after=True)
        page.wait_for_timeout(3000)
        tp.wait_until_loaded()

        final_rows = tp.count_project_rows()
        print(f"[5] rows after reload: {final_rows}")

        page.screenshot(
            path=str(config.SCREENSHOT_DIR / "cleanup_final.png"),
            full_page=True,
        )
        if final_rows == 0:
            print("\n[done] Grid is clean. ✅")
        else:
            print(f"\n[warn] {final_rows} row(s) still present.")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()