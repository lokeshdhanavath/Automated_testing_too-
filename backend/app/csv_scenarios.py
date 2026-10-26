import csv
import io
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.database import SessionLocal
from app import db_service

router = APIRouter(prefix="/api/csv-scenarios", tags=["CSV Scenarios"])

REQUIRED_COLUMNS = [
    "TC_ID",
    "Scenario",
    "Preconditions",
    "Steps",
    "Expected_Result",
    "Priority",
]

ALLOWED_PRIORITIES = {"HIGH", "MEDIUM", "LOW"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

# Static fallback map for default APEX scenarios
SCENARIO_TEST_MAP = {
    "TC-001": "tests/test_login.py::test_login_page_loads[chromium]",
    "TC-002": "tests/test_login.py::test_login_with_valid_credentials[chromium]",
    "TC-003": "tests/test_login.py::test_navigate_to_my_timesheet[chromium]",
    "TC-007": "tests/test_projects.py::test_adding_one_project_adds_one_row[chromium]",
    "TC-008": "tests/test_validation.py::test_over_max_hours_cleared[chromium]",
}


def _get_project_mapping(project_id: str | None = None) -> dict[str, str]:
    db = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        db_mappings = db_service.get_scenario_mappings(db, project["id"])
        # Merge with fallback
        return {**SCENARIO_TEST_MAP, **db_mappings}
    finally:
        db.close()


@router.post("/validate")
async def validate_csv(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
):
    """Validate CSV structure, rows, and approved test mappings."""

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a .csv file.",
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="CSV file exceeds the 2 MB limit.",
        )

    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="CSV must use UTF-8 encoding.",
        ) from exc

    try:
        reader = csv.DictReader(io.StringIO(text_content, newline=""))

        if not reader.fieldnames:
            raise HTTPException(
                status_code=400,
                detail="CSV is empty or missing its header row.",
            )

        headers = [header.strip() for header in reader.fieldnames]

        if len(headers) != len(set(headers)):
            raise HTTPException(
                status_code=400,
                detail="CSV contains duplicate column names.",
            )

        missing = [
            column for column in REQUIRED_COLUMNS
            if column not in headers
        ]

        if missing:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Required CSV columns are missing.",
                    "missing_columns": missing,
                    "required_columns": REQUIRED_COLUMNS,
                },
            )

        scenario_map = _get_project_mapping(project_id)

        scenarios = []
        errors = []
        seen_ids = set()

        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                errors.append({
                    "row": row_number,
                    "message": "Row contains more values than the header.",
                })
                continue

            row = {
                key.strip(): (value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }

            # Ignore completely blank rows.
            if not any(row.values()):
                continue

            tc_id = row.get("TC_ID", "")
            priority = row.get("Priority", "").upper()
            row_errors = []

            for column in REQUIRED_COLUMNS:
                if not row.get(column):
                    row_errors.append(f"{column} is required")

            if tc_id in seen_ids and tc_id:
                row_errors.append(f"Duplicate TC_ID: {tc_id}")

            if tc_id:
                seen_ids.add(tc_id)

            if priority and priority not in ALLOWED_PRIORITIES:
                row_errors.append(
                    "Priority must be High, Medium, or Low"
                )

            if row_errors:
                errors.append({
                    "row": row_number,
                    "tc_id": tc_id,
                    "messages": row_errors,
                })

            mapped = tc_id in scenario_map
            row_valid = len(row_errors) == 0

            # Extra response fields help the UI distinguish
            # between invalid structure and missing test mappings.
            scenarios.append({
                **row,
                "valid": row_valid,
                "mapped": mapped,
                "pytest_id": scenario_map.get(tc_id),
            })

        valid_rows = sum(1 for item in scenarios if item["valid"])

        return {
            "valid": len(errors) == 0 and len(scenarios) > 0,
            "filename": file.filename,
            "total_rows": len(scenarios),
            "valid_rows": valid_rows,
            "errors": errors,
            "columns": headers,
            "scenarios": scenarios,
        }

    except csv.Error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"CSV parsing error: {exc}",
        ) from exc


