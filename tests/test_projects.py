"""
Add Project flow tests (READ-ONLY, no Save).

Uses RELATIVE row counts, so tests are valid whether the week starts
with 0 rows or has a saved row from earlier runs.
"""
from pages.timesheet_page import TimesheetPage


KNOWN_PROJECT = "DM project"


def test_add_project_dialog_opens(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    tp.open_add_project_dialog()
    assert tp.project_dialog_visible(), "Add Project dialog did not open"
    tp.close_dialog()


def test_add_project_dialog_lists_projects(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    tp.open_add_project_dialog()

    names = tp.dialog_project_names()
    print(f"\n[dialog] projects found: {names}")

    body = tp.page.locator("body").inner_text()
    assert KNOWN_PROJECT in body, (
        f"Expected {KNOWN_PROJECT!r} somewhere on the page after opening dialog"
    )

    tp.close_dialog()


def test_adding_one_project_adds_one_row(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    before_rows = tp.count_project_rows()
    before_inputs = tp.count_hours_inputs()
    print(f"\n[before] rows={before_rows} inputs={before_inputs}")

    tp.open_add_project_dialog()
    tp.select_project_in_dialog(KNOWN_PROJECT)
    page.wait_for_timeout(1500)

    after_rows = tp.count_project_rows()
    after_inputs = tp.count_hours_inputs()
    print(f"[after]  rows={after_rows} inputs={after_inputs}")

    assert after_rows == before_rows + 1, (
        f"Expected 1 new row; got {after_rows - before_rows}"
    )
    assert after_inputs == before_inputs + 7


def test_closing_dialog_without_selection_does_not_add_row(
    timesheet_page_in_session,
):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    before_rows = tp.count_project_rows()
    print(f"\n[before] rows={before_rows}")

    tp.open_add_project_dialog()
    tp.close_dialog()
    page.wait_for_timeout(800)

    after_rows = tp.count_project_rows()
    print(f"[after] rows={after_rows}")

    assert after_rows == before_rows


def test_grid_visible_after_add_project(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.open_add_project_dialog()
    tp.select_project_in_dialog(KNOWN_PROJECT)
    page.wait_for_timeout(1200)

    assert tp.is_grid_visible()


def test_unsaved_row_disappears_after_reload(timesheet_page_in_session):
    """
    Unsaved rows vanish after reload.
    If the grid started with a saved row, that row remains after reload,
    but any unsaved additions disappear.
    """
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    starting_rows = tp.count_project_rows()
    print(f"\n[starting] rows={starting_rows}")

    # Add a row without saving
    tp.open_add_project_dialog()
    tp.select_project_in_dialog(KNOWN_PROJECT)
    page.wait_for_timeout(1500)

    rows_with_unsaved = tp.count_project_rows()
    print(f"[unsaved] rows: {rows_with_unsaved}")
    assert rows_with_unsaved >= starting_rows + 1

    # Reload — saved rows stay, unsaved rows vanish
    page.goto(page.url, wait_until="load")
    tp.wait_until_loaded()
    tp.select_current_week()
    page.wait_for_timeout(1500)

    rows_after_reload = tp.count_project_rows()
    print(f"[after reload] rows: {rows_after_reload}")

    assert rows_after_reload == starting_rows, (
        f"After reload, rows should return to {starting_rows}; "
        f"got {rows_after_reload}"
    )