"""
Database service module for Veriqon PostgreSQL tables:
- projects
- test_runs
- test_run_results
- artifacts
- scenario_mappings
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

# Project root: Automated_testing_too-
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SCENARIOS = {
    "TC-001": "tests/test_login.py::test_login_page_loads[chromium]",
    "TC-002": "tests/test_login.py::test_login_with_valid_credentials[chromium]",
    "TC-003": "tests/test_login.py::test_navigate_to_my_timesheet[chromium]",
    "TC-007": "tests/test_projects.py::test_adding_one_project_adds_one_row[chromium]",
    "TC-008": "tests/test_validation.py::test_over_max_hours_cleared[chromium]",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_project(db: Session, project_identifier: str | None = None) -> dict[str, Any]:
    """
    Resolve a project by its external_id (e.g. 'apex-timesheet') or UUID.
    Falls back to the default project if no identifier is provided.
    """
    if not project_identifier or project_identifier in ("default", ""):
        query = text("""
            SELECT * FROM projects
            WHERE is_active = TRUE
            ORDER BY is_default DESC, created_at ASC
            LIMIT 1
        """)
        row = db.execute(query).mappings().first()
    else:
        query = text("""
            SELECT * FROM projects
            WHERE (external_id = :pid OR id::text = :pid)
            LIMIT 1
        """)
        row = db.execute(query, {"pid": project_identifier}).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_identifier}' not found in database.",
        )

    data = dict(row)
    # Ensure id is string representation of UUID when returned to callers
    data["uuid_str"] = str(data["id"])
    return data


def seed_scenario_mappings(db: Session, project_uuid: uuid.UUID) -> None:
    """Seed scenario mappings for a project if none exist."""
    existing_count = db.execute(
        text("SELECT COUNT(*) FROM scenario_mappings WHERE project_id = :pid"),
        {"pid": project_uuid},
    ).scalar() or 0

    if existing_count == 0:
        for tc_id, node_id in DEFAULT_SCENARIOS.items():
            db.execute(
                text("""
                    INSERT INTO scenario_mappings (project_id, tc_id, pytest_node_id, created_at)
                    VALUES (:pid, :tc_id, :node_id, :created_at)
                """),
                {
                    "pid": project_uuid,
                    "tc_id": tc_id,
                    "node_id": node_id,
                    "created_at": _now(),
                },
            )
        db.commit()


def get_scenario_mappings(db: Session, project_uuid: uuid.UUID) -> dict[str, str]:
    """Return tc_id -> pytest_node_id mapping for a project."""
    seed_scenario_mappings(db, project_uuid)
    rows = db.execute(
        text("SELECT tc_id, pytest_node_id FROM scenario_mappings WHERE project_id = :pid"),
        {"pid": project_uuid},
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def create_test_run(
    db: Session,
    run_uuid: uuid.UUID,
    project_uuid: uuid.UUID,
    environment: str | None = None,
    browser: str | None = None,
    selected_tests: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new record in test_runs table."""
    now = _now()
    tests_json = json.dumps(selected_tests or [])

    db.execute(
        text("""
            INSERT INTO test_runs (
                id, project_id, status, environment, browser,
                selected_tests, started_at, finished_at, exit_code,
                summary, log_path, created_at
            )
            VALUES (
                :id, :project_id, 'queued', :environment, :browser,
                CAST(:selected_tests AS jsonb), NULL, NULL, NULL,
                NULL, NULL, :created_at
            )
        """),
        {
            "id": run_uuid,
            "project_id": project_uuid,
            "environment": environment,
            "browser": browser,
            "selected_tests": tests_json,
            "created_at": now,
        },
    )
    db.commit()

    return {
        "id": str(run_uuid),
        "project_id": str(project_uuid),
        "status": "queued",
        "created_at": now.isoformat(),
    }


def update_test_run(
    db: Session,
    run_uuid: uuid.UUID,
    *,
    status: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    exit_code: int | None = None,
    summary: dict[str, Any] | None = None,
    log_path: str | None = None,
) -> None:
    """Update fields on an existing test_runs record."""
    updates = []
    params: dict[str, Any] = {"id": run_uuid}

    if status is not None:
        updates.append("status = :status")
        params["status"] = status
    if started_at is not None:
        updates.append("started_at = :started_at")
        params["started_at"] = started_at
    if finished_at is not None:
        updates.append("finished_at = :finished_at")
        params["finished_at"] = finished_at
    if exit_code is not None:
        updates.append("exit_code = :exit_code")
        params["exit_code"] = exit_code
    if summary is not None:
        updates.append("summary = CAST(:summary AS jsonb)")
        params["summary"] = json.dumps(summary)
    if log_path is not None:
        updates.append("log_path = :log_path")
        params["log_path"] = log_path

    if updates:
        stmt = f"UPDATE test_runs SET {', '.join(updates)} WHERE id = :id"
        db.execute(text(stmt), params)
        db.commit()