@router.post("/execute")
async def execute_csv_scenarios(
    file: UploadFile = File(...),
    selected_tc_ids: list[str] = Form(...),
    project_id: str | None = Form(None),
):
    """Run selected scenarios that have valid rows and approved mappings."""

    validation = await validate_csv(file, project_id=project_id)

    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV validation failed. Fix the CSV errors first.",
                "errors": validation["errors"],
            },
        )

    normalized_ids = [
        tc_id.strip()
        for value in selected_tc_ids
        for tc_id in value.split(",")
        if tc_id.strip()
    ]

    if not normalized_ids:
        raise HTTPException(
            status_code=400,
            detail="Select at least one test scenario.",
        )

    if len(normalized_ids) != len(set(normalized_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate scenario IDs were selected.",
        )

    scenario_by_id = {
        scenario["TC_ID"]: scenario
        for scenario in validation["scenarios"]
    }

    missing_from_csv = [
        tc_id for tc_id in normalized_ids
        if tc_id not in scenario_by_id
    ]

    if missing_from_csv:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Selected scenario IDs are not present in the CSV.",
                "ids": missing_from_csv,
            },
        )

    invalid_ids = [
        tc_id for tc_id in normalized_ids
        if not scenario_by_id[tc_id]["valid"]
    ]

    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Some selected CSV rows are invalid.",
                "ids": invalid_ids,
            },
        )

    unmapped_ids = [
        tc_id for tc_id in normalized_ids
        if not scenario_by_id[tc_id]["mapped"]
    ]

    if unmapped_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Some scenarios do not have approved test mappings yet."
                ),
                "ids": unmapped_ids,
            },
        )

    scenario_map = _get_project_mapping(project_id)

    # Keep the user's selected order.
    pytest_ids = [
        scenario_map[tc_id]
        for tc_id in normalized_ids
    ]

    # Reuse the existing dashboard test-run lifecycle with project context.
    from app.main import RunRequest, start_run

    result = start_run(RunRequest(project_id=project_id, test_ids=pytest_ids))

    return {
        **result,
        "selected_tc_ids": normalized_ids,
        "pytest_test_ids": pytest_ids,
    }

# Element registry CSV parser

from typing import Any
from sqlalchemy.orm import Session
from app.models.elements import Element

ACTION_MAP = {"open_app":"open_app","open":"open_app","navigate":"navigate","login":"login","click":"click_element","click_element":"click_element","fill":"fill_input","fill_input":"fill_input","type":"fill_input","select":"select_option","select_option":"select_option","verify_visible":"verify_element","verify_contains":"verify_element","verify_exact":"verify_element","wait_for_element":"wait_for_element","wait":"wait_for_element","wait_timeout":"wait_for_element","press_key":"press_key","check":"check","uncheck":"uncheck","hover":"hover","clear":"clear"}
ELEMENT_REQUIRED = {"click_element","fill_input","select_option","verify_element","wait_for_element","press_key","check","uncheck","hover","clear"}
URL_ACTIONS = {"open_app","navigate"}

def parse_csv_to_steps(csv_text: str, project_id: str, db: Session) -> list[dict]:
    """Parse workflow CSV actions and resolve named elements from the project registry."""
    reader=csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames: raise ValueError("CSV is empty or missing its header row.")
    reader.fieldnames=[h.strip().lower() for h in reader.fieldnames]
    project=db_service.resolve_project(db,project_id)
    elements={e.name:e for e in db.query(Element).filter_by(project_id=uuid.UUID(str(project["id"]))).all()}
    steps=[]
    for idx,row in enumerate(reader,start=1):
        raw=(row.get("action") or "").strip().lower()
        if not raw: continue
        if raw not in ACTION_MAP: raise ValueError(f"Row {idx}: unknown action '{raw}'")
        action=ACTION_MAP[raw]; name=(row.get("element") or "").strip(); url=(row.get("url") or "").strip(); value=row.get("value") or ""
        try: wait_ms=int(row.get("wait_ms") or 0)
        except ValueError as exc: raise ValueError(f"Row {idx}: wait_ms must be an integer.") from exc
        on_fail=(row.get("on_fail") or "stop").strip().lower()
        if on_fail not in {"stop","continue"} and not on_fail.startswith("retry:"): raise ValueError(f"Row {idx}: invalid on_fail policy.")
        params: dict[str,Any]={"value":value,"wait_after_ms":wait_ms,"element_name":name}
        if raw=="verify_visible": params["verify_type"]="visible"
        elif raw=="verify_contains": params.update({"verify_type":"contains_text","expected":value})
        elif raw=="verify_exact": params.update({"verify_type":"exact_text","expected":value})
        if action in URL_ACTIONS: lt,lv=None,url;params["url"]=url
        elif action in ELEMENT_REQUIRED:
            if not name: raise ValueError(f"Row {idx}: action '{raw}' requires an element name.")
            el=elements.get(name)
            if not el: raise ValueError(f"Row {idx}: element '{name}' is not registered for this project.")
            lt,lv=el.selector_type,el.selector_value
            params.update({"element_kind":el.element_kind,"fallback_type":el.fallback_type,"fallback_value":el.fallback_value})
        else: lt,lv=None,""
        steps.append({"step_order":idx,"action_type":action,"locator_type":lt,"locator_value":lv,"action_params":params,"on_fail":on_fail,"is_enabled":True,"timeout_ms":None,"description":f"Step {idx}: {raw} '{name or url}'"})
    if not steps: raise ValueError("CSV contains no executable action rows.")
    return steps


@router.post("/workflow/parse")
async def parse_registry_workflow_csv(file: UploadFile = File(...), project_id: str = Form(...)) -> dict:
    """Validate a workflow CSV and resolve its named elements for execution."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="CSV file exceeds the 2 MB limit.")
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must use UTF-8 encoding.") from exc
    db = SessionLocal()
    try:
        steps = parse_csv_to_steps(text_content, project_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        db.close()
    return {"filename": file.filename, "project_id": project_id, "steps": steps}
