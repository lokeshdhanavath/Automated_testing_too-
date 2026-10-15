"""
Persistence tests — THE ONLY FILE THAT WRITES TO THE DATABASE.

Every test is marked @pytest.mark.state_changing and will NOT run by default.
To run: pytest -m state_changing

Safety:
  - Self-skips if the week already contains non-zero hours.
  - ALWAYS attempts cleanup (delete + save) in a finally block.
"""
import pytest

from pages.timesheet_page import TimesheetPage


DM_PROJECT = "DM project"


def _grid_is_clean(tp: TimesheetPage) -> bool:
    """Clean = zero rows OR every hour input reads 0/empty."""
    inputs = tp.page.locator(".hours-input")
    n = inputs.count()
    for i in range(n):
        try:
            val = inputs.nth(i).input_value()
            if val and val not in ("0", "0.0", ""):
                return False
        except Exception:
            continue
    return True


def _do_cleanup(tp: TimesheetPage):
    """
    Delete any row that exists and save. Best-effort — never raises.
    """
    try:
        rows = tp.count_project_rows()
        if rows > 0:
            # Delete all rows one at a time (the grid may have one or more)
            for _ in range(rows):
                tp.click_delete_row(row_index=0)
                tp.page.wait_for_timeout(500)
            tp.click_save()
            tp.page.wait_for_timeout(2500)
            tp.reload()
    except Exception as e:
        print(f"[cleanup] best-effort delete failed: {e}")


@pytest.mark.state_changing
def test_add_save_and_delete_row_persists(timesheet_page_in_session):
    tp: TimesheetPage = timesheet_page_in_session
    page = tp.page

    # ---------- Safety gate ----------
    if not _grid_is_clean(tp):
        pytest.skip("Current week has hours already — skipping persistence test")

    starting_rows = tp.count_project_rows()
    print(f"\n[start] rows={starting_rows}")

    try:
        # ---------- Add row ----------
        tp.open_add_project_dialog()
        tp.select_project_in_dialog(DM_PROJECT)
        page.wait_for_timeout(1500)

        rows_after_add = tp.count_project_rows()
        print(f"[after add] rows={rows_after_add}")
        assert rows_after_add == starting_rows + 1

        # ---------- Enter 1 hour on Monday ----------
        tp.set_hours_in_row(row_index=0, day="mon", value="1")
        mon_after_typing = tp.read_hours_in_row(0, "mon")
        print(f"[after typing] mon={mon_after_typing!r}")
        assert mon_after_typing in ("1", "1.0")

        # ---------- Save ----------
        tp.click_save()
        page.wait_for_timeout(2000)

        # ---------- Verify persistence ----------
        tp.reload()
        rows_after_reload = tp.count_project_rows()
        mon_after_reload = tp.read_hours_in_row(0, "mon")
        print(f"[after reload] rows={rows_after_reload} mon={mon_after_reload!r}")

        assert rows_after_reload >= 1, "Saved row disappeared after reload"
        assert mon_after_reload in ("1", "1.0"), (
            f"Saved hour didn't persist; Monday reads {mon_after_reload!r}"
        )

    finally:
        # ---------- ALWAYS cleanup ----------
        print("\n[cleanup] deleting test row(s) and saving...")
        _do_cleanup(tp)

        final_rows = tp.count_project_rows()
        print(f"[cleanup] final rows={final_rows}")
        # Do not assert here — cleanup best-effort, we already reported failure above