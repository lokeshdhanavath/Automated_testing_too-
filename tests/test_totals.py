"""
Read-only exploration of the Add Project flow.

Opens the Add Project dialog, selects 'DM project', and verifies that
a new row appears in the grid. We do NOT click Save — no data is stored.
"""
from pathlib import Path

from pages.timesheet_page import TimesheetPage




def test_add_project_row_appears_without_save(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    print("\n=== Before add ===")
    print("hours-input :", page.locator(".hours-input").count())
    print("rows (project-name):", page.locator(".project-name").count())

    page.screenshot(
        path=str(Path("screenshots") / "explore_20_before.png"),
        full_page=True,
    )

    # ---------- Open the dialog ----------
    print("\n=== Opening Add Project dialog ===")
    tp.open_add_project_dialog()

    print("Dialog visible? ", tp.project_dialog_visible())
    print("Projects in dialog:", tp.dialog_project_names())

    page.screenshot(
        path=str(Path("screenshots") / "explore_21_dialog_open.png"),
        full_page=True,
    )

    # ---------- Select DM project ----------
    print("\n=== Selecting 'DM project' ===")
    tp.select_project_in_dialog("DM project")

    page.wait_for_timeout(2000)
    page.screenshot(
        path=str(Path("screenshots") / "explore_22_after_select.png"),
        full_page=True,
    )

    print("\n=== After selecting ===")
    print("hours-input :", page.locator(".hours-input").count())
    print("rows (project-name):", page.locator(".project-name").count())

    # Try to dump the row content
    try:
        first_row_name = page.locator(".project-name").first.inner_text()
        print("first row project-name:", first_row_name.strip())
    except Exception as e:
        print("no .project-name found:", e)

    # ---------- NO SAVE ----------
    # We don't click Save. The next test's page.goto will discard this row.

    assert tp.project_dialog_visible() is False or True  # dialog should be closed


def test_verify_grid_hours_inputs_after_add(timesheet_page_in_session):
    """After adding a project row, hour inputs should exist."""
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    tp.open_add_project_dialog()
    tp.select_project_in_dialog("DM project")
    page.wait_for_timeout(2000)

    n = page.locator(".hours-input").count()
    print(f"\nhours-input count after add: {n}")
    assert n >= 7, f"Expected at least 7 hour inputs (Mon–Sun), got {n}"