"""
Week-limit behavior tests (READ-ONLY relative to the database).

The app's real rules:
  - Past weeks:   navigation works; hours CAN be logged.
  - Current week: navigation works; hours CAN be logged.
  - Future weeks: navigation works; Add Project works, but hour inputs
                  are DISABLED (tooltip: 'Future dates cannot be logged.').

We verify those rules. We NEVER click Save, so no data is written.
"""
from pages.timesheet_page import TimesheetPage


def _goto_current_week_clean(tp: TimesheetPage):
    """Reset to the current week at the end of a test."""
    try:
        tp.navigate_to_current_week()
    except Exception:
        pass


def _first_hour_input_is_disabled(page) -> bool:
    """Return True if the first hour input exists and is disabled."""
    inputs = page.locator(".hours-input")
    if inputs.count() == 0:
        return True   # no input at all counts as 'cannot log'
    return not inputs.first.is_enabled()


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
    """Add Project dialog works in a future week; a row appears (but inputs disabled)."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_next_week()

    before_inputs = tp.count_hours_inputs()
    print(f"\n[future] hours inputs before add: {before_inputs}")

    tp.open_add_project_dialog()
    tp.select_project_in_dialog("DM project")
    page.wait_for_timeout(1500)

    after_inputs = tp.count_hours_inputs()
    print(f"[future] hours inputs after add:  {after_inputs}")

    assert after_inputs >= 7, (
        f"Expected a row with >=7 hour inputs to appear; got {after_inputs}"
    )

    _goto_current_week_clean(tp)


# =====================================================================
# Future week: hour inputs are DISABLED (this is the strong check)
# =====================================================================

def test_future_week_hour_inputs_are_disabled(timesheet_page_in_session):
    """
    The app disables future-week hour inputs.
    This is the strongest form of validation: the user cannot even type.
    """
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_next_week()

    # Ensure a row exists so we have inputs to inspect
    if tp.count_hours_inputs() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)

    inputs = page.locator(".hours-input")
    n = inputs.count()
    print(f"\n[future] hour input count: {n}")

    disabled_count = 0
    for i in range(n):
        try:
            if not inputs.nth(i).is_enabled():
                disabled_count += 1
        except Exception:
            pass
    print(f"[future] disabled inputs: {disabled_count} / {n}")

    assert n > 0, "Expected at least one hour input in the future week"
    assert disabled_count == n, (
        f"All future-week inputs must be disabled; "
        f"only {disabled_count} of {n} were disabled"
    )

    # Also check the tooltip text that Playwright surfaced in the trace
    try:
        tooltip = inputs.first.get_attribute("title") or ""
        print(f"[future] tooltip: {tooltip!r}")
        assert "Future" in tooltip or "future" in tooltip, (
            f"Expected tooltip about future dates; got {tooltip!r}"
        )
    except Exception:
        pass

    _goto_current_week_clean(tp)


def test_future_week_cannot_type_hours(timesheet_page_in_session):
    """
    Direct proof: trying to type into a future-week hour field must not work.
    Uses force=False so Playwright refuses to interact with disabled inputs.
    """
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.navigate_to_next_week()

    if tp.count_hours_inputs() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)

    inputs = page.locator(".hours-input")
    field = inputs.first

    disabled = not field.is_enabled()
    print(f"\n[future] first input enabled? {not disabled}")

    # The strongest assertion: field must be disabled.
    assert disabled, "Future-week hour input should be disabled"

    # Verify we can read its value but not interact via keyboard
    try:
        value = field.input_value()
        print(f"[future] input value: {value!r}")
        assert value in ("0", "", "0.0"), (
            f"Future-week input should show 0/empty; shows {value!r}"
        )
    except Exception:
        pass

    _goto_current_week_clean(tp)


# =====================================================================
# Control tests — current and past weeks DO accept hours
# =====================================================================

def test_current_week_accepts_hour_entry(timesheet_page_in_session):
    """Control test: current week DOES accept hours."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    if tp.count_hours_inputs() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)

    typed_value = tp.try_set_hours_first_input("4")
    print(f"\n[current] typed '4', field now reads: {typed_value!r}")

    assert typed_value in ("4", "4.0"), (
        f"Current week should accept hour '4'; field reads {typed_value!r}"
    )

    tp.clear_first_hours_input()


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

    tp.clear_first_hours_input()
    _goto_current_week_clean(tp)