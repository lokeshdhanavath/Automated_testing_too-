"""
Week-limit behavior tests (READ-ONLY relative to the database).

The app's real rules:
  - Past weeks: navigation works; hours CAN be logged.
  - Current week: navigation works; hours CAN be logged.
  - Future weeks: navigation works; Add Project works, BUT hours
    CANNOT be logged.

We verify those rules. We NEVER click Save, so no data is written.

Each test navigates back to the current week when it finishes.
"""
from pages.timesheet_page import TimesheetPage


def _goto_current_week_clean(tp: TimesheetPage):
    """Reset to the current week at the end of a test."""
    try:
        tp.navigate_to_current_week()
    except Exception:
        pass


# =====================================================================
# Future week: Add Project is allowed
# =====================================================================

def test_future_week_allows_add_project_button(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_next_week()
    print(f"\n[future] url: {page.url}")
    print(f"[future] add_project_btn visible: {tp.is_add_project_button_visible()}")

    assert tp.is_add_project_button_visible(), (
        "Add Project button should be visible in a future week"
    )

    _goto_current_week_clean(tp)


def test_future_week_allows_adding_row(timesheet_page_in_session):
    """Add Project dialog works in a future week; a row appears."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_next_week()

    before_inputs = tp.count_hours_inputs()
    print(f"\n[future] hours inputs before add: {before_inputs}")

    # Add a project row (do NOT save)
    tp.open_add_project_dialog()
    tp.select_project_in_dialog("DM project")
    page.wait_for_timeout(1500)

    after_inputs = tp.count_hours_inputs()
    print(f"[future] hours inputs after add:  {after_inputs}")

    # Add Project should have succeeded
    assert after_inputs >= 7, (
        f"Expected a row with >=7 hour inputs to appear; got {after_inputs}"
    )

    _goto_current_week_clean(tp)


# =====================================================================
# Future week: hours CANNOT be logged
# =====================================================================

def test_future_week_blocks_hour_entry(timesheet_page_in_session):
    """
    In a future week, typing into an hour input should not persist.
    Depending on the app, either:
      - no hour inputs exist at all, or
      - typing is ignored / cleared.
    """
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_next_week()

    # Ensure a row exists so we can test hour input behavior
    if tp.count_hours_inputs() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)

    typed_value = tp.try_set_hours_first_input("4")
    print(f"\n[future] typed '4', field now reads: {typed_value!r}")

    # In future weeks, either input doesn't exist or value should not stick
    assert typed_value in ("<no-input>", "", "0"), (
        f"Future week should not accept hours; field kept {typed_value!r}"
    )

    _goto_current_week_clean(tp)


def test_current_week_accepts_hour_entry(timesheet_page_in_session):
    """Control test: current week DOES accept hours (to prove our check is valid)."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    # Fixture already put us on current week + clicked This Week.
    if tp.count_hours_inputs() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)

    typed_value = tp.try_set_hours_first_input("4")
    print(f"\n[current] typed '4', field now reads: {typed_value!r}")

    # Current week accepts hours, so it should read back as 4
    assert typed_value in ("4", "4.0"), (
        f"Current week should accept hour '4'; field reads {typed_value!r}"
    )

    # Restore: clear the field so nothing lingers
    try:
        field = page.locator(tp.HOURS_INPUT).first
        field.click()
        field.fill("")
        field.press("Tab")
        page.wait_for_timeout(500)
    except Exception:
        pass


def test_past_week_accepts_hour_entry(timesheet_page_in_session):
    """Past weeks DO allow hour entry (per the app's real rule)."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_previous_week()
    if tp.count_hours_inputs() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)

    typed_value = tp.try_set_hours_first_input("3")
    print(f"\n[past] typed '3', field now reads: {typed_value!r}")

    assert typed_value in ("3", "3.0"), (
        f"Past week should accept hours; field reads {typed_value!r}"
    )

    # Clean up this test's input without saving
    try:
        field = page.locator(tp.HOURS_INPUT).first
        field.click()
        field.fill("")
        field.press("Tab")
        page.wait_for_timeout(500)
    except Exception:
        pass

    _goto_current_week_clean(tp)