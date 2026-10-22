"""
Integration test for Generic Playwright Execution Engine in Veriqon.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal
from app import db_service, scenarios_service, scenario_engine


def test_engine_execution():
    html_content = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><title>Veriqon Engine Test</title></head>\n"
        "<body>\n"
        "  <h1>Welcome to Veriqon Engine</h1>\n"
        "  <input id='username-input' type='text' placeholder='Enter username' />\n"
        "  <button id='login-btn' onclick='document.getElementById(\"result\").innerText=\"Login Success: \" + document.getElementById(\"username-input\").value'>Log In</button>\n"
        "  <div id='result'></div>\n"
        "</body>\n"
        "</html>"
    )

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html_content)
        test_html_path = f.name.replace("\\", "/")

    db = SessionLocal()
    try:
        proj = db_service.resolve_project(db, "apex-timesheet")
        pid = proj["id"]

        run_uuid = uuid.uuid4()
        db_service.create_test_run(db, run_uuid, pid, environment="QA", browser="chromium")

        # Delete any leftover test scenario
        db.execute(db_service.text("DELETE FROM test_scenarios WHERE name LIKE 'Engine Fixture Test%'"))
        db.commit()

        scenario_name = f"Engine Fixture Test {uuid.uuid4().hex[:6]}"
        scenario = scenarios_service.create_scenario(
            db=db,
            project_id=pid,
            name=scenario_name,
            failure_policy="stop",
            environment="QA",
            steps=[
                {
                    "step_order": 1,
                    "action_type": "navigate",
                    "locator_value": f"file:///{test_html_path}",
                    "action_params": {"url": f"file:///{test_html_path}"},
                    "description": "Open HTML fixture",
                },
                {
                    "step_order": 2,
                    "action_type": "assert_title",
                    "action_params": {"value": "Veriqon Engine Test"},
                    "description": "Assert Title",
                },
                {
                    "step_order": 3,
                    "action_type": "fill",
                    "locator_type": "id",
                    "locator_value": "username-input",
                    "action_params": {"value": "{{username}}"},
                    "description": "Enter username",
                },
                {
                    "step_order": 4,
                    "action_type": "click",
                    "locator_type": "id",
                    "locator_value": "login-btn",
                    "description": "Click button",
                },
                {
                    "step_order": 5,
                    "action_type": "assert_text",
                    "locator_type": "id",
                    "locator_value": "result",
                    "action_params": {"value": "Login Success: admin_user"},
                    "description": "Assert result message",
                },
                {
                    "step_order": 6,
                    "action_type": "capture_screenshot",
                    "description": "Capture final screenshot",
                },
            ],
        )

        test_cred = {"username": "admin_user", "secret": "dummy"}

        result = scenario_engine.run_generic_scenario(
            db=db,
            run_uuid=run_uuid,
            project=proj,
            scenario=scenario,
            decrypted_credentials=test_cred,
        )

        print("Execution outcome:", result)
        assert result["status"] == "passed", f"Engine failed: {result}"

        step_results = scenarios_service.get_step_results(db, run_uuid)
        print("Step Results count:", len(step_results))
        for s in step_results:
            print(f"  Step {s['step_order']}: {s['description']} -> {s['status']} ({s['duration_ms']}ms)")
            if s.get("screenshot_url"):
                print(f"    Screenshot URL: {s['screenshot_url']}")
        assert len(step_results) == 6, "Step count mismatch"

        run_details = db_service.get_run_details(db, str(run_uuid))
        print("Run status in DB:", run_details["status"])
        assert run_details["status"] == "passed"

        print("GENERIC SCENARIO PLAYWRIGHT ENGINE TEST PASSED!")

    finally:
        try:
            if "scenario" in locals() and scenario.get("id"):
                scenarios_service.delete_scenario(db, uuid.UUID(scenario["id"]))
        except Exception:
            pass
        db.close()
        if os.path.exists(test_html_path):
            os.remove(test_html_path)


if __name__ == "__main__":
    test_engine_execution()
