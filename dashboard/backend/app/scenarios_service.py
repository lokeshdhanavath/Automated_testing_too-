"""
Database service module for generic test scenarios, steps, test data profiles,
and step-level execution results.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def _now() -> datetime:
    return datetime.now(timezone.utc)


# =====================================================================
# Scenarios and Steps
# =====================================================================

def create_scenario(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    description: str | None = None,
    tags: list[str] | None = None,
    failure_policy: str = "stop",
    timeout_seconds: int = 60,
    environment: str = "QA",
    credential_id: uuid.UUID | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Scenario name is required.")

    scenario_id = uuid.uuid4()
    now = _now()
    tags_json = json.dumps(tags or [])

    db.execute(
        text("""
            INSERT INTO test_scenarios (
                id, project_id, name, description, tags, failure_policy,
                timeout_seconds, environment, credential_id, is_active,
                created_at, updated_at
            )
            VALUES (
                :id, :project_id, :name, :description, CAST(:tags AS jsonb),
                :failure_policy, :timeout_seconds, :environment, :credential_id,
                TRUE, :created_at, :updated_at
            )
        """),
        {
            "id": scenario_id,
            "project_id": project_id,
            "name": name,
            "description": description,
            "tags": tags_json,
            "failure_policy": failure_policy,
            "timeout_seconds": timeout_seconds,
            "environment": environment,
            "credential_id": credential_id,
            "created_at": now,
            "updated_at": now,
        },
    )

    # Insert steps
    created_steps = []
    if steps:
        for idx, step_data in enumerate(steps, start=1):
            action_type = step_data.get("action_type") or "click"
            locator_type = step_data.get("locator_type")
            locator_value = step_data.get("locator_value")
            action_params = json.dumps(step_data.get("action_params") or {})
            step_desc = step_data.get("description") or f"Step {idx}: {action_type}"
            is_enabled = step_data.get("is_enabled", True)
            timeout_ms = step_data.get("timeout_ms")

            step_row = db.execute(
                text("""
                    INSERT INTO test_scenario_steps (
                        scenario_id, step_order, action_type, locator_type,
                        locator_value, action_params, description, is_enabled,
                        timeout_ms, created_at
                    )
                    VALUES (
                        :scenario_id, :step_order, :action_type, :locator_type,
                        :locator_value, CAST(:action_params AS jsonb), :description,
                        :is_enabled, :timeout_ms, :created_at
                    )
                    RETURNING id, step_order, action_type, locator_type, locator_value,
                              action_params, description, is_enabled, timeout_ms
                """),
                {
                    "scenario_id": scenario_id,
                    "step_order": idx,
                    "action_type": action_type,
                    "locator_type": locator_type,
                    "locator_value": locator_value,
                    "action_params": action_params,
                    "description": step_desc,
                    "is_enabled": is_enabled,
                    "timeout_ms": timeout_ms,
                    "created_at": now,
                },
            ).mappings().first()
            created_steps.append(dict(step_row))

    db.commit()

    return {
        "id": str(scenario_id),
        "project_id": str(project_id),
        "name": name,
        "description": description or "",
        "tags": tags or [],
        "failure_policy": failure_policy,
        "timeout_seconds": timeout_seconds,
        "environment": environment,
        "credential_id": str(credential_id) if credential_id else None,
        "is_active": True,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "steps": created_steps,
    }


def list_scenarios(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """List all scenarios for a project with step count."""
    rows = db.execute(
        text("""
            SELECT s.id, s.project_id, s.name, s.description, s.tags,
                   s.failure_policy, s.timeout_seconds, s.environment,
                   s.credential_id, s.is_active, s.created_at, s.updated_at,
                   c.name as credential_name,
                   COUNT(st.id) as step_count
            FROM test_scenarios s
            LEFT JOIN app_credentials c ON c.id = s.credential_id
            LEFT JOIN test_scenario_steps st ON st.scenario_id = s.id
            WHERE s.project_id = :pid AND s.is_active = TRUE
            GROUP BY s.id, c.name
            ORDER BY s.created_at DESC
        """),
        {"pid": project_id},
    ).mappings().all()

    results = []
    for row in rows:
        item = dict(row)
        item["id"] = str(item["id"])
        item["project_id"] = str(item["project_id"])
        item["credential_id"] = str(item["credential_id"]) if item["credential_id"] else None
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else ""
        item["updated_at"] = item["updated_at"].isoformat() if item["updated_at"] else ""
        item["step_count"] = int(item["step_count"])
        results.append(item)
    return results


def get_scenario(db: Session, scenario_id: uuid.UUID) -> dict[str, Any]:
    """Retrieve scenario and its full list of ordered steps."""
    row = db.execute(
        text("""
            SELECT s.*, c.name as credential_name
            FROM test_scenarios s
            LEFT JOIN app_credentials c ON c.id = s.credential_id
            WHERE s.id = :id AND s.is_active = TRUE
        """),
        {"id": scenario_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    steps_rows = db.execute(
        text("""
            SELECT id, step_order, action_type, locator_type, locator_value,
                   action_params, description, is_enabled, timeout_ms
            FROM test_scenario_steps
            WHERE scenario_id = :id
            ORDER BY step_order ASC
        """),
        {"id": scenario_id},
    ).mappings().all()

    data = dict(row)
    data["id"] = str(data["id"])
    data["project_id"] = str(data["project_id"])
    data["credential_id"] = str(data["credential_id"]) if data["credential_id"] else None
    data["created_at"] = data["created_at"].isoformat() if data["created_at"] else ""
    data["updated_at"] = data["updated_at"].isoformat() if data["updated_at"] else ""
    data["steps"] = [dict(s) for s in steps_rows]
    return data


def update_scenario(
    db: Session,
    scenario_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    failure_policy: str | None = None,
    timeout_seconds: int | None = None,
    environment: str | None = None,
    credential_id: uuid.UUID | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update scenario details and optionally replace steps."""
    now = _now()
    updates = ["updated_at = :now"]
    params: dict[str, Any] = {"id": scenario_id, "now": now}

    if name is not None:
        updates.append("name = :name")
        params["name"] = name.strip()
    if description is not None:
        updates.append("description = :description")
        params["description"] = description
    if tags is not None:
        updates.append("tags = CAST(:tags AS jsonb)")
        params["tags"] = json.dumps(tags)
    if failure_policy is not None:
        updates.append("failure_policy = :failure_policy")
        params["failure_policy"] = failure_policy
    if timeout_seconds is not None:
        updates.append("timeout_seconds = :timeout_seconds")
        params["timeout_seconds"] = timeout_seconds
    if environment is not None:
        updates.append("environment = :environment")
        params["environment"] = environment
    if credential_id is not None or "credential_id" in params:
        updates.append("credential_id = :credential_id")
        params["credential_id"] = credential_id

    stmt = f"UPDATE test_scenarios SET {', '.join(updates)} WHERE id = :id"
    db.execute(text(stmt), params)

    if steps is not None:
        # Replace steps atomically
        db.execute(
            text("DELETE FROM test_scenario_steps WHERE scenario_id = :id"),
            {"id": scenario_id},
        )
        for idx, step_data in enumerate(steps, start=1):
            db.execute(
                text("""
                    INSERT INTO test_scenario_steps (
                        scenario_id, step_order, action_type, locator_type,
                        locator_value, action_params, description, is_enabled,
                        timeout_ms, created_at
                    )
                    VALUES (
                        :scenario_id, :step_order, :action_type, :locator_type,
                        :locator_value, CAST(:action_params AS jsonb), :description,
                        :is_enabled, :timeout_ms, :created_at
                    )
                """),
                {
                    "scenario_id": scenario_id,
                    "step_order": idx,
                    "action_type": step_data.get("action_type") or "click",
                    "locator_type": step_data.get("locator_type"),
                    "locator_value": step_data.get("locator_value"),
                    "action_params": json.dumps(step_data.get("action_params") or {}),
                    "description": step_data.get("description") or f"Step {idx}",
                    "is_enabled": step_data.get("is_enabled", True),
                    "timeout_ms": step_data.get("timeout_ms"),
                    "created_at": now,
                },
            )

    db.commit()
    return get_scenario(db, scenario_id)


def delete_scenario(db: Session, scenario_id: uuid.UUID) -> bool:
    """Soft-delete scenario by setting is_active = FALSE."""
    res = db.execute(
        text("UPDATE test_scenarios SET is_active = FALSE, updated_at = :now WHERE id = :id"),
        {"id": scenario_id, "now": _now()},
    )
    db.commit()
    return res.rowcount > 0


# =====================================================================
# Test Data Profiles
# =====================================================================

def create_data_profile(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    description: str | None = None,
    dataset_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required.")

    profile_id = uuid.uuid4()
    now = _now()
    rows_json = json.dumps(dataset_rows or [])

    db.execute(
        text("""
            INSERT INTO test_data_profiles (
                id, project_id, name, description, dataset_rows,
                created_at, updated_at
            )
            VALUES (
                :id, :project_id, :name, :description, CAST(:dataset_rows AS jsonb),
                :created_at, :updated_at
            )
        """),
        {
            "id": profile_id,
            "project_id": project_id,
            "name": name,
            "description": description,
            "dataset_rows": rows_json,
            "created_at": now,
            "updated_at": now,
        },
    )
    db.commit()

    return {
        "id": str(profile_id),
        "project_id": str(project_id),
        "name": name,
        "description": description or "",
        "dataset_rows": dataset_rows or [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def list_data_profiles(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT id, project_id, name, description, dataset_rows,
                   created_at, updated_at
            FROM test_data_profiles
            WHERE project_id = :pid
            ORDER BY created_at ASC
        """),
        {"pid": project_id},
    ).mappings().all()

    results = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["project_id"] = str(item["project_id"])
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else ""
        item["updated_at"] = item["updated_at"].isoformat() if item["updated_at"] else ""
        results.append(item)
    return results


def delete_data_profile(db: Session, profile_id: uuid.UUID) -> bool:
    res = db.execute(
        text("DELETE FROM test_data_profiles WHERE id = :id"),
        {"id": profile_id},
    )
    db.commit()
    return res.rowcount > 0


# =====================================================================
# Step Execution Results
# =====================================================================

def record_step_result(
    db: Session,
    run_id: uuid.UUID,
    scenario_id: uuid.UUID | None,
    step_order: int,
    action_type: str,
    description: str | None,
    status: str,
    duration_ms: int = 0,
    actual_value: str | None = None,
    expected_value: str | None = None,
    error_message: str | None = None,
    screenshot_artifact_id: int | None = None,
) -> dict[str, Any]:
    now = _now()
    row = db.execute(
        text("""
            INSERT INTO step_execution_results (
                run_id, scenario_id, step_order, action_type, description,
                status, duration_ms, actual_value, expected_value,
                error_message, screenshot_artifact_id, created_at
            )
            VALUES (
                :run_id, :scenario_id, :step_order, :action_type, :description,
                :status, :duration_ms, :actual_value, :expected_value,
                :error_message, :screenshot_artifact_id, :created_at
            )
            RETURNING id, run_id, scenario_id, step_order, action_type,
                      description, status, duration_ms, actual_value,
                      expected_value, error_message, screenshot_artifact_id, created_at
        """),
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "step_order": step_order,
            "action_type": action_type,
            "description": description,
            "status": status,
            "duration_ms": duration_ms,
            "actual_value": actual_value,
            "expected_value": expected_value,
            "error_message": error_message,
            "screenshot_artifact_id": screenshot_artifact_id,
            "created_at": now,
        },
    ).mappings().first()
    db.commit()

    item = dict(row)
    item["run_id"] = str(item["run_id"])
    item["scenario_id"] = str(item["scenario_id"]) if item["scenario_id"] else None
    item["created_at"] = item["created_at"].isoformat() if item["created_at"] else ""
    return item


def get_step_results(db: Session, run_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT s.*, a.relative_path as screenshot_path, a.id as screenshot_id
            FROM step_execution_results s
            LEFT JOIN artifacts a ON a.id = s.screenshot_artifact_id
            WHERE s.run_id = :rid
            ORDER BY s.step_order ASC
        """),
        {"rid": run_id},
    ).mappings().all()

    results = []
    for r in rows:
        item = dict(r)
        item["run_id"] = str(item["run_id"])
        item["scenario_id"] = str(item["scenario_id"]) if item["scenario_id"] else None
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else ""
        if item.get("screenshot_id"):
            item["screenshot_url"] = f"/api/artifacts/{item['screenshot_id']}/content"
        else:
            item["screenshot_url"] = None
        results.append(item)
    return results

