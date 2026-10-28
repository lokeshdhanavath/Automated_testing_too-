import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from app.database import SessionLocal
from app.csv_scenarios import parse_csv_to_steps, extract_wait_seconds
from app.scenario_engine import handle_wait


def test_extract_wait_seconds():
    # Unit tests for flexible duration parser
    assert extract_wait_seconds("5") == 5.0
    assert extract_wait_seconds("5s") == 5.0
    assert extract_wait_seconds("3 sec") == 3.0
    assert extract_wait_seconds("2.5 seconds") == 2.5
    assert extract_wait_seconds("5000ms") == 5.0
    assert extract_wait_seconds("500ms") == 0.5
    assert extract_wait_seconds("3000") == 3.0
    assert extract_wait_seconds("1500") == 1.5
    assert extract_wait_seconds("") is None
    assert extract_wait_seconds(None) is None


def test_handle_wait_execution():
    mock_page = MagicMock()
    logs = []
    def log(msg):
        logs.append(msg)

    # 1. Test explicit seconds parameter
    res, val = handle_wait(mock_page, {"seconds": 2}, "", 10000, log)
    assert res == "Paused for 2s"
    assert val == "2s"
    mock_page.wait_for_timeout.assert_called_with(2000)

    # 2. Test duration_ms parameter
    res, val = handle_wait(mock_page, {"duration_ms": 1500}, "", 10000, log)
    assert res == "Paused for 1.5s"
    mock_page.wait_for_timeout.assert_called_with(1500)

    # 3. Test string with seconds unit "3s"
    res, val = handle_wait(mock_page, {"value": "3s"}, "", 10000, log)
    assert res == "Paused for 3s"
    mock_page.wait_for_timeout.assert_called_with(3000)

    # 4. Test string with ms unit "500ms"
    res, val = handle_wait(mock_page, {"value": "500ms"}, "", 10000, log)
    assert res == "Paused for 0.5s"
    mock_page.wait_for_timeout.assert_called_with(500)


def test_parse_csv_with_wait_actions():
    csv_content = """Action,Target,Value,Description
open_app,,https://example.com,Open website
wait,,3,Wait 3 seconds for initial load
pause,2s,,Pause for 2 seconds
wait 5s,,,Pause 5s using action name
sleep,,1500ms,Wait 1500ms
"""
    db = SessionLocal()
    try:
        steps = parse_csv_to_steps(csv_content, "apex-timesheet", db)
        assert len(steps) == 5

        # Step 1: open_app
        assert steps[0]["action_type"] == "open_app"

        # Step 2: wait 3s
        assert steps[1]["action_type"] == "wait"
        assert steps[1]["action_params"]["seconds"] == 3.0
        assert steps[1]["action_params"]["duration_ms"] == 3000

        # Step 3: pause 2s
        assert steps[2]["action_type"] == "wait"
        assert steps[2]["action_params"]["seconds"] == 2.0
        assert steps[2]["action_params"]["duration_ms"] == 2000

        # Step 4: wait 5s from action column
        assert steps[3]["action_type"] == "wait"
        assert steps[3]["action_params"]["seconds"] == 5.0
        assert steps[3]["action_params"]["duration_ms"] == 5000

        # Step 5: sleep 1500ms
        assert steps[4]["action_type"] == "wait"
        assert steps[4]["action_params"]["seconds"] == 1.5
        assert steps[4]["action_params"]["duration_ms"] == 1500
    finally:
        db.close()

