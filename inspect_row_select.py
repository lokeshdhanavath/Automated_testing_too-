"""
Inspect how a project row is 'selected' for deletion.
Read-only — never clicks Delete.
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


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(viewport={"width": 1500, "height": 900})
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

        print(f"\n[3] rows: {tp.count_project_rows()}")

        # ---------- Look at the row structure ----------
        print("\n=== Row wrappers around .project-name ===")
        page.evaluate(
            """
            () => {
                const rows = document.querySelectorAll('.project-name');
                for (let i = 0; i < rows.length; i++) {
                    let el = rows[i];
                    for (let up = 0; up < 6 && el; up++) {
                        if (el.tagName === 'TR' || el.tagName === 'DIV'
                            && el.getAttribute('role') === 'row') {
                            console.log('ROW HTML:', el.outerHTML.slice(0, 500));
                            break;
                        }
                        el = el.parentElement;
                    }
                }
            }
            """
        )

        # ---------- Dump every clickable thing inside the grid ----------
        print("\n=== Everything inside the grid (tags + classes) ===")
        info = page.evaluate(
            """
            () => {
                const grid = document.querySelector('.timesheet-grid');
                if (!grid) return [];
                const out = [];
                const walk = (el, depth) => {
                    if (depth > 6) return;
                    const tag = el.tagName.toLowerCase();
                    const cls = (el.className || '').toString().slice(0, 80);
                    const attrs = [];
                    for (const a of ['id', 'name', 'type', 'role', 'aria-checked',
                                     'aria-selected', 'tabindex', 'onclick']) {
                        const v = el.getAttribute(a);
                        if (v) attrs.push(a + '=' + v);
                    }
                    out.push('  '.repeat(depth) + `<${tag}> `
                             + (cls ? `class="${cls}" ` : '')
                             + (attrs.length ? attrs.join(' ') : ''));
                    for (const c of el.children) walk(c, depth + 1);
                };
                walk(grid, 0);
                return out;
            }
            """
        )
        for line in info[:200]:
            print(line)

        # ---------- Look for inputs, radios, checkboxes ----------
        print("\n=== Inputs inside grid ===")
        for sel in [
            ".timesheet-grid input[type='checkbox']",
            ".timesheet-grid input[type='radio']",
            ".timesheet-grid input",
            ".timesheet-grid [role='checkbox']",
            ".timesheet-grid [role='radio']",
            ".timesheet-grid [aria-checked]",
            ".timesheet-grid tr[aria-selected]",
            ".timesheet-grid tbody tr",
            ".timesheet-grid .select-row",
            ".timesheet-grid .row-selector",
            ".timesheet-grid .a-GV-row-selector",
        ]:
            try:
                loc = page.locator(sel)
                c = loc.count()
                if c:
                    print(f"  {sel:50s} count={c}")
            except Exception:
                pass

        print("\n[done] Browser stays open 90s so you can look.")
        page.wait_for_timeout(90000)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()