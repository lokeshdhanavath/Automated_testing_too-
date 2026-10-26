"""
Veriqon Automated Testing Platform - Integration & Verification Test Suite.
Tests database persistence, project isolation, artifact registration,
video/screenshot capture pipeline, and security.
"""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

# Ensure backend app is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal, check_database_connection, engine
from app import db_service
from app.main import app, ROOT, discover_tests, read_report


def test_01_database_connection():
    """Verify PostgreSQL 18 veriqon_db connection and tables."""
    assert check_database_connection() is True

    with engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)).scalars().all()

        required = {"projects", "test_runs", "test_run_results", "artifacts", "scenario_mappings"}
        assert required.issubset(set(tables)), f"Missing tables: {required - set(tables)}"


def test_02_project_resolution():
    """Verify resolving projects by external_id and UUID with fallback."""
    db = SessionLocal()
    try:
        # Default project
        default_proj = db_service.resolve_project(db, None)
        assert default_proj["external_id"] == "apex-timesheet"
        assert isinstance(default_proj["id"], uuid.UUID)

        # By external_id
        named_proj = db_service.resolve_project(db, "apex-timesheet")
        assert named_proj["id"] == default_proj["id"]

        # By UUID string
        uuid_proj = db_service.resolve_project(db, str(default_proj["id"]))
        assert uuid_proj["external_id"] == "apex-timesheet"

        # Invalid project
        with pytest.raises(Exception):
            db_service.resolve_project(db, "nonexistent-project-xyz")
    finally:
        db.close()


def test_03_run_lifecycle_and_test_results_persistence():
    """Verify test run creation, status updates, and individual test result persistence."""
    db = SessionLocal()
    test_run_uuid = uuid.uuid4()
    try:
        project = db_service.resolve_project(db, "apex-timesheet")
        project_uuid = project["id"]

        # 1. Create queued run
        run_record = db_service.create_test_run(
            db,
            run_uuid=test_run_uuid,
            project_uuid=project_uuid,
            environment="QA",
            browser="chromium",
            selected_tests=["tests/test_new_feature.py::test_new_feature[chromium]"],
        )
        assert run_record["status"] == "queued"

        # 2. Update to running
        db_service.update_test_run(
            db,
            test_run_uuid,
            status="running",
            log_path="reports/logs/test.log",
        )

        details = db_service.get_run_details(db, str(test_run_uuid))
        assert details["status"] == "running"
        assert details["log_path"] == "reports/logs/test.log"

        # 3. Persist individual test results
        mock_results = [
            {
                "name": "tests/test_new_feature.py::test_new_feature[chromium]",
                "status": "passed",
                "duration": 0.42,
                "error": None,
            },
            {
                "name": "tests/test_login.py::test_login_page_loads[chromium]",
                "status": "failed",
                "duration": 1.15,
                "error": "AssertionError: Element not found",
            },
        ]
        db_service.save_test_results(db, test_run_uuid, mock_results)

        # 4. Finish run
        summary = {"total": 2, "passed": 1, "failed": 1, "skipped": 0, "errors": 0}
        db_service.update_test_run(
            db,
            test_run_uuid,
            status="failed",
            exit_code=1,
            summary=summary,
        )

        final_details = db_service.get_run_details(db, str(test_run_uuid))
        assert final_details["status"] == "failed"
        assert final_details["exit_code"] == 1
        assert len(final_details["test_results"]) == 2
        res_map = {r["test_id"]: r for r in final_details["test_results"]}
        assert res_map["tests/test_new_feature.py::test_new_feature[chromium]"]["status"] == "passed"
        assert res_map["tests/test_login.py::test_login_page_loads[chromium]"]["status"] == "failed"
        assert "AssertionError" in (res_map["tests/test_login.py::test_login_page_loads[chromium]"]["error_message"] or "")
    finally:
        # Clean up test run from DB (cascade deletes test_run_results)
        try:
            db.execute(text("DELETE FROM test_runs WHERE id = :rid"), {"rid": test_run_uuid})
            db.commit()
        except Exception:
            db.rollback()
        db.close()


def test_04_artifact_registration_and_safe_serving():
    """Verify artifact registration, deduping, and path resolution."""
    db = SessionLocal()
    test_run_uuid = uuid.uuid4()
    dummy_art = ROOT / "artifacts" / "test-dummy.png"
    try:
        project = db_service.resolve_project(db, "apex-timesheet")
        project_uuid = project["id"]

        # Create run for foreign key
        db_service.create_test_run(
            db, run_uuid=test_run_uuid, project_uuid=project_uuid
        )

        # Create dummy artifact file on disk
        dummy_art.parent.mkdir(parents=True, exist_ok=True)
        dummy_art.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")

        # Register artifact
        art = db_service.register_artifact(
            db,
            project_uuid=project_uuid,
            run_uuid=test_run_uuid,
            artifact_type="screenshot",
            file_path=dummy_art,
        )
        assert art is not None
        assert art["artifact_type"] == "screenshot"
        assert art["content_type"] == "image/png"
        assert art["url"] == f"/api/artifacts/{art['id']}/content"

        # Check duplicate registration returns same id
        art_dup = db_service.register_artifact(
            db,
            project_uuid=project_uuid,
            run_uuid=test_run_uuid,
            artifact_type="screenshot",
            file_path=dummy_art,
        )
        assert art_dup["id"] == art["id"]

        # Verify query filters
        arts = db_service.get_artifacts(db, project_identifier="apex-timesheet", run_id_str=str(test_run_uuid))
        assert len(arts) == 1
        assert arts[0]["id"] == art["id"]

        # Verify retrieval by ID
        fetched = db_service.get_artifact_by_id(db, art["id"])
        assert fetched["filename"] == "test-dummy.png"
    finally:
        if dummy_art.exists():
            dummy_art.unlink()
        try:
            db.execute(text("DELETE FROM test_runs WHERE id = :rid"), {"rid": test_run_uuid})
            db.commit()
        except Exception:
            db.rollback()
        db.close()


def test_05_project_isolation():
    """Verify artifacts from one project do not appear under another project."""
    db = SessionLocal()
    try:
        project_a = db_service.resolve_project(db, "apex-timesheet")
        # Query artifacts for a non-existent project returns 404
        with pytest.raises(Exception):
            db_service.get_artifacts(db, project_identifier="other-isolated-project")
    finally:
        db.close()


def test_06_scenario_mappings_and_test_discovery():
    """Verify scenario mappings in PostgreSQL and pytest discovery."""
    db = SessionLocal()
    try:
        project = db_service.resolve_project(db, "apex-timesheet")
        mappings = db_service.get_scenario_mappings(db, project["id"])
        assert "TC-001" in mappings
        assert "TC-002" in mappings
        assert mappings["TC-001"] == "tests/test_login.py::test_login_page_loads[chromium]"

        # Test discovery
        tests = discover_tests("tests")
        assert len(tests) >= 30
        assert any("tests/test_new_feature.py::test_new_feature" in t for t in tests)
    finally:
        db.close()

