from playwright.sync_api import Page, Locator

from utils import config


class LoginPage:
    """Page object for login authentication (supports Oracle APEX, Oracle Cloud IDCS, and generic login forms)."""

    NAV_MENU = "#t_Button_navControl"
    MY_TIMESHEET_LINK = "a.a-TreeView-label"

    def __init__(self, page: Page):
        self.page = page

    def get_username_locator(self) -> Locator:
        # 1. Oracle Cloud / IDCS
        loc = self.page.get_by_role("textbox", name="Username")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
        # 2. Oracle APEX
        loc = self.page.locator("#P9999_USERNAME")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
        # 3. Generic inputs
        for sel in [
            "input[id*='signin-form-username']",
            "input[name='username']",
            "input[name='user']",
            "input[type='email']",
            "#username",
        ]:
            loc = self.page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        # Fallback to get_by_role or APEX
        if self.page.get_by_role("textbox", name="Username").count() > 0:
            return self.page.get_by_role("textbox", name="Username").first
        return self.page.locator("#P9999_USERNAME").first

    def get_password_locator(self) -> Locator:
        # 1. Oracle Cloud / IDCS
        loc = self.page.get_by_role("textbox", name="Password")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
        # 2. Oracle APEX
        loc = self.page.locator("#P9999_PASSWORD")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
        # 3. Generic inputs
        for sel in [
            "input[id*='signin-form-password']",
            "input[name='password']",
            "input[type='password']",
            "#password",
        ]:
            loc = self.page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        if self.page.get_by_role("textbox", name="Password").count() > 0:
            return self.page.get_by_role("textbox", name="Password").first
        return self.page.locator("#P9999_PASSWORD").first

    def get_signin_locator(self) -> Locator:
        # 1. Oracle Cloud / IDCS
        for name in ["Next", "Sign In", "Sign in"]:
            loc = self.page.get_by_role("button", name=name)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        # 2. Oracle APEX
        loc = self.page.locator("#B39857664851513779045")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
        # 3. Generic buttons
        for sel in [
            "button[type='submit']",
            "input[type='submit']",
            "#B9999_LOGIN",
            "button:has-text('Sign In')",
        ]:
            loc = self.page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        return self.page.locator("#B39857664851513779045, button[type='submit']").first

    @property
    def USERNAME(self):
        return self.get_username_locator()

    @property
    def PASSWORD(self):
        return self.get_password_locator()

    @property
    def SIGN_IN(self):
        return self.get_signin_locator()

    def open(self):
        target_url = config.LOGIN_URL or config.BASE_URL
        self.page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        try:
            self.page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass

        # Wait until the login form (either APEX or Oracle Cloud IDCS) is rendered and visible
        deadline = 30000
        step = 500
        elapsed = 0
        while elapsed < deadline:
            u_loc = self.page.get_by_role("textbox", name="Username")
            if u_loc.count() > 0 and u_loc.first.is_visible():
                break
            apex_loc = self.page.locator("#P9999_USERNAME")
            if apex_loc.count() > 0 and apex_loc.first.is_visible():
                break
            self.page.wait_for_timeout(step)
            elapsed += step

        # Give widgets time to finish wiring up
        self.page.wait_for_timeout(1000)
        return self

    def login(self, username: str = None, password: str = None):
        username = username if username is not None else config.USERNAME
        password = password if password is not None else config.PASSWORD

        u_loc = self.get_username_locator()
        p_loc = self.get_password_locator()
        b_loc = self.get_signin_locator()

        u_loc.fill(username)
        p_loc.fill(password)
        self.page.wait_for_timeout(400)
        b_loc.click()

        self.page.wait_for_timeout(3000)
        return self

    def open_timesheet(self):
        """Open the nav menu and click 'My Timesheet'."""
        self.page.locator(self.NAV_MENU).click(no_wait_after=True)
        self.page.wait_for_timeout(1200)

        link = self.page.locator(self.MY_TIMESHEET_LINK, has_text="My Timesheet").first
        link.wait_for(state="visible", timeout=15000)
        link.click(no_wait_after=True)

        deadline_ms = 30000
        step = 500
        waited = 0
        while waited < deadline_ms:
            if "my-timesheet" in self.page.url:
                return self
            self.page.wait_for_timeout(step)
            waited += step

        raise AssertionError(f"Did not reach My Timesheet. URL: {self.page.url}")
