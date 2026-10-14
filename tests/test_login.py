"""
Read-only login and navigation tests.
No data is modified by any test in this file.
"""
from playwright.sync_api import expect

from pages.login_page import LoginPage
from pages.timesheet_page import TimesheetPage
from utils import config


def test_login_page_loads(page):
    lp = LoginPage(page).open()
    expect(page.locator(lp.USERNAME)).to_be_visible()
    expect(page.locator(lp.PASSWORD)).to_be_visible()
    expect(page.locator(lp.SIGN_IN)).to_be_visible()


def test_login_with_valid_credentials(page):
    LoginPage(page).open().login()
    assert "/login" not in page.url, f"Still on login page: {page.url}"


def test_navigate_to_my_timesheet(page):
    LoginPage(page).open().login().open_timesheet()
    assert "my-timesheet" in page.url, f"URL: {page.url}"

    tp = TimesheetPage(page)
    tp.wait_until_loaded()
    assert tp.is_grid_visible()


def test_weekly_total_is_visible(page):
    LoginPage(page).open().login().open_timesheet()
    tp = TimesheetPage(page)
    tp.wait_until_loaded()

    total = tp.get_weekly_total()
    print(f"Weekly total: {total}")
    assert total >= 0, "Weekly total should be a non-negative number"


def test_week_navigation_controls_present(page):
    LoginPage(page).open().login().open_timesheet()
    tp = TimesheetPage(page)
    tp.wait_until_loaded()

    assert tp.is_previous_week_visible(), "Previous week button not visible"
    assert tp.is_next_week_visible(), "Next week button not visible"