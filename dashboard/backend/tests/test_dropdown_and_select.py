import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from app.database import SessionLocal
from app.csv_scenarios import parse_csv_to_steps
from app.scenario_engine import handle_select_option


def test_handle_select_option_native():
    mock_page = MagicMock()
    mock_loc = MagicMock()
    mock_page.locator.return_value = mock_loc
    mock_loc.first = mock_loc
    mock_loc.count.return_value = 1
    mock_loc.evaluate.return_value = "select"

    logs = []
    def log(msg):
        logs.append(msg)

    res, val = handle_select_option(
        page=mock_page,
        action_params={"value": "Engineering"},
        locator_type="id",
        locator_val="dept-select",
        step_timeout=5000,
        log=log,
    )

    assert "Engineering" in res
    assert val == "Engineering"


def test_handle_select_option_combobox_search():
    mock_page = MagicMock()
    mock_loc = MagicMock()
    mock_page.locator.return_value = mock_loc
    mock_loc.first = mock_loc
    mock_loc.count.return_value = 1
    # First evaluate tag is input
    mock_loc.evaluate.side_effect = ["input", True]

    # Mock option candidate
    mock_option = MagicMock()
    mock_option.count.return_value = 1
    mock_option.is_visible.return_value = True

    # When looking for option in page
    mock_page.locator.side_effect = lambda sel: mock_option if 'Engineering' in str(sel) else mock_loc
    mock_page.get_by_role.return_value.first = mock_option

    logs = []
    def log(msg):
        logs.append(msg)

    res, val = handle_select_option(
        page=mock_page,
        action_params={"value": "Engineering"},
        locator_type="id",
        locator_val="project-search-box",
        step_timeout=5000,
        log=log,
    )

    assert "Engineering" in res
    assert val == "Engineering"
    mock_loc.click.assert_called()


def test_parse_csv_with_select_actions():
    csv_content = """Action,Target,Value,Description
select_option,Department,Engineering,Select Engineering department
search_and_select,Project Name,Phoenix,Search and choose Phoenix
choose,Status,Active,Choose Active status
"""
    db = SessionLocal()
    try:
        steps = parse_csv_to_steps(csv_content, "apex-timesheet", db)
        assert len(steps) == 3

        # Step 1: select_option
        assert steps[0]["action_type"] == "select_option"
        assert steps[0]["action_params"]["option"] == "Engineering"
        assert steps[0]["action_params"]["value"] == "Engineering"

        # Step 2: search_and_select mapped to select_option
        assert steps[1]["action_type"] == "select_option"
        assert steps[1]["action_params"]["option"] == "Phoenix"
        assert steps[1]["action_params"]["value"] == "Phoenix"

        # Step 3: choose mapped to select_option
        assert steps[2]["action_type"] == "select_option"
        assert steps[2]["action_params"]["option"] == "Active"
        assert steps[2]["action_params"]["value"] == "Active"
    finally:
        db.close()

