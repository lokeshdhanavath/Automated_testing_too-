import re

from playwright.sync_api import Page


class TimesheetPage:
    """Page object for the Oracle APEX My Timesheet page."""

    URL_FRAGMENT = "my-timesheet"

    # ---------- Grid selectors ----------
    GRID = ".timesheet-grid"
    HOURS_INPUT = ".hours-input"
    PROJECT_NAME = ".project-name"
    PROJECT_NAME_CELL = ".project-name-cell"
    HOUR_CELL = ".hour-cell"
    PROJECT_TOTAL = ".project-total"
    DAILY_TOTAL_LABEL = ".daily-total-label"

    # ---------- Daily / weekly totals ----------
    WEEKLY_TOTAL = "#weekly_total"
    DAILY_TOTALS = {
        "mon": "#mon_total",
        "tue": "#tue_total",
        "wed": "#wed_total",
        "thu": "#thu_total",
        "fri": "#fri_total",
        "sat": "#sat_total",
        "sun": "#sun_total",
    }

    # ---------- Buttons ----------
    BTN_PREV_WEEK = "#p4-previous"
    BTN_CURRENT_WEEK = "#p4-current"
    BTN_NEXT_WEEK = "#p4-next"
    BTN_ADD_PROJECT = "#add_project_btn"
    BTN_SAVE = "#save"
    BTN_DELETE_PROJECT = "#delete_project_btn"

    # ---------- Add Project dialog ----------
    DIALOG_TITLE = "Select Project"
    DIALOG_SUBTITLE = "Choose a project assigned to you"
    DIALOG_CHEVRON = "›"

    # ---------- Days order ----------
    DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    # ---------- Week-date regex ----------
    DATE_RE = re.compile(r"\b\d{1,2}-[A-Za-z]{3}-\d{2}\b")

    def __init__(self, page: Page):
        self.page = page

    # =====================================================
    # Waits
    # =====================================================

    def wait_until_loaded(self, timeout: int = 30000):
        """Wait for the timesheet grid to be visible."""
        self.page.locator(self.GRID).wait_for(state="visible", timeout=timeout)
        return self

    def _current_week_dates_text(self) -> str:
        """Return the string of week dates currently shown, or ''."""
        try:
            body = self.page.locator("body").inner_text()
            matches = self.DATE_RE.findall(body)
            seen = []
            for m in matches:
                if m not in seen:
                    seen.append(m)
            return " ".join(seen[:10])
        except Exception:
            return ""

    def _wait_for_week_grid_reload(self, timeout_ms: int = 15000):
        """
        Wait until the grid is visible AND the body contains at least
        one date header like 12-Oct-26.
        """
        waited = 0
        step = 400
        while waited < timeout_ms:
            try:
                body = self.page.locator("body").inner_text()
                if self.DATE_RE.search(body) and self.page.locator(
                    self.GRID
                ).is_visible():
                    return self
            except Exception:
                pass
            self.page.wait_for_timeout(step)
            waited += step
        return self

    def _wait_for_dates_change(
        self, previous: str, timeout_ms: int = 15000
    ) -> str:
        """
        Wait until the week-date header text differs from `previous`.
        Returns the new date text (or the current one on timeout).
        """
        waited = 0
        step = 400
        while waited < timeout_ms:
            current = self._current_week_dates_text()
            if current and current != previous:
                return current
            self.page.wait_for_timeout(step)
            waited += step
        return self._current_week_dates_text()

    def select_current_week(self):
        """Click 'This Week' and wait for the grid to settle."""
        before = self._current_week_dates_text()
        self.page.locator(self.BTN_CURRENT_WEEK).click(no_wait_after=True)
        self._wait_for_dates_change(before, timeout_ms=5000)
        return self

    # =====================================================
    # Read-only queries
    # =====================================================

    def get_weekly_total(self) -> float:
        txt = self.page.locator(self.WEEKLY_TOTAL).inner_text().strip()
        return self._to_float(txt)

    def get_daily_total(self, day: str) -> float:
        selector = self.DAILY_TOTALS[day.lower()]
        txt = self.page.locator(selector).inner_text().strip()
        return self._to_float(txt)

    def get_all_totals(self) -> dict:
        totals = {}
        for day in self.DAYS:
            try:
                totals[day] = self.get_daily_total(day)
            except Exception:
                totals[day] = None
        try:
            totals["weekly"] = self.get_weekly_total()
        except Exception:
            totals["weekly"] = None
        return totals

    def count_projects(self) -> int:
        return self.page.locator(self.PROJECT_NAME).count()

    def count_hours_inputs(self) -> int:
        return self.page.locator(self.HOURS_INPUT).count()

    def count_project_rows(self) -> int:
        return self.page.locator(self.PROJECT_TOTAL).count()

    def is_grid_visible(self) -> bool:
        return self.page.locator(self.GRID).is_visible()

    def is_previous_week_visible(self) -> bool:
        return self.page.locator(self.BTN_PREV_WEEK).is_visible()

    def is_current_week_visible(self) -> bool:
        return self.page.locator(self.BTN_CURRENT_WEEK).is_visible()

    def is_next_week_visible(self) -> bool:
        return self.page.locator(self.BTN_NEXT_WEEK).is_visible()

    def current_week_dates(self) -> str:
        """Public accessor: return visible week date string."""
        return self._current_week_dates_text()

    # =====================================================
    # Week navigation
    # =====================================================

    def navigate_to_previous_week(self):
        """Go one week back. Waits until visible week dates actually change."""
        before = self._current_week_dates_text()
        self.page.locator(self.BTN_PREV_WEEK).click(no_wait_after=True)
        self._wait_for_dates_change(before)
        return self

    def navigate_to_next_week(self):
        """Go one week forward. Waits up to 5s for a change."""
        before = self._current_week_dates_text()
        self.page.locator(self.BTN_NEXT_WEEK).click(no_wait_after=True)
        self._wait_for_dates_change(before, timeout_ms=5000)
        return self

    def navigate_to_current_week(self):
        return self.select_current_week()

    def go_to_future_week(self):
        """Alias for readability in week-limit tests."""
        return self.navigate_to_next_week()

    # =====================================================
    # Add Project dialog
    # =====================================================

    def open_add_project_dialog(self):
        """Click '+ Add Project' and wait for the Select Project dialog."""
        self.page.locator(self.BTN_ADD_PROJECT).click(no_wait_after=True)
        self.page.wait_for_selector(
            f"text={self.DIALOG_TITLE}",
            timeout=15000,
        )
        self.page.wait_for_timeout(800)
        return self

    def project_dialog_visible(self) -> bool:
        try:
            return self.page.locator(
                f"text={self.DIALOG_TITLE}"
            ).first.is_visible()
        except Exception:
            return False

    def dialog_project_names(self) -> list:
        """Return the list of project names shown in the open dialog."""
        names = []
        try:
            handles = self.page.evaluate(
                """
                () => {
                    const out = [];
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT, null);
                    while (walker.nextNode()) {
                        const t = walker.currentNode.nodeValue || '';
                        if (!t.includes('›')) continue;
                        let el = walker.currentNode.parentElement;
                        for (let i = 0; i < 6 && el; i++) {
                            const txt = (el.innerText || '').trim();
                            if (txt && txt.length < 120
                                && txt.length > 2
                                && !txt.includes('Choose a project')) {
                                out.push(txt.split('\\n')[0].trim());
                                break;
                            }
                            el = el.parentElement;
                        }
                    }
                    return out;
                }
                """
            )
            for name in handles or []:
                if name and name not in names and len(name) < 80:
                    names.append(name)
        except Exception:
            pass

        return names[:10]

    def select_project_in_dialog(self, project_name: str):
        target = self.page.locator(f"text={project_name}").first
        target.wait_for(state="visible", timeout=15000)
        target.click(no_wait_after=True)
        self.page.wait_for_timeout(2000)
        return self

    def close_dialog(self):
        try:
            self.page.locator(
                "button:has-text('×'), [aria-label='Close'], "
                ".ui-dialog-titlebar-close"
            ).first.click(no_wait_after=True)
            self.page.wait_for_timeout(600)
        except Exception:
            pass
        return self

    # =====================================================
    # Buttons / capabilities
    # =====================================================

    def is_add_project_button_visible(self) -> bool:
        try:
            return self.page.locator(self.BTN_ADD_PROJECT).is_visible()
        except Exception:
            return False

    def is_save_button_visible(self) -> bool:
        try:
            return self.page.locator(self.BTN_SAVE).is_visible()
        except Exception:
            return False

    def is_delete_button_visible(self) -> bool:
        try:
            return self.page.locator(self.BTN_DELETE_PROJECT).is_visible()
        except Exception:
            return False

    # =====================================================
    # Row + hour operations (non-persistent — never call Save)
    # =====================================================

    def set_hours_in_row(self, row_index: int, day: str, value: str):
        day_index = self.DAYS.index(day.lower())
        inputs_per_row = 7
        global_index = row_index * inputs_per_row + day_index

        field = self.page.locator(self.HOURS_INPUT).nth(global_index)
        field.wait_for(state="visible", timeout=10000)
        field.click()
        field.fill("")
        if value != "":
            field.type(value, delay=30)
        field.press("Tab")
        self.page.wait_for_timeout(700)
        return self

    def read_hours_in_row(self, row_index: int, day: str) -> str:
        day_index = self.DAYS.index(day.lower())
        inputs_per_row = 7
        global_index = row_index * inputs_per_row + day_index
        try:
            return self.page.locator(
                self.HOURS_INPUT
            ).nth(global_index).input_value()
        except Exception:
            return "<unreadable>"

    def try_set_hours_first_input(self, value: str = "4") -> str:
        """
        Attempt to type into the first hour input on the current page.
        Returns the value read back from the field.
        If no hour input exists, returns '<no-input>'.
        Never clicks Save.
        """
        inputs = self.page.locator(self.HOURS_INPUT)
        if inputs.count() == 0:
            return "<no-input>"
        field = inputs.first
        field.click()
        field.fill("")
        field.type(value, delay=30)
        field.press("Tab")
        self.page.wait_for_timeout(700)
        return field.input_value()

    def clear_first_hours_input(self):
        """Clear the first hour input (cleanup, no save)."""
        try:
            field = self.page.locator(self.HOURS_INPUT).first
            field.click()
            field.fill("")
            field.press("Tab")
            self.page.wait_for_timeout(400)
        except Exception:
            pass
        return self

    def get_project_row_names(self) -> list:
        names = []
        try:
            cells = self.page.locator(
                ".project-name-cell, .project-name, td:first-child"
            ).all()
        except Exception:
            cells = []

        for cell in cells:
            try:
                txt = cell.inner_text().strip()
                first = txt.splitlines()[0] if txt else ""
                if first and first not in names and len(first) < 80:
                    names.append(first)
            except Exception:
                pass
        return names

    # =====================================================
    # Helpers
    # =====================================================

    @staticmethod
    def _to_float(text: str) -> float:
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        return float(cleaned) if cleaned else 0.0