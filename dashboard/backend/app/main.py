from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

# Ensure backend directory and project root are always on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent.parent
for p in (BACKEND_DIR, ROOT_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import SessionLocal
from app import db_service, credentials_service
from app.csv_scenarios import router as csv_scenarios_router
from app.projects_api import router as projects_router
from app.scripts_api import router as scripts_router
from app.scenarios_api import router as scenarios_router
from app.inspector_api import router as inspector_router


# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parents[3]

TESTS_DIR = ROOT / "tests"
REPORT_DIR = ROOT / "reports" / "json"
XML_DIR = ROOT / "reports" / "xml"
VIDEO_DIR = ROOT / "videos"
SCREENSHOT_DIR = ROOT / "screenshots"
ARTIFACTS_ROOT = ROOT / "artifacts"

for folder in (REPORT_DIR, XML_DIR, VIDEO_DIR, SCREENSHOT_DIR, ARTIFACTS_ROOT):
    folder.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(title="Veriqon Automated Testing Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scripts_router)
app.include_router(csv_scenarios_router)
app.include_router(projects_router)
app.include_router(scenarios_router)
app.include_router(inspector_router)

lock = Lock()
runs: dict[str, dict[str, Any]] = {}
active_run_id: str | None = None


# ---------------------------------------------------------
# Request models
# ---------------------------------------------------------

class RunRequest(BaseModel):
    project_id: str | None = None
    test_file: str | None = None
    test_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------
# Pytest test discovery
# ---------------------------------------------------------

def discover_tests(test_directory: str = "tests") -> list[str]:
    """Discover real pytest node IDs safely within the configured test directory."""
    safe_dir = Path(test_directory).as_posix().strip("/")
    target_path = ROOT / safe_dir

    if not target_path.exists() or not target_path.is_dir():
        target_path = ROOT / "tests"

    command = [
        sys.executable,
        "-m",
        "pytest",
        str(target_path.relative_to(ROOT)),
        "--collect-only",
        "-q",
        "-o",
        "addopts=",
    ]

    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Pytest test discovery timed out.",
        ) from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Pytest test discovery failed",
                "output": (result.stdout + "\n" + result.stderr)[-8000:],
            },
        )

    tests = []
    prefix = f"{safe_dir}/" if not safe_dir.endswith("/") else safe_dir

    for line in result.stdout.splitlines():
        line = line.strip()
        # Accept node IDs starting with the target directory
        if "::" not in line:
            continue
        test_path = line.split("::", 1)[0]
        if not test_path.endswith(".py"):
            continue
        tests.append(line)

    return list(dict.fromkeys(tests))


# ---------------------------------------------------------
# Report parsing
# ---------------------------------------------------------

def read_report(run_id: str, project_external_id: str | None = None) -> dict[str, Any] | None:
    """Read this dashboard run's JUnit XML and return a summary."""
    paths_to_check = []
    if project_external_id:
        paths_to_check.append(
            ARTIFACTS_ROOT / project_external_id / run_id / "reports" / "xml" / f"{run_id}.xml"
        )
    paths_to_check.append(XML_DIR / f"{run_id}.xml")

    xml_path = next((p for p in paths_to_check if p.is_file()), None)
    if not xml_path:
        return None

    try:
        root = ET.parse(xml_path).getroot()
        if root.tag == "testsuite":
            suites = [root]
        else:
            suites = root.findall(".//testsuite")

        total = 0
        failures = 0
        errors = 0
        skipped = 0

        for suite in suites:
            total += int(suite.attrib.get("tests", 0))
            failures += int(suite.attrib.get("failures", 0))
            errors += int(suite.attrib.get("errors", 0))
            skipped += int(suite.attrib.get("skipped", 0))

        passed = max(0, total - failures - errors - skipped)

        return {
            "total": total,
            "passed": passed,
            "failed": failures,
            "errors": errors,
            "skipped": skipped,
            "report_file": str(xml_path),
        }
    except (ET.ParseError, OSError, ValueError):
        return None


def get_json_report(run_id: str, project_external_id: str | None = None) -> dict[str, Any] | None:
    """Return a JSON report for this dashboard run if available."""
    paths_to_check = []
    if project_external_id:
        paths_to_check.append(
            ARTIFACTS_ROOT / project_external_id / run_id / "reports" / "json" / f"run_{run_id}.json"
        )
    paths_to_check.append(REPORT_DIR / f"run_{run_id}.json")

    json_path = next((p for p in paths_to_check if p.is_file()), None)
    if not json_path:
        return None

    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------
# Test execution worker
# ---------------------------------------------------------

def execute_run(run_id: str, project_data: dict[str, Any], request_data: dict[str, Any]) -> None:
    global active_run_id

    run_uuid = uuid.UUID(run_id)
    project_uuid = project_data["id"] if isinstance(project_data["id"], uuid.UUID) else uuid.UUID(str(project_data["id"]))
    project_ext_id = project_data.get("external_id") or "apex-timesheet"

    # Set up isolated project & run artifact directory structure
    # artifacts/<project_id>/<run_id>/
    run_artifact_dir = ARTIFACTS_ROOT / project_ext_id / run_id
    screenshots_dir = run_artifact_dir / "screenshots"
    videos_dir = run_artifact_dir / "videos"
    reports_dir = run_artifact_dir / "reports"
    xml_dir = reports_dir / "xml"
    logs_dir = reports_dir / "logs"

    for d in (screenshots_dir, videos_dir, xml_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    junit_path = xml_dir / f"{run_id}.xml"
    log_file_path = logs_dir / f"run_{run_id}.log"

    command = [
        sys.executable,
        str(ROOT / "run_all.py"),
    ]

    if request_data.get("test_ids"):
        command.extend(request_data["test_ids"])
    elif request_data.get("test_file"):
        command.append(request_data["test_file"])

    command.extend(["--junitxml", str(junit_path)])

    # Mark as running in DB
    db = SessionLocal()
    started_time = datetime.now(timezone.utc)
    try:
        db_service.update_test_run(
            db,
            run_uuid,
            status="running",
            started_at=started_time,
            log_path=str(log_file_path.relative_to(ROOT)).replace("\\", "/"),
        )
    finally:
        db.close()

    with lock:
        if run_id in runs:
            runs[run_id]["status"] = "running"
            runs[run_id]["started_at"] = time.time()
            runs[run_id]["command"] = command

    try:
        env = os.environ.copy()
        env["DASHBOARD_RUN_ID"] = run_id
        env["VERIQON_PROJECT_ID"] = project_ext_id
        env["VERIQON_PROJECT_UUID"] = str(project_uuid)
        env["VERIQON_HEADLESS"] = str(project_data.get("headless", True)).lower()
        env["VERIQON_BROWSER"] = str(project_data.get("browser", "chromium")).lower()
        env["VERIQON_CAPTURE_SCREENSHOTS"] = str(project_data.get("capture_screenshots", True)).lower()
        env["VERIQON_CAPTURE_VIDEO"] = str(project_data.get("capture_video", False)).lower()
        env["VERIQON_BASE_URL"] = str(project_data.get("base_url", "")).rstrip("/")

        # Check if project has encrypted database credentials in app_credentials
        db_username = None
        db_password = None
        try:
            with SessionLocal() as db_session:
                cred_rows = credentials_service.list_credentials(db_session, project_uuid)
                if cred_rows:
                    target_env = str(project_data.get("default_environment", "QA")).lower()
                    matched = next((c for c in cred_rows if str(c.get("environment", "")).lower() == target_env), cred_rows[0])
                    decrypted_c = credentials_service.get_decrypted_credential(db_session, uuid.UUID(matched["id"]))
                    db_username = decrypted_c.get("username", "")
                    db_password = decrypted_c.get("secret", "")
        except Exception as e:
            pass

        if db_username:
            env["VERIQON_USERNAME"] = db_username
            env["VERIQON_PASSWORD"] = db_password or ""
        else:
            # Safely check if custom environment variables were specified
            user_env = project_data.get("username_env_var")
            pass_env = project_data.get("password_env_var")
            if user_env and os.getenv(user_env):
                env["VERIQON_USERNAME"] = os.getenv(user_env, "")
            else:
                env["VERIQON_USERNAME"] = ""

            if pass_env and os.getenv(pass_env):
                env["VERIQON_PASSWORD"] = os.getenv(pass_env, "")
            else:
                env["VERIQON_PASSWORD"] = ""

        # Ensure no legacy APEX environment variables leak into any test execution
        env.pop("APEX_USERNAME", None)
        env.pop("APEX_PASSWORD", None)
        env.pop("APEX_BASE_URL", None)

        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )

        with lock:
            if run_id in runs:
                runs[run_id]["pid"] = process.pid
                runs[run_id]["process"] = process

        output_lines = []
        if process.stdout is not None:
            for line in process.stdout:
                output_lines.append(line)
                with lock:
                    if run_id in runs:
                        runs[run_id]["logs"] += line

        exit_code = process.wait()

        # Write execution logs to disk
        log_content = "".join(output_lines)
        log_file_path.write_text(log_content, encoding="utf-8")

        # Copy JUnit XML to root reports/xml for backwards compatibility
        global_xml = XML_DIR / f"{run_id}.xml"
        if junit_path.is_file() and not global_xml.is_file():
            try:
                global_xml.write_bytes(junit_path.read_bytes())
            except Exception:
                pass

        summary = read_report(run_id, project_ext_id)
        json_report = get_json_report(run_id, project_ext_id)

        if summary is None and json_report:
            summary = {
                "total": json_report.get("total", 0),
                "passed": json_report.get("passed", 0),
                "failed": json_report.get("failed", 0),
                "skipped": json_report.get("skipped", 0),
                "errors": json_report.get("errors", 0),
            }

        final_status = "passed" if exit_code == 0 else ("failed" if exit_code == 1 else "error")

        # Database persistence
        db = SessionLocal()
        try:
            # 1. Save individual test results into test_run_results
            if json_report and "tests" in json_report:
                db_service.save_test_results(db, run_uuid, json_report["tests"])

            # 2. Register all generated artifacts in PostgreSQL
            # Screenshots
            if screenshots_dir.is_dir():
                for shot in sorted(screenshots_dir.iterdir()):
                    if shot.is_file() and shot.suffix.lower() == ".png":
                        db_service.register_artifact(
                            db, project_uuid, run_uuid, "screenshot", shot
                        )

            # Videos
            if videos_dir.is_dir():
                for vid in sorted(videos_dir.iterdir()):
                    if vid.is_file() and vid.suffix.lower() in (".webm", ".mp4"):
                        db_service.register_artifact(
                            db, project_uuid, run_uuid, "video", vid
                        )

            # Reports
            if junit_path.is_file():
                db_service.register_artifact(
                    db, project_uuid, run_uuid, "junit", junit_path
                )
            if json_report:
                json_file = reports_dir / "json" / f"run_{run_id}.json"
                if not json_file.is_file():
                    json_file = REPORT_DIR / f"run_{run_id}.json"
                if json_file.is_file():
                    db_service.register_artifact(
                        db, project_uuid, run_uuid, "report", json_file
                    )

            # Log artifact
            if log_file_path.is_file():
                db_service.register_artifact(
                    db, project_uuid, run_uuid, "log", log_file_path
                )

            # 3. Update test_runs table
            db_service.update_test_run(
                db,
                run_uuid,
                status=final_status,
                finished_at=datetime.now(timezone.utc),
                exit_code=exit_code,
                summary=summary,
                log_path=str(log_file_path.relative_to(ROOT)).replace("\\", "/"),
            )
        finally:
            db.close()

        with lock:
            if run_id in runs:
                record = runs[run_id]
                record["exit_code"] = exit_code
                record["junit_report"] = str(junit_path)
                record["summary"] = summary
                record["json_report"] = json_report
                record["status"] = final_status
                record["finished_at"] = time.time()

    except Exception as exc:
        db = SessionLocal()
        try:
            db_service.update_test_run(
                db,
                run_uuid,
                status="error",
                finished_at=datetime.now(timezone.utc),
                summary={"error": str(exc)},
            )
        except Exception:
            pass
        finally:
            db.close()

        with lock:
            if run_id in runs:
                record = runs[run_id]
                record["status"] = "error"
                record["logs"] += f"\nRunner error: {exc}\n"
                record["finished_at"] = time.time()

    finally:
        with lock:
            if active_run_id == run_id:
                active_run_id = None


# ---------------------------------------------------------
# General endpoints
# ---------------------------------------------------------

@app.get("/")
def root():
    return {"message": "Veriqon Automated Testing Platform API is running"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "application": "Veriqon Automated Testing Platform API",
    }


# ---------------------------------------------------------
# Test-case endpoints
# ---------------------------------------------------------

@app.get("/api/test-cases")
def test_cases(project_id: str | None = None):
    test_dir = "tests"
    if project_id:
        db = SessionLocal()
        try:
            project = db_service.resolve_project(db, project_id)
            test_dir = project.get("test_directory") or "tests"
        finally:
            db.close()

    return discover_tests(test_dir)


# ---------------------------------------------------------
# Test execution & run endpoints
# ---------------------------------------------------------

@app.get("/api/runs")
def list_runs(project_id: str | None = None):
    """List runs from PostgreSQL with in-memory status merge."""
    db = SessionLocal()
    try:
        if project_id:
            runs_list = db_service.get_project_runs(db, project_id)
        else:
            # Query all runs across active projects
            query = text("""
                SELECT tr.*, p.external_id as project_external_id, p.name as project_name
                FROM test_runs tr
                JOIN projects p ON p.id = tr.project_id
                ORDER BY tr.created_at DESC
                LIMIT 100
            """)
            rows = db.execute(query).mappings().all()
            runs_list = []
            for row in rows:
                item = dict(row)
                item["id"] = str(item["id"])
                item["project_id"] = item["project_external_id"]
                item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
                item["started_at"] = item["started_at"].isoformat() if item["started_at"] else None
                item["finished_at"] = item["finished_at"].isoformat() if item["finished_at"] else None
                runs_list.append(item)

        # Merge in-memory active runs
        with lock:
            for r in runs_list:
                mem = runs.get(r["id"])
                if mem and mem.get("status") in ("queued", "running"):
                    r["status"] = mem["status"]
                    if mem.get("summary"):
                        r["summary"] = mem["summary"]

        return runs_list
    finally:
        db.close()


@app.post("/api/runs")
def start_run(request: RunRequest):
    global active_run_id

    if request.test_file and request.test_ids:
        raise HTTPException(
            status_code=400,
            detail="Choose a test file or test IDs, not both.",
        )

    if not request.test_file and not request.test_ids:
        raise HTTPException(
            status_code=400,
            detail="Select at least one test file or test ID.",
        )

    # Validate project against PostgreSQL
    db = SessionLocal()
    try:
        project = db_service.resolve_project(db, request.project_id)
        discovered = discover_tests(project.get("test_directory", "tests"))
    finally:
        db.close()

    if request.test_file:
        allowed_files = {test.split("::", 1)[0] for test in discovered}
        requested_file = Path(request.test_file).as_posix()
        if requested_file not in allowed_files:
            raise HTTPException(
                status_code=400,
                detail="Unknown test file.",
            )

    if request.test_ids:
        invalid = set(request.test_ids) - set(discovered)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Unknown test IDs",
                    "tests": sorted(invalid),
                },
            )

    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)
    project_uuid = project["id"] if isinstance(project["id"], uuid.UUID) else uuid.UUID(str(project["id"]))

    with lock:
        if active_run_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Another test run is already in progress.",
            )

        runs[run_id] = {
            "id": run_id,
            "project_id": project["external_id"],
            "status": "queued",
            "created_at": time.time(),
            "logs": "",
            "exit_code": None,
            "summary": None,
            "json_report": None,
            "test_file": request.test_file,
            "test_ids": request.test_ids,
            "junit_report": str(ARTIFACTS_ROOT / project["external_id"] / run_id / "reports" / "xml" / f"{run_id}.xml"),
        }
        active_run_id = run_id

    # Persist queued run in PostgreSQL
    db = SessionLocal()
    try:
        db_service.create_test_run(
            db,
            run_uuid=run_uuid,
            project_uuid=project_uuid,
            environment=project.get("default_environment", "QA"),
            browser=project.get("browser", "chromium"),
            selected_tests=request.test_ids or ([request.test_file] if request.test_file else []),
        )
    finally:
        db.close()

    Thread(
        target=execute_run,
        args=(run_id, project, request.model_dump()),
        daemon=True,
    ).start()

    return {
        "run_id": run_id,
        "project_id": project["external_id"],
        "status": "queued",
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    db = SessionLocal()
    try:
        run_data = db_service.get_run_details(db, run_id)
        with lock:
            mem = runs.get(run_id)
            if mem and mem.get("status") in ("queued", "running") and run_data.get("status") in ("queued", "running", "pending"):
                run_data["status"] = mem["status"]
            if mem and mem.get("logs"):
                run_data["logs"] = mem["logs"]
        return run_data
    except HTTPException:
        # Fallback to in-memory if DB record is not yet committed
        with lock:
            mem = runs.get(run_id)
            if mem:
                return {k: v for k, v in mem.items() if k not in ("pid", "command")}
        raise
    finally:
        db.close()


@app.get("/api/runs/{run_id}/logs")
def get_logs(run_id: str):
    with lock:
        mem = runs.get(run_id)
        if mem and mem.get("logs"):
            return {"logs": mem["logs"]}

    # Fallback to DB log path
    db = SessionLocal()
    try:
        run_data = db_service.get_run_details(db, run_id)
        log_path = run_data.get("log_path")
        if log_path:
            full_log = (ROOT / log_path).resolve()
            if full_log.is_file() and full_log.is_relative_to(ROOT.resolve()):
                return {"logs": full_log.read_text(encoding="utf-8")}
        return {"logs": ""}
    finally:
        db.close()


@app.post("/api/runs/{run_id}/stop")
@app.post("/api/runs/stop")
def stop_run(run_id: str | None = None):
    """
    Terminates an ongoing test run or dynamic browser scenario execution immediately.
    """
    global active_run_id
    target_id = run_id or active_run_id
    if not target_id:
        return {"status": "ok", "message": "No active test run to terminate."}

    # 1. Stop dynamic Playwright session if present
    try:
        from app import scenario_engine
        scenario_engine.cancel_scenario_run(target_id)
    except Exception:
        pass

    # 2. Terminate subprocess if pytest run
    with lock:
        mem = runs.get(target_id)
        if mem:
            proc = mem.get("process")
            if proc:
                try:
                    proc.terminate()
                    proc.kill()
                except Exception:
                    pass
            pid = mem.get("pid")
            if pid:
                try:
                    import psutil
                    p = psutil.Process(pid)
                    for child in p.children(recursive=True):
                        child.kill()
                    p.kill()
                except Exception:
                    pass
            mem["status"] = "cancelled"
            mem["logs"] += "\n[STOPPED] Execution terminated by user request.\n"

        if active_run_id == target_id:
            active_run_id = None

    # 3. Update database record
    db = SessionLocal()
    try:
        r_uuid = uuid.UUID(target_id)
        db_service.update_test_run(
            db,
            r_uuid,
            status="cancelled",
            finished_at=datetime.now(timezone.utc),
            exit_code=130,
            summary={"error": "Run terminated by user"},
        )
    except Exception:
        pass
    finally:
        db.close()

    return {"status": "cancelled", "run_id": target_id, "message": "Run terminated successfully."}


# ---------------------------------------------------------
# Project-scoped runs & artifacts endpoints
# ---------------------------------------------------------

@app.get("/api/projects/{project_id}/runs")
def project_runs(project_id: str):
    db = SessionLocal()
    try:
        return db_service.get_project_runs(db, project_id)
    finally:
        db.close()


@app.get("/api/projects/{project_id}/runs/{run_id}")
def project_run_details(project_id: str, run_id: str):
    db = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        run_data = db_service.get_run_details(db, run_id)
        if run_data["project_id"] != project["external_id"]:
            raise HTTPException(status_code=404, detail="Run does not belong to this project.")
        return run_data
    finally:
        db.close()


@app.get("/api/projects/{project_id}/artifacts")
def project_artifacts(
    project_id: str,
    run_id: str | None = None,
    artifact_type: str | None = Query(None, alias="type"),
):
    """Retrieve artifacts associated with a project."""
    db = SessionLocal()
    try:
        return db_service.get_artifacts(
            db,
            project_identifier=project_id,
            run_id_str=run_id,
            artifact_type=artifact_type,
        )
    finally:
        db.close()


@app.get("/api/projects/{project_id}/runs/{run_id}/artifacts")
def project_run_artifacts(project_id: str, run_id: str):
    db = SessionLocal()
    try:
        return db_service.get_artifacts(
            db,
            project_identifier=project_id,
            run_id_str=run_id,
        )
    finally:
        db.close()


@app.get("/api/runs/{run_id}/artifacts")
def run_artifacts(run_id: str):
    """List all artifacts for a run."""
    db = SessionLocal()
    try:
        return db_service.get_artifacts(db, run_id_str=run_id)
    finally:
        db.close()


# ---------------------------------------------------------
# Artifact content serving (Safe path resolution & inline playback)
# ---------------------------------------------------------

@app.get("/api/artifacts/{artifact_id}/content")
def get_artifact_content(artifact_id: int, download: bool = False):
    """
    Serve artifact file inline (for browser viewing and video playback)
    or as attachment when download=true.
    Strictly prevents path traversal and verifies file existence.
    """
    db = SessionLocal()
    try:
        art = db_service.get_artifact_by_id(db, artifact_id)
        rel_path = art["relative_path"]
        file_path = (ROOT / rel_path).resolve()

        # Strict security check: path must resolve inside project ROOT
        if not file_path.is_relative_to(ROOT.resolve()):
            raise HTTPException(status_code=400, detail="Invalid artifact path.")

        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Artifact file not found on disk.")

        disposition = "attachment" if download else "inline"
        media_type = art.get("content_type") or "application/octet-stream"

        return FileResponse(
            path=file_path,
            media_type=media_type,
            content_disposition_type=disposition,
            filename=art["filename"],
        )
    finally:
        db.close()
