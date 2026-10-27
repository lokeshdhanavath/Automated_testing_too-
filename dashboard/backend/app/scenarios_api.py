"""
API Router for Generic Test Scenarios, Steps, App Credentials, and Test Data Profiles.
"""
from __future__ import annotations

import os
import time
import uuid
from threading import Thread
from typing import Any, Literal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app import db_service
from app import credentials_service
from app import scenarios_service
from app import scenario_engine

router = APIRouter(prefix="/api", tags=["Scenarios & Credentials"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"


# =====================================================================
# Request / Response Models
# =====================================================================

class CredentialPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=255)
    secret: str = Field(min_length=1, max_length=1024)
    environment: str = Field(default="QA", max_length=50)
    description: str | None = Field(default=None, max_length=500)
    credential_type: str = Field(default="username_password", max_length=50)


class CredentialUpdatePayload(BaseModel):
    name: str | None = None
    username: str | None = None
    secret: str | None = None
    environment: str | None = None
    description: str | None = None


class StepPayload(BaseModel):
    step_order: int | None = None
    action_type: str = Field(default="click")
    locator_type: str | None = Field(default="css")
    locator_value: str | None = Field(default="")
    action_params: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    is_enabled: bool = True
    timeout_ms: int | None = None
    on_fail: str | None = None


class ScenarioCreatePayload(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    failure_policy: Literal["stop", "continue"] = "stop"
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    environment: str = "QA"
    credential_id: str | None = None
    steps: list[StepPayload] = Field(default_factory=list)


class ScenarioUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    failure_policy: Literal["stop", "continue"] | None = None
    timeout_seconds: int | None = None
    environment: str | None = None
    credential_id: str | None = None
    steps: list[StepPayload] | None = None


class ScenarioRunPayload(BaseModel):
    environment: str | None = None
    credential_id: str | None = None
    data_profile_id: str | None = None
    dataset_row_index: int | None = 0
    headless: bool | None = None
    browser: str | None = None


class DynamicWorkflowPayload(BaseModel):
    name: str = Field(default="Dynamic Browser Workflow", max_length=200)
    description: str | None = None
    environment: str = "QA"
    credential_id: str | None = None
    failure_policy: Literal["stop", "continue"] = "stop"
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    steps: list[StepPayload] = Field(default_factory=list)
    save_as_scenario: bool = False
    dataset_row: dict[str, Any] | None = None
    dataset_rows: list[dict[str, Any]] | None = None
    headless: bool | None = None
    browser: str | None = None


class DataProfilePayload(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    dataset_rows: list[dict[str, Any]] = Field(default_factory=list)


# =====================================================================
# Credentials Endpoints
# =====================================================================

@router.get("/projects/{project_id}/credentials")
def get_project_credentials(project_id: str):
    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        creds = credentials_service.list_credentials(db, project["id"])
        return creds
    finally:
        db.close()


@router.post("/projects/{project_id}/credentials", status_code=status.HTTP_201_CREATED)
def create_project_credential(project_id: str, payload: CredentialPayload):
    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        cred = credentials_service.create_credential(
            db=db,
            project_id=project["id"],
            name=payload.name,
            username=payload.username,
            secret=payload.secret,
            environment=payload.environment,
            description=payload.description,
            credential_type=payload.credential_type,
        )
        return cred
    finally:
        db.close()


@router.put("/credentials/{credential_id}")
def update_credential_endpoint(credential_id: str, payload: CredentialUpdatePayload):
    db: Session = SessionLocal()
    try:
        c_uuid = uuid.UUID(credential_id)
        updated = credentials_service.update_credential(
            db=db,
            credential_id=c_uuid,
            name=payload.name,
            username=payload.username,
            secret=payload.secret,
            environment=payload.environment,
            description=payload.description,
        )
        return updated
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid credential ID.")
    finally:
        db.close()


@router.delete("/credentials/{credential_id}")
def delete_credential_endpoint(credential_id: str):
    db: Session = SessionLocal()
    try:
        c_uuid = uuid.UUID(credential_id)
        deleted = credentials_service.delete_credential(db, c_uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Credential not found.")
        return {"message": "Credential removed successfully."}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid credential ID.")
    finally:
        db.close()


# =====================================================================
# Scenarios Endpoints
# =====================================================================

@router.get("/projects/{project_id}/scenarios")
def list_project_scenarios(project_id: str):
    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        scenarios = scenarios_service.list_scenarios(db, project["id"])
        return scenarios
    finally:
        db.close()


@router.post("/projects/{project_id}/scenarios", status_code=status.HTTP_201_CREATED)
def create_scenario_endpoint(project_id: str, payload: ScenarioCreatePayload):
    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        cred_uuid = uuid.UUID(payload.credential_id) if payload.credential_id else None
        steps_dicts = [s.model_dump() for s in payload.steps]

        created = scenarios_service.create_scenario(
            db=db,
            project_id=project["id"],
            name=payload.name,
            description=payload.description,
            tags=payload.tags,
            failure_policy=payload.failure_policy,
            timeout_seconds=payload.timeout_seconds,
            environment=payload.environment,
            credential_id=cred_uuid,
            steps=steps_dicts,
        )
        return created
    finally:
        db.close()


@router.get("/scenarios/{scenario_id}")
def get_scenario_endpoint(scenario_id: str):
    db: Session = SessionLocal()
    try:
        s_uuid = uuid.UUID(scenario_id)
        return scenarios_service.get_scenario(db, s_uuid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scenario ID.")
    finally:
        db.close()


@router.put("/scenarios/{scenario_id}")
def update_scenario_endpoint(scenario_id: str, payload: ScenarioUpdatePayload):
    db: Session = SessionLocal()
    try:
        s_uuid = uuid.UUID(scenario_id)
        cred_uuid = uuid.UUID(payload.credential_id) if payload.credential_id else None
        steps_dicts = [s.model_dump() for s in payload.steps] if payload.steps is not None else None

        updated = scenarios_service.update_scenario(
            db=db,
            scenario_id=s_uuid,
            name=payload.name,
            description=payload.description,
            tags=payload.tags,
            failure_policy=payload.failure_policy,
            timeout_seconds=payload.timeout_seconds,
            environment=payload.environment,
            credential_id=cred_uuid,
            steps=steps_dicts,
        )
        return updated
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scenario ID.")
    finally:
        db.close()


@router.delete("/scenarios/{scenario_id}")
def delete_scenario_endpoint(scenario_id: str):
    db: Session = SessionLocal()
    try:
        s_uuid = uuid.UUID(scenario_id)
        deleted = scenarios_service.delete_scenario(db, s_uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        return {"message": "Scenario removed successfully."}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scenario ID.")
    finally:
        db.close()


# =====================================================================
# Test Data Profiles Endpoints
# =====================================================================

@router.get("/projects/{project_id}/data-profiles")
def get_project_data_profiles(project_id: str):
    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        profiles = scenarios_service.list_data_profiles(db, project["id"])
        return profiles
    finally:
        db.close()


@router.post("/projects/{project_id}/data-profiles", status_code=status.HTTP_201_CREATED)
def create_project_data_profile(project_id: str, payload: DataProfilePayload):
    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        profile = scenarios_service.create_data_profile(
            db=db,
            project_id=project["id"],
            name=payload.name,
            description=payload.description,
            dataset_rows=payload.dataset_rows,
        )
        return profile
    finally:
        db.close()


@router.delete("/data-profiles/{profile_id}")
def delete_data_profile_endpoint(profile_id: str):
    db: Session = SessionLocal()
    try:
        p_uuid = uuid.UUID(profile_id)
        deleted = scenarios_service.delete_data_profile(db, p_uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Data profile not found.")
        return {"message": "Data profile removed successfully."}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID.")
    finally:
        db.close()


# =====================================================================
# Step Execution Results & Scenario Run Endpoints
# =====================================================================

@router.get("/runs/{run_id}/steps")
def get_run_step_results(run_id: str):
    db: Session = SessionLocal()
    try:
        r_uuid = uuid.UUID(run_id)
        return scenarios_service.get_step_results(db, r_uuid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run ID.")
    finally:
        db.close()


def _execute_scenario_background(
    run_uuid: uuid.UUID,
    project: dict[str, Any],
    scenario: dict[str, Any],
    decrypted_credentials: dict[str, str] | None,
    dataset_row: dict[str, Any] | None,
):
    """Worker function executing scenario in a separate background thread."""
    from app.main import runs, lock, active_run_id

    db: Session = SessionLocal()
    run_id_str = str(run_uuid)
    try:
        result = scenario_engine.run_generic_scenario(
            db=db,
            run_uuid=run_uuid,
            project=project,
            scenario=scenario,
            decrypted_credentials=decrypted_credentials,
            dataset_row=dataset_row,
        )
        with lock:
            if run_id_str in runs:
                runs[run_id_str]["status"] = result.get("status", "passed")
                runs[run_id_str]["summary"] = result.get("summary")
    except Exception as exc:
        db_service.update_test_run(
            db,
            run_uuid,
            status="error",
            summary={"error": str(exc)},
        )
        with lock:
            if run_id_str in runs:
                runs[run_id_str]["status"] = "error"
                runs[run_id_str]["logs"] += f"\nEngine error: {exc}\n"
    finally:
        db.close()
        with lock:
            from app import main
            if main.active_run_id == run_id_str:
                main.active_run_id = None


@router.post("/scenarios/{scenario_id}/run")
def trigger_scenario_run(scenario_id: str, payload: ScenarioRunPayload):
    from app.main import runs, lock, active_run_id
    import app.main as main_mod

    db: Session = SessionLocal()
    try:
        s_uuid = uuid.UUID(scenario_id)
        scenario = scenarios_service.get_scenario(db, s_uuid)
        project_uuid = uuid.UUID(scenario["project_id"])
        project = db_service.resolve_project(db, str(project_uuid))

        # Check concurrency lock
        with lock:
            if main_mod.active_run_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Another test run is already in progress.",
                )

        # Resolve credential if specified or default from scenario
        cred_id_str = payload.credential_id or scenario.get("credential_id")
        decrypted_cred = None
        if cred_id_str:
            try:
                decrypted_cred = credentials_service.get_decrypted_credential(db, uuid.UUID(cred_id_str))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to load credentials: {e}")

        # If not explicitly specified on the scenario, auto-resolve from the application's stored credentials in DB
        if not decrypted_cred:
            try:
                proj_creds = credentials_service.list_credentials(db, project["id"])
                if proj_creds:
                    target_env = str(payload.environment or scenario.get("environment") or project.get("default_environment", "QA")).lower()
                    matched = next((c for c in proj_creds if str(c.get("environment", "")).lower() == target_env), proj_creds[0])
                    decrypted_cred = credentials_service.get_decrypted_credential(db, uuid.UUID(matched["id"]))
            except Exception:
                pass

        # If still none, check if project specifies custom environment variable names
        if not decrypted_cred:
            user_env = project.get("username_env_var")
            pass_env = project.get("password_env_var")
            if user_env and os.getenv(user_env):
                decrypted_cred = {
                    "username": os.getenv(user_env, ""),
                    "secret": os.getenv(pass_env, "") if pass_env else "",
                }

        # Resolve dataset row if specified
        dataset_row = None
        dataset_name = None
        if payload.data_profile_id:
            try:
                prof = db.execute(
                    db_service.text("SELECT * FROM test_data_profiles WHERE id = :id"),
                    {"id": uuid.UUID(payload.data_profile_id)},
                ).mappings().first()
                if prof:
                    dataset_name = prof["name"]
                    rows = prof.get("dataset_rows") or []
                    idx = payload.dataset_row_index or 0
                    if 0 <= idx < len(rows):
                        dataset_row = rows[idx]
            except Exception:
                pass

        run_uuid = uuid.uuid4()
        run_id_str = str(run_uuid)

        # Initialize in-memory run tracking
        with lock:
            main_mod.runs[run_id_str] = {
                "id": run_id_str,
                "project_id": project["external_id"],
                "status": "queued",
                "created_at": time.time(),
                "logs": f"Queued scenario: {scenario['name']}\n",
                "exit_code": None,
                "summary": None,
                "test_ids": [f"Scenario: {scenario['name']}"],
            }
            main_mod.active_run_id = run_id_str

        # Apply runtime headless / browser overrides if specified
        project = dict(project)
        scenario = dict(scenario)
        if payload.headless is not None:
            project["headless"] = payload.headless
            scenario["headless"] = payload.headless
        if payload.browser:
            project["browser"] = payload.browser
            scenario["browser"] = payload.browser

        # Persist test run in DB
        db_service.create_test_run(
            db=db,
            run_uuid=run_uuid,
            project_uuid=project_uuid,
            environment=payload.environment or scenario.get("environment") or "QA",
            browser=project.get("browser", "chromium"),
            selected_tests=[f"Scenario: {scenario['name']}"],
        )

        # Record scenario_id in test_runs table
        db.execute(
            db_service.text("""
                UPDATE test_runs
                SET scenario_id = :sid, dataset_name = :dname, dataset_row_index = :didx
                WHERE id = :rid
            """),
            {
                "sid": s_uuid,
                "dname": dataset_name,
                "didx": payload.dataset_row_index,
                "rid": run_uuid,
            },
        )
        db.commit()

        # Launch background thread
        Thread(
            target=_execute_scenario_background,
            args=(run_uuid, project, scenario, decrypted_cred, dataset_row),
            daemon=True,
        ).start()

        return {
            "run_id": run_id_str,
            "project_id": project["external_id"],
            "scenario_id": str(s_uuid),
            "status": "queued",
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID.")
    finally:
        db.close()


@router.post("/projects/{project_id}/workflows/run")
def trigger_dynamic_workflow_run(project_id: str, payload: DynamicWorkflowPayload):
    """
    Executes an ad-hoc dynamic workflow on-the-fly without requiring
    predefined test suites or python scripts.
    Automatically retrieves the application's base URL and vault credentials.
    """
    from app.main import runs, lock, active_run_id
    import app.main as main_mod

    db: Session = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found.")

        project_uuid = project["id"]

        # Check concurrency lock
        with lock:
            if main_mod.active_run_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Another test run is already in progress.",
                )

        # Securely resolve credentials from DB vault without requiring user re-entry
        decrypted_cred = None
        if payload.credential_id:
            try:
                decrypted_cred = credentials_service.get_decrypted_credential(db, uuid.UUID(payload.credential_id))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to load credentials: {e}")

        if not decrypted_cred:
            try:
                proj_creds = credentials_service.list_credentials(db, project_uuid)
                if proj_creds:
                    target_env = str(payload.environment or project.get("default_environment", "QA")).lower()
                    matched = next((c for c in proj_creds if str(c.get("environment", "")).lower() == target_env), proj_creds[0])
                    decrypted_cred = credentials_service.get_decrypted_credential(db, uuid.UUID(matched["id"]))
            except Exception:
                pass

        if not decrypted_cred:
            user_env = project.get("username_env_var")
            pass_env = project.get("password_env_var")
            if user_env and os.getenv(user_env):
                decrypted_cred = {
                    "username": os.getenv(user_env, ""),
                    "secret": os.getenv(pass_env, "") if pass_env else "",
                }

        # Build steps representation
        steps_dicts = []
        for idx, s in enumerate(payload.steps, start=1):
            steps_dicts.append({
                "step_order": s.step_order or idx,
                "action_type": s.action_type,
                "locator_type": s.locator_type,
                "locator_value": s.locator_value or "",
                "action_params": s.action_params or {},
                "description": s.description or f"Step {idx}: {s.action_type}",
                "is_enabled": s.is_enabled,
                "timeout_ms": s.timeout_ms,
                "on_fail": s.on_fail,
            })

        scenario_uuid = None
        if payload.save_as_scenario:
            try:
                saved = scenarios_service.create_scenario(
                    db=db,
                    project_id=project_uuid,
                    name=payload.name,
                    description=payload.description or "Dynamic workflow saved from Scenario Builder",
                    tags=["dynamic-workflow"],
                    failure_policy=payload.failure_policy,
                    timeout_seconds=payload.timeout_seconds,
                    environment=payload.environment,
                    credential_id=uuid.UUID(payload.credential_id) if payload.credential_id else None,
                    steps=steps_dicts,
                )
                scenario_uuid = uuid.UUID(saved["id"])
            except Exception:
                pass

        # Apply runtime headless / browser overrides if specified
        project = dict(project)
        if payload.headless is not None:
            project["headless"] = payload.headless
        if payload.browser:
            project["browser"] = payload.browser

        scenario_dict = {
            "id": str(scenario_uuid) if scenario_uuid else None,
            "name": payload.name,
            "environment": payload.environment,
            "failure_policy": payload.failure_policy,
            "timeout_seconds": payload.timeout_seconds,
            "steps": steps_dicts,
            "headless": payload.headless if payload.headless is not None else project.get("headless", True),
            "browser": payload.browser or project.get("browser", "chromium"),
        }

        run_uuid = uuid.uuid4()
        run_id_str = str(run_uuid)

        # Initialize in-memory run tracking
        with lock:
            main_mod.runs[run_id_str] = {
                "id": run_id_str,
                "project_id": project["external_id"],
                "status": "queued",
                "created_at": time.time(),
                "logs": f"Queued dynamic workflow: {payload.name} ({len(steps_dicts)} steps)\n",
                "exit_code": None,
                "summary": None,
                "test_ids": [f"Workflow: {payload.name}"],
            }
            main_mod.active_run_id = run_id_str

        # Persist test run in DB
        db_service.create_test_run(
            db=db,
            run_uuid=run_uuid,
            project_uuid=project_uuid,
            environment=payload.environment,
            browser=project.get("browser", "chromium"),
            selected_tests=[f"Workflow: {payload.name}"],
        )

        if scenario_uuid:
            db.execute(
                db_service.text("UPDATE test_runs SET scenario_id = :sid WHERE id = :rid"),
                {"sid": scenario_uuid, "rid": run_uuid},
            )
            db.commit()

        # Launch background execution thread
        Thread(
            target=_execute_scenario_background,
            args=(run_uuid, project, scenario_dict, decrypted_cred, payload.dataset_row),
            daemon=True,
        ).start()

        return {
            "run_id": run_id_str,
            "project_id": project["external_id"],
            "scenario_id": str(scenario_uuid) if scenario_uuid else None,
            "status": "queued",
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID.")
    finally:
        db.close()


