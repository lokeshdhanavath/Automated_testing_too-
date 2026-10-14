"""
Hour-field validation tests.

Uses the `timesheet_page_in_session` fixture (already logged in, current week).

Each test first adds a DM project row to the grid (WITHOUT saving) so that
hour inputs exist. The row is discarded when the page reloads between tests,
so no data is persisted.

READ-ONLY relative to the DB.
"""
from pages.timesheet_page import TimesheetPage


# ---------- Helpers ----------

def _ensure_row(tp: TimesheetPage):
    """Add a DM project row if the grid is empty. Returns the page."""
    page = tp.page
    if page.locator(".hours-input").count() == 0:
        tp.open_add_project_dialog()
        tp.select_project_in_dialog("DM project")
        page.wait_for_timeout(1500)
    return page


def _first_hours_input(page):
    locator = page.locator(".hours-input").first
    locator.wait_for(state="visible", timeout=15000)
    return locator


def _read_value(locator) -> str:
    try:
        return locator.input_value()
    except Exception:
        return "<unreadable>"


def _observe(tp: TimesheetPage, value: str):
    """
    Ensure a row exists, then type into the first hour input, blur it,
    observe the resulting value and any visible error, and restore.
    """
    page = _ensure_row(tp)

    field = _first_hours_input(page)
    original = _read_value(field)

    field.click()
    field.fill("")
    if value != "":
        field.type(value, delay=30)
    field.press("Tab")
    page.wait_for_timeout(700)

    after = _read_value(field)

    error_text = ""
    for sel in (
        ".a-ValidationError",
        ".apex-page-error",
        ".u-Color--danger",
        ".t-Form-error",
        "[role='alert']",
    ):
        node = page.locator(sel).first
        try:
            if node.is_visible(timeout=200):
                error_text = node.inner_text().strip()[:200]
                if error_text:
                    break
        except Exception:
            pass

    # Restore original value
    field.click()
    field.fill(original)
    field.press("Tab")
    page.wait_for_timeout(500)

    print(f"\n[observe] input={value!r}  ->  after={after!r}  error={error_text!r}")
    return {"input": value, "after": after, "error": error_text,
            "original": original}


# =====================================================================
# Strict tests based on real APEX behavior
# =====================================================================

def test_valid_half_hour_kept(timesheet_page_in_session):
    result = _observe(timesheet_page_in_session, "7.5")
    assert result["after"] == "7.5", f"got {result['after']!r}"


def test_max_daily_hours_kept(timesheet_page_in_session):
    result = _observe(timesheet_page_in_session, "8")
    assert result["after"] == "8", f"got {result['after']!r}"


def test_over_max_hours_cleared(timesheet_page_in_session):
    result = _observe(timesheet_page_in_session, "9")
    assert result["after"] == "", f"got {result['after']!r}"


def test_negative_hours_cleared(timesheet_page_in_session):
    result = _observe(timesheet_page_in_session, "-1")
    assert result["after"] == "", f"got {result['after']!r}"


def test_alphabetic_input_cleared(timesheet_page_in_session):
    result = _observe(timesheet_page_in_session, "abc")
    assert result["after"] == "", f"got {result['after']!r}"


def test_field_still_editable_after_invalid_input(timesheet_page_in_session):
    tp = timesheet_page_in_session
    _observe(tp, "abc")
    field = _first_hours_input(tp.page)
    assert field.is_visible()
    assert field.is_editable()


def test_grid_survives_invalid_input(timesheet_page_in_session):
    tp = timesheet_page_in_session
    _observe(tp, "xyz")
    page = tp.page
    assert "my-timesheet" in page.url
    assert page.locator(TimesheetPage.GRID).is_visible()