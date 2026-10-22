
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database import SessionLocal

router = APIRouter(prefix="/api/projects", tags=["Projects"])

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_DIR = ROOT / "config"
REGISTRY_FILE = REGISTRY_DIR / "projects.json"
_registry_lock = RLock()

ProjectType = Literal["Web application", "API application", "Full-stack application"]
EnvironmentName = Literal["Development", "QA", "Staging", "Production"]
BrowserName = Literal["chromium", "firefox", "webkit"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_project() -> dict:
    now = _now()
    return {
        "id": "apex-timesheet",
        "name": "APEX Timesheet",
        "project_type": "Web application",
        "base_url": "http://127.0.0.1:8000",
        "test_directory": "tests",
        "default_environment": "QA",
        "browser": "chromium",
        "headless": True,
        "capture_screenshots": True,
        "capture_video": False,
        "username_env_var": "",
        "password_env_var": "",
        "is_default": True,
        "created_at": now,
        "updated_at": now,
    }


def _read_registry() -> list[dict]:
    """Read the JSON registry as a migration/recovery source."""
    with _registry_lock:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

        if not REGISTRY_FILE.exists():
            return [_default_project()]

        try:
            data = json.loads(
                REGISTRY_FILE.read_text(encoding="utf-8")
            )
            projects = data.get("projects", [])

            if not isinstance(projects, list):
                raise ValueError("projects must be a list")

            return projects

        except (OSError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Unable to read project registry: {exc}",
            ) from exc


def _safe_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "project"


class ProjectPayload(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    project_type: ProjectType = "Web application"
    base_url: str = Field(min_length=8, max_length=2048)
    test_directory: str = Field(default="tests", min_length=1, max_length=240)
    default_environment: EnvironmentName = "QA"
    browser: BrowserName = "chromium"
    headless: bool = True
    capture_screenshots: bool = True
    capture_video: bool = False
    username_env_var: str = Field(default="", max_length=100)
    password_env_var: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    test_timeout_seconds: int = Field(default=60, ge=5, le=600)
    navigation_timeout_seconds: int = Field(default=30, ge=5, le=300)
    default_wait_ms: int = Field(default=500, ge=0, le=10000)
    auth_method: str = Field(default="form", max_length=50)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name is required.")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "Base URL must be a valid http:// or https:// URL."
            )
        return value.rstrip("/")

    @field_validator("test_directory")
    @classmethod
    def validate_test_directory(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        path = Path(value)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "Test directory must be a relative path inside the workspace."
            )

        return value.strip("/") or "tests"

    @field_validator("username_env_var", "password_env_var")
    @classmethod
    def validate_env_name(cls, value: str) -> str:
        value = value.strip()

        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(
                "Credential references must be environment-variable names, "
                "not secret values."
            )

        return value


def _project_dict(row) -> dict:
    """Convert a PostgreSQL row to the existing API response format."""
    return {
        "id": row["external_id"],
        "name": row["name"],
        "project_type": row["project_type"],
        "base_url": row["base_url"],
        "test_directory": row["test_directory"],
        "default_environment": row["default_environment"],
        "browser": row["browser"],
        "headless": row["headless"],
        "capture_screenshots": row["capture_screenshots"],
        "capture_video": row["capture_video"],
        "username_env_var": row["username_env_var"] or "",
        "password_env_var": row["password_env_var"] or "",
        "description": row.get("description") or "",
        "test_timeout_seconds": row.get("test_timeout_seconds") or 60,
        "navigation_timeout_seconds": row.get("navigation_timeout_seconds") or 30,
        "default_wait_ms": row.get("default_wait_ms") or 500,
        "auth_method": row.get("auth_method") or "form",
        "is_default": row["is_default"],
        "is_active": bool(row["is_active"]) if row.get("is_active") is not None else True,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _insert_project(db, project: dict) -> None:
    """Insert one project into PostgreSQL."""
    now = _now()

    db.execute(
        text(
            """
            INSERT INTO projects (
                id, external_id, name, project_type, base_url,
                test_directory, default_environment, browser, headless,
                capture_screenshots, capture_video, username_env_var,
                password_env_var, description, test_timeout_seconds,
                navigation_timeout_seconds, default_wait_ms, auth_method,
                is_default, is_active, created_at, updated_at
            )
            VALUES (
                :id, :external_id, :name, :project_type, :base_url,
                :test_directory, :default_environment, :browser, :headless,
                :capture_screenshots, :capture_video, :username_env_var,
                :password_env_var, :description, :test_timeout_seconds,
                :navigation_timeout_seconds, :default_wait_ms, :auth_method,
                :is_default, TRUE, :created_at, :updated_at
            )
            """
        ),
        {
            "id": str(uuid4()),
            "external_id": project["id"],
            "name": project["name"],
            "project_type": project["project_type"],
            "base_url": project["base_url"],
            "test_directory": project.get("test_directory", "tests"),
            "default_environment": project.get("default_environment", "QA"),
            "browser": project.get("browser", "chromium"),
            "headless": project.get("headless", True),
            "capture_screenshots": project.get("capture_screenshots", True),
            "capture_video": project.get("capture_video", False),
            "username_env_var": project.get("username_env_var") or None,
            "password_env_var": project.get("password_env_var") or None,
            "description": project.get("description") or None,
            "test_timeout_seconds": project.get("test_timeout_seconds", 60),
            "navigation_timeout_seconds": project.get("navigation_timeout_seconds", 30),
            "default_wait_ms": project.get("default_wait_ms", 500),
            "auth_method": project.get("auth_method", "form"),
            "is_default": project.get("is_default", False),
            "created_at": project.get("created_at", now),
            "updated_at": project.get("updated_at", now),
        },
    )


def _ensure_projects_exist() -> None:
    """
    Keep existing JSON projects available if PostgreSQL is empty.
    Existing database records are never overwritten by this fallback.
    """
    with _registry_lock:
        db = SessionLocal()

        try:
            count = db.execute(
                text("SELECT COUNT(*) FROM projects")
            ).scalar_one()

            if count:
                return

            projects = _read_registry()

            for project in projects:
                _insert_project(db, project)

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()


def _list_projects_from_db() -> list[dict]:
    _ensure_projects_exist()

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT *
                FROM projects
                ORDER BY is_default DESC, created_at ASC
                """
            )
        ).mappings().all()

        return [_project_dict(row) for row in rows]

    finally:
        db.close()


@router.get("")
def list_projects():
    try:
        return _list_projects_from_db()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to read projects from PostgreSQL.",
        ) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectPayload):
    try:
        with _registry_lock:
            db = SessionLocal()

            try:
                existing_ids = set(
                    db.execute(
                        text("SELECT external_id FROM projects")
                    ).scalars().all()
                )

                base_id = _safe_id(payload.name)
                project_id = base_id
                suffix = 2

                while project_id in existing_ids:
                    project_id = f"{base_id}-{suffix}"
                    suffix += 1

                now = _now()
                project = {
                    "id": project_id,
                    **payload.model_dump(),
                    "is_default": False,
                    "created_at": now,
                    "updated_at": now,
                }

                _insert_project(db, project)
                db.commit()

                return project

            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="A project with this name already exists.",
                ) from exc

            except Exception:
                db.rollback()
                raise

            finally:
                db.close()

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to create project in PostgreSQL.",
        ) from exc


@router.put("/{project_id}")
def update_project(project_id: str, payload: ProjectPayload):
    db = SessionLocal()

    try:
        row = db.execute(
            text(
                """
                SELECT *
                FROM projects
                WHERE external_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).mappings().first()

        if row is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        updated = {
            **_project_dict(row),
            **payload.model_dump(),
            "updated_at": _now(),
        }

        db.execute(
            text(
                """
                UPDATE projects
                SET name = :name,
                    project_type = :project_type,
                    base_url = :base_url,
                    test_directory = :test_directory,
                    default_environment = :default_environment,
                    browser = :browser,
                    headless = :headless,
                    capture_screenshots = :capture_screenshots,
                    capture_video = :capture_video,
                    username_env_var = :username_env_var,
                    password_env_var = :password_env_var,
                    description = :description,
                    test_timeout_seconds = :test_timeout_seconds,
                    navigation_timeout_seconds = :navigation_timeout_seconds,
                    default_wait_ms = :default_wait_ms,
                    auth_method = :auth_method,
                    is_active = :is_active,
                    updated_at = :updated_at
                WHERE external_id = :project_id
                """
            ),
            {
                **payload.model_dump(),
                "username_env_var": payload.username_env_var or None,
                "password_env_var": payload.password_env_var or None,
                "description": payload.description or None,
                "is_active": payload.is_active,
                "updated_at": updated["updated_at"],
                "project_id": project_id,
            },
        )

        db.commit()
        return updated

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A project with this name already exists.",
        ) from exc

    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to update project in PostgreSQL.",
        ) from exc

    finally:
        db.close()


@router.delete("/{project_id}")
def delete_project(project_id: str):
    if project_id == "apex-timesheet":
        raise HTTPException(
            status_code=400,
            detail="The default APEX Timesheet project cannot be deleted.",
        )

    db = SessionLocal()

    try:
        result = db.execute(
            text(
                """
                UPDATE projects
                SET is_active = FALSE,
                    updated_at = :updated_at
                WHERE external_id = :project_id
                  AND is_active = TRUE
                """
            ),
            {
                "project_id": project_id,
                "updated_at": _now(),
            },
        )

        if result.rowcount == 0:
            db.rollback()
            raise HTTPException(
                status_code=404,
                detail="Project not found.",
            )

        db.commit()

        return {
            "message": "Project configuration removed. Test files were not deleted."
        }

    except HTTPException:
        raise

    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to delete project from PostgreSQL.",
        ) from exc

    finally:
        db.close()


@router.patch("/{project_id}/toggle-active")
def toggle_project_active(project_id: str):
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id, is_active FROM projects WHERE external_id = :project_id"),
            {"project_id": project_id},
        ).mappings().first()

        if row is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        current = bool(row["is_active"])
        new_status = not current
        now = _now()

        db.execute(
            text(
                """
                UPDATE projects
                SET is_active = :status,
                    updated_at = :now
                WHERE external_id = :project_id
                """
            ),
            {"status": new_status, "now": now, "project_id": project_id},
        )
        db.commit()

        return {
            "id": project_id,
            "is_active": new_status,
            "message": f"Project is now {'Active' if new_status else 'Inactive'}.",
        }
    finally:
        db.close()
