
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.scripts_api import router as scripts_router


# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parents[3]
TESTS_DIR = ROOT / "tests"
REPORT_DIR = ROOT / "reports" / "json"
XML_DIR = ROOT / "reports" / "xml"
VIDEO_DIR = ROOT / "videos"
SCREENSHOT_DIR = ROOT / "screenshots"

for folder in (REPORT_DIR, XML_DIR, VIDEO_DIR, SCREENSHOT_DIR):
    folder.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(title="APEX Automated Testing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scripts_router)

lock = Lock()
runs = {}
active_run_id = None


# ---------------------------------------------------------
# Request models
# ---------------------------------------------------------

class RunRequest(BaseModel):
    test_file: str | None = None
    test_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------
# Pytest test discovery
# ---------------------------------------------------------

def discover_tests():
    """Discover real pytest node IDs without executing tests."""
    command = [
        sys.executable,
        "-m",
        "pytest",
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
                "output": (
                    result.stdout + "\n" + result.stderr
                )[-8000:],
            },
        )

    tests = []

    for line in result.stdout.splitlines():
        line = line.strip()

        # Only accept pytest node IDs from the tests directory.
        if not line.startswith("tests/") or "::" not in line:
            continue

        test_path = line.split("::", 1)[0]

        if not test_path.endswith(".py"):
            continue

        tests.append(line)

    return list(dict.fromkeys(tests))


# ---------------------------------------------------------
# Report parsing
# ---------------------------------------------------------

def read_report(run_id):
    """Read this dashboard run's JUnit XML and return a summary."""
    xml_path = XML_DIR / f"{run_id}.xml"

    if not xml_path.is_file():
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


def get_json_report(run_id):
    """Return a timestamp-based project JSON report if available."""
    path = REPORT_DIR / f"run_{run_id}.json"

    if not path.is_file():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------
# Test execution worker
# ---------------------------------------------------------

def execute_run(run_id, request_data):
    global active_run_id

    started = time.time()
    junit_path = XML_DIR / f"{run_id}.xml"

    command = [
        sys.executable,
        str(ROOT / "run_all.py"),
    ]

    if request_data["test_ids"]:
        command.extend(request_data["test_ids"])
    elif request_data["test_file"]:
        command.append(request_data["test_file"])

    command.extend(["--junitxml", str(junit_path)])

    with lock:
        run_record = runs[run_id]
        run_record["status"] = "running"
        run_record["started_at"] = started
        run_record["command"] = command

    try:
        env = os.environ.copy()

        # Allow the existing reporting code to associate its JSON report
        # with this dashboard run, if it supports this environment variable.
        env["DASHBOARD_RUN_ID"] = run_id

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
            runs[run_id]["pid"] = process.pid

        if process.stdout is not None:
            for line in process.stdout:
                with lock:
                    runs[run_id]["logs"] += line

        exit_code = process.wait()

        # Parse the JUnit XML generated for this exact dashboard run.
        summary = read_report(run_id)

        if summary is None:
            with lock:
                runs[run_id]["logs"] += (
                    "\n[Warning] JUnit XML summary is not available yet.\n"
                )

        json_report = get_json_report(run_id)

        with lock:
            record = runs[run_id]
            record["exit_code"] = exit_code
            record["junit_report"] = str(junit_path)
            record["summary"] = summary
            record["json_report"] = json_report

            if exit_code == 0:
                record["status"] = "passed"
            elif exit_code == 1:
                record["status"] = "failed"
            else:
                record["status"] = "error"

            record["finished_at"] = time.time()

    except Exception as exc:
        with lock:
            record = runs[run_id]
            record["status"] = "error"
            record["logs"] += f"\nRunner error: {exc}\n"
            record["finished_at"] = time.time()

    finally:
        with lock:
            if active_run_id == run_id:
                active_run_id = None


# ---------------------------------------------------------
# API endpoints
# ---------------------------------------------------------

@app.get("/")
def root():
    return {"message": "APEX Automated Testing API is running"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "application": "APEX Automated Testing API",
    }


@app.get("/api/test-cases")
def test_cases():
    return discover_tests()


@app.get("/api/runs")
def list_runs():
    with lock:
        return [
            {
                key: value
                for key, value in run.items()
                if key not in ("pid", "command")
            }
            for run in reversed(list(runs.values()))
        ]


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

    discovered = discover_tests()

    if request.test_file:
        allowed_files = {
            test.split("::", 1)[0]
            for test in discovered
        }

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

    with lock:
        if active_run_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Another test run is already in progress.",
            )

        run_id = str(uuid4())

        runs[run_id] = {
            "id": run_id,
            "status": "queued",
            "created_at": time.time(),
            "logs": "",
            "exit_code": None,
            "summary": None,
            "json_report": None,
            "test_file": request.test_file,
            "test_ids": request.test_ids,
            "junit_report": str(XML_DIR / f"{run_id}.xml"),
        }

        active_run_id = run_id

    Thread(
        target=execute_run,
        args=(run_id, request.model_dump()),
        daemon=True,
    ).start()

    return {
        "run_id": run_id,
        "status": "queued",
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    with lock:
        run = runs.get(run_id)

        if run is None:
            raise HTTPException(
                status_code=404,
                detail="Run not found.",
            )

        return {
            key: value
            for key, value in run.items()
            if key not in ("pid", "command")
        }


@app.get("/api/runs/{run_id}/logs")
def get_logs(run_id: str):
    with lock:
        run = runs.get(run_id)

        if run is None:
            raise HTTPException(
                status_code=404,
                detail="Run not found.",
            )

        return {"logs": run["logs"]}


@app.get("/api/runs/{run_id}/artifacts")
def artifacts(run_id: str):
    with lock:
        run = runs.get(run_id)

        if run is None:
            raise HTTPException(
                status_code=404,
                detail="Run not found.",
            )

        run_status = run["status"]

    files = []

    # Videos and screenshots are currently listed from their output
    # directories. They are not guaranteed to be uniquely attributable
    # to this run until the recording naming convention is updated.
    for folder, artifact_type in (
        (VIDEO_DIR, "video"),
        (SCREENSHOT_DIR, "screenshot"),
    ):
        if folder.is_dir():
            for path in folder.iterdir():
                if path.is_file():
                    files.append({
                        "name": path.name,
                        "path": str(path),
                        "type": artifact_type,
                    })

    junit_path = XML_DIR / f"{run_id}.xml"

    if junit_path.is_file():
        files.append({
            "name": junit_path.name,
            "path": str(junit_path),
            "type": "junit",
        })

    summary = read_report(run_id)

    return {
        "run_id": run_id,
        "status": run_status,
        "report": summary,
        "files": files,
    }