def save_test_results(
    db: Session,
    run_uuid: uuid.UUID,
    results: list[dict[str, Any]],
) -> None:
    """Persist individual test results into test_run_results table."""
    now = _now()
    for item in results:
        test_id = item.get("name") or "unknown_test"
        status_val = item.get("status") or "passed"
        duration = item.get("duration")
        error_msg = item.get("error") or None

        db.execute(
            text("""
                INSERT INTO test_run_results (
                    run_id, test_id, status, duration_seconds, error_message, created_at
                )
                VALUES (
                    :run_id, :test_id, :status, :duration_seconds, :error_message, :created_at
                )
            """),
            {
                "run_id": run_uuid,
                "test_id": test_id,
                "status": status_val,
                "duration_seconds": duration,
                "error_message": error_msg,
                "created_at": now,
            },
        )
    db.commit()


def register_artifact(
    db: Session,
    project_uuid: uuid.UUID,
    run_uuid: uuid.UUID | None,
    artifact_type: str,
    file_path: Path,
) -> dict[str, Any] | None:
    """
    Register an artifact in the artifacts table.
    Prevents duplicate entries using relative_path.
    """
    if not file_path.is_file():
        return None

    try:
        rel_path = file_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        rel_path = file_path.name

    filename = file_path.name
    size = file_path.stat().st_size

    # Deduce MIME type
    ext = file_path.suffix.lower()
    content_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".webm": "video/webm",
        ".mp4": "video/mp4",
        ".xml": "application/xml",
        ".json": "application/json",
        ".html": "text/html",
        ".csv": "text/csv",
        ".log": "text/plain",
        ".txt": "text/plain",
    }
    content_type = content_types.get(ext, "application/octet-stream")

    # Check for existing record
    existing = db.execute(
        text("SELECT id FROM artifacts WHERE relative_path = :rel_path"),
        {"rel_path": rel_path},
    ).scalar()

    if existing:
        return {
            "id": existing,
            "filename": filename,
            "relative_path": rel_path,
            "artifact_type": artifact_type,
            "content_type": content_type,
            "size_bytes": size,
            "url": f"/api/artifacts/{existing}/content",
            "download_url": f"/api/artifacts/{existing}/content?download=true",
        }

    now = _now()
    row = db.execute(
        text("""
            INSERT INTO artifacts (
                project_id, run_id, artifact_type, filename,
                relative_path, content_type, size_bytes, created_at
            )
            VALUES (
                :project_id, :run_id, :artifact_type, :filename,
                :relative_path, :content_type, :size_bytes, :created_at
            )
            RETURNING id, project_id, run_id, artifact_type, filename,
                      relative_path, content_type, size_bytes, created_at
        """),
        {
            "project_id": project_uuid,
            "run_id": run_uuid,
            "artifact_type": artifact_type,
            "filename": filename,
            "relative_path": rel_path,
            "content_type": content_type,
            "size_bytes": size,
            "created_at": now,
        },
    ).mappings().first()

    db.commit()

    art = dict(row)
    art["id"] = int(art["id"])
    art["project_id"] = str(art["project_id"])
    art["run_id"] = str(art["run_id"]) if art["run_id"] else None
    art["created_at"] = art["created_at"].isoformat() if art["created_at"] else now.isoformat()
    art["url"] = f"/api/artifacts/{art['id']}/content"
    art["download_url"] = f"/api/artifacts/{art['id']}/content?download=true"
    return art


def get_project_runs(
    db: Session,
    project_identifier: str,
) -> list[dict[str, Any]]:
    """Return all test runs for a project."""
    project = resolve_project(db, project_identifier)
    project_uuid = project["id"]

    rows = db.execute(
        text("""
            SELECT tr.*, p.external_id as project_external_id, p.name as project_name
            FROM test_runs tr
            JOIN projects p ON p.id = tr.project_id
            WHERE tr.project_id = :pid
            ORDER BY tr.created_at DESC
        """),
        {"pid": project_uuid},
    ).mappings().all()

    results = []
    for row in rows:
        item = dict(row)
        item["id"] = str(item["id"])
        item["project_id"] = project["external_id"]
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
        item["started_at"] = item["started_at"].isoformat() if item["started_at"] else None
        item["finished_at"] = item["finished_at"].isoformat() if item["finished_at"] else None
        results.append(item)

    return results


def get_run_details(
    db: Session,
    run_id_str: str,
) -> dict[str, Any]:
    """Return test run details along with individual test results."""
    try:
        run_uuid = uuid.UUID(run_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run ID format.")

    run_row = db.execute(
        text("""
            SELECT tr.*, p.external_id as project_external_id, p.name as project_name
            FROM test_runs tr
            JOIN projects p ON p.id = tr.project_id
            WHERE tr.id = :rid
        """),
        {"rid": run_uuid},
    ).mappings().first()

    if not run_row:
        raise HTTPException(status_code=404, detail="Run not found.")

    run_data = dict(run_row)
    run_data["id"] = str(run_data["id"])
    run_data["project_id"] = run_data["project_external_id"]
    run_data["created_at"] = run_data["created_at"].isoformat() if run_data["created_at"] else None
    run_data["started_at"] = run_data["started_at"].isoformat() if run_data["started_at"] else None
    run_data["finished_at"] = run_data["finished_at"].isoformat() if run_data["finished_at"] else None

    # Fetch individual test results
    test_results_rows = db.execute(
        text("""
            SELECT id, test_id, status, duration_seconds, error_message, created_at
            FROM test_run_results
            WHERE run_id = :rid
            ORDER BY created_at ASC, id ASC
        """),
        {"rid": run_uuid},
    ).mappings().all()

    test_results = []
    for tr in test_results_rows:
        item = dict(tr)
        item["duration_seconds"] = float(item["duration_seconds"]) if item["duration_seconds"] is not None else 0.0
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
        test_results.append(item)

    run_data["test_results"] = test_results
    return run_data


def get_artifacts(
    db: Session,
    project_identifier: str | None = None,
    run_id_str: str | None = None,
    artifact_type: str | None = None,
) -> list[dict[str, Any]]:
    """List artifacts with optional filtering by project, run, and artifact type."""
    filters = []
    params: dict[str, Any] = {}

    if project_identifier:
        project = resolve_project(db, project_identifier)
        filters.append("a.project_id = :pid")
        params["pid"] = project["id"]

    if run_id_str:
        try:
            params["rid"] = uuid.UUID(run_id_str)
            filters.append("a.run_id = :rid")
        except ValueError:
            return []

    if artifact_type:
        filters.append("a.artifact_type = :art_type")
        params["art_type"] = artifact_type

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    query = f"""
        SELECT a.*, p.external_id as project_external_id
        FROM artifacts a
        JOIN projects p ON p.id = a.project_id
        {where_clause}
        ORDER BY a.created_at DESC
    """

    rows = db.execute(text(query), params).mappings().all()
    results = []
    for row in rows:
        art = dict(row)
        art["id"] = int(art["id"])
        art["project_id"] = art["project_external_id"]
        art["run_id"] = str(art["run_id"]) if art["run_id"] else None
        art["created_at"] = art["created_at"].isoformat() if art["created_at"] else None
        art["url"] = f"/api/artifacts/{art['id']}/content"
        art["download_url"] = f"/api/artifacts/{art['id']}/content?download=true"
        results.append(art)

    return results


def get_artifact_by_id(db: Session, artifact_id: int) -> dict[str, Any]:
    """Retrieve an artifact by its database ID."""
    row = db.execute(
        text("""
            SELECT a.*, p.external_id as project_external_id
            FROM artifacts a
            JOIN projects p ON p.id = a.project_id
            WHERE a.id = :aid
        """),
        {"aid": artifact_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    art = dict(row)
    art["id"] = int(art["id"])
    art["project_id"] = art["project_external_id"]
    art["run_id"] = str(art["run_id"]) if art["run_id"] else None
    art["created_at"] = art["created_at"].isoformat() if art["created_at"] else None
    art["url"] = f"/api/artifacts/{art['id']}/content"
    art["download_url"] = f"/api/artifacts/{art['id']}/content?download=true"
    return art

