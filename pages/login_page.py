from playwright.sync_api import Page

from utils import config


class LoginPage:
    """Page object for the Oracle APEX login page."""

    USERNAME = "#P9999_USERNAME"
    PASSWORD = "#P9999_PASSWORD"
    SIGN_IN = "#B39857664851513779045"
    NAV_MENU = "#t_Button_navControl"
    MY_TIMESHEET_LINK = "a.a-TreeView-label"

    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto(config.LOGIN_URL, wait_until="load", timeout=60000)
        self.page.wait_for_selector(self.USERNAME, state="visible", timeout=30000)
        # Give APEX widgets time to finish wiring up
        self.page.wait_for_timeout(3000)
        return self

    def login(self, username: str = None, password: str = None):
        username = username if username is not None else config.USERNAME
        password = password if password is not None else config.PASSWORD

        self.page.locator(self.USERNAME).fill(username)
        self.page.locator(self.PASSWORD).fill(password)
        self.page.wait_for_timeout(400)
        self.page.locator(self.SIGN_IN).click()

        # Wait until we leave /login (success)
        self.page.wait_for_timeout(3000)
        if "/login" in self.page.url:
            raise AssertionError(
                f"Login did not redirect. Still at: {self.page.url}"
            )
        return self

    def open_timesheet(self):
        """Open the nav menu and click 'My Timesheet'."""
        self.page.locator(self.NAV_MENU).click(no_wait_after=True)
        self.page.wait_for_timeout(1200)

        link = self.page.locator(self.MY_TIMESHEET_LINK, has_text="My Timesheet").first
        link.wait_for(state="visible", timeout=15000)
        link.click(no_wait_after=True)

        # Wait for the URL to contain my-timesheet
        deadline_ms = 30000
        step = 500
        waited = 0
        while waited < deadline_ms:
            if "my-timesheet" in self.page.url:
                return self
            self.page.wait_for_timeout(step)
            waited += step

        raise AssertionError(f"Did not reach My Timesheet. URL: {self.page.url}")