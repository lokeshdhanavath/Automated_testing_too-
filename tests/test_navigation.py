"""
Week navigation tests (READ-ONLY).

The app ALLOWS navigation forward and backward. Only the ability to
log hours is restricted to past + current weeks.

Verified behaviors:
  - Previous Week changes the week dates (backward navigation works)
  - Current Week restores today's week
  - Next Week advances the week (forward navigation works)
  - The grid remains visible after every navigation

Data is never modified.
"""
import re

from pages.timesheet_page import TimesheetPage

DATE_PATTERN = re.compile(r"\b\d{1,2}-[A-Za-z]{3}-\d{2}\b")


def _read_week_dates(page) -> str:
    body = page.locator("body").inner_text()
    matches = DATE_PATTERN.findall(body)
    seen = []
    for m in matches:
        if m not in seen:
            seen.append(m)
    return " ".join(seen[:10])


def test_previous_week_changes_dates(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    before = tp.current_week_dates()
    print(f"\n[before] dates: {before}")

    tp.navigate_to_previous_week()
    after = tp.current_week_dates()
    print(f"[after prev] dates: {after}")

    assert before != after, "Previous Week did not change the week dates"
    assert page.locator(TimesheetPage.GRID).is_visible()


def test_current_week_returns_to_today(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    original = tp.current_week_dates()
    print(f"\n[original] dates: {original}")

    tp.navigate_to_previous_week()
    tp.navigate_to_current_week()
    restored = tp.current_week_dates()
    print(f"[restored] dates: {restored}")

    assert restored == original, (
        f"Current Week did not restore original dates.\n"
        f"original: {original}\nrestored: {restored}"
    )


def test_next_week_advances_dates(timesheet_page_in_session):
    """The app DOES allow navigating to next week (view only)."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    before = tp.current_week_dates()
    print(f"\n[before] dates: {before}")

    tp.navigate_to_next_week()
    after = tp.current_week_dates()
    print(f"[after next] dates: {after}")

    assert before != after, (
        f"Next Week should advance the calendar.\n"
        f"before: {before}\nafter:  {after}"
    )
    # Grid must still be visible even in the future week
    assert page.locator(TimesheetPage.GRID).is_visible()


def test_grid_remains_visible_after_navigation(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_previous_week()
    assert page.locator(TimesheetPage.GRID).is_visible()

    tp.navigate_to_current_week()
    assert page.locator(TimesheetPage.GRID).is_visible()

    tp.navigate_to_next_week()
    assert page.locator(TimesheetPage.GRID).is_visible()


def test_week_buttons_all_present(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    assert tp.is_previous_week_visible()
    assert tp.is_current_week_visible()
    assert tp.is_next_week_visible()