from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

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


def _write_registry(projects: list[dict]) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = REGISTRY_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps({"version": 1, "projects": projects}, indent=2), encoding="utf-8")
    temp_file.replace(REGISTRY_FILE)


def _read_registry() -> list[dict]:
    with _registry_lock:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_FILE.exists():
            projects = [_default_project()]
            _write_registry(projects)
            return projects
        try:
            data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            projects = data.get("projects", [])
            if not isinstance(projects, list):
                raise ValueError("projects must be a list")
            if not any(p.get("id") == "apex-timesheet" for p in projects):
                projects.insert(0, _default_project())
                _write_registry(projects)
            return projects
        except (OSError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            raise HTTPException(status_code=500, detail=f"Unable to read project registry: {exc}") from exc


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
            raise ValueError("Base URL must be a valid http:// or https:// URL.")
        return value.rstrip("/")

    @field_validator("test_directory")
    @classmethod
    def validate_test_directory(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Test directory must be a relative path inside the workspace.")
        return value.strip("/") or "tests"

    @field_validator("username_env_var", "password_env_var")
    @classmethod
    def validate_env_name(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Credential references must be environment-variable names, not secret values.")
        return value


@router.get("")
def list_projects():
    return _read_registry()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectPayload):
    with _registry_lock:
        projects = _read_registry()
        base_id = _safe_id(payload.name)
        project_id = base_id
        suffix = 2
        existing_ids = {project["id"] for project in projects}
        while project_id in existing_ids:
            project_id = f"{base_id}-{suffix}"
            suffix += 1
        now = _now()
        project = {"id": project_id, **payload.model_dump(), "is_default": False, "created_at": now, "updated_at": now}
        projects.append(project)
        _write_registry(projects)
        return project


@router.put("/{project_id}")
def update_project(project_id: str, payload: ProjectPayload):
    with _registry_lock:
        projects = _read_registry()
        for index, current in enumerate(projects):
            if current["id"] == project_id:
                updated = {**current, **payload.model_dump(), "updated_at": _now()}
                projects[index] = updated
                _write_registry(projects)
                return updated
        raise HTTPException(status_code=404, detail="Project not found.")


@router.delete("/{project_id}")
def delete_project(project_id: str):
    if project_id == "apex-timesheet":
        raise HTTPException(status_code=400, detail="The default APEX Timesheet project cannot be deleted.")
    with _registry_lock:
        projects = _read_registry()
        remaining = [project for project in projects if project["id"] != project_id]
        if len(remaining) == len(projects):
            raise HTTPException(status_code=404, detail="Project not found.")
        _write_registry(remaining)
    return {"message": "Project configuration removed. Test files were not deleted."}
