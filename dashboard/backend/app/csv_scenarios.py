
import csv
import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

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

# Only map scenarios to existing, reviewed pytest tests.
SCENARIO_TEST_MAP = {
    "TC-001": "tests/test_login.py::test_login_page_loads[chromium]",
    "TC-002": "tests/test_login.py::test_login_with_valid_credentials[chromium]",
    "TC-003": "tests/test_login.py::test_navigate_to_my_timesheet[chromium]",
    "TC-007": "tests/test_projects.py::test_adding_one_project_adds_one_row[chromium]",
    "TC-008": "tests/test_validation.py::test_over_max_hours_cleared[chromium]",
}


@router.post("/validate")
async def validate_csv(file: UploadFile = File(...)):
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
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="CSV must use UTF-8 encoding.",
        ) from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))

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

            mapped = tc_id in SCENARIO_TEST_MAP
            row_valid = len(row_errors) == 0

            # Extra response fields help the UI distinguish
            # CSV validity from whether a test can be executed.
            row["valid"] = row_valid
            row["validation_errors"] = row_errors
            row["mapped"] = mapped
            row["runnable"] = row_valid and mapped

            scenarios.append(row)

        total_rows = len(scenarios)
        valid_rows = sum(
            1 for scenario in scenarios if scenario["valid"]
        )
        runnable_rows = sum(
            1 for scenario in scenarios if scenario["runnable"]
        )

        return {
            "valid": total_rows > 0 and len(errors) == 0,
            "filename": file.filename,
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "runnable_rows": runnable_rows,
            "errors": errors,
            "columns": REQUIRED_COLUMNS,
            "scenarios": scenarios,
        }

    except csv.Error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to parse CSV: {exc}",
        ) from exc


@router.post("/execute")
async def execute_csv_scenarios(
    file: UploadFile = File(...),
    selected_tc_ids: list[str] = Form(...),
):
    """Run selected scenarios that have valid rows and approved mappings."""

    validation = await validate_csv(file)

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

    # Keep the user's selected order.
    pytest_ids = [
        SCENARIO_TEST_MAP[tc_id]
        for tc_id in normalized_ids
    ]

    # Reuse the existing dashboard test-run lifecycle.
    from app.main import RunRequest, start_run

    result = start_run(RunRequest(test_ids=pytest_ids))

    return {
        **result,
        "selected_tc_ids": normalized_ids,
        "pytest_test_ids": pytest_ids,
    }
