
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


# Explicit mappings to existing Playwright/pytest test IDs.
# Add more mappings only after confirming the corresponding test exists.
SCENARIO_TEST_MAP = {
    "TC-001": "tests/test_login.py::test_login_page_loads[chromium]",
    "TC-002": "tests/test_login.py::test_login_with_valid_credentials[chromium]",
    "TC-003": "tests/test_login.py::test_navigate_to_my_timesheet[chromium]",
}


@router.post("/validate")
async def validate_csv(file: UploadFile = File(...)):
    """Validate a CSV scenario file without executing tests."""

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
            column
            for column in REQUIRED_COLUMNS
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

        rows = []
        seen_ids = set()
        errors = []

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

            row_errors = []
            tc_id = row.get("TC_ID", "")
            priority = row.get("Priority", "").upper()

            for column in REQUIRED_COLUMNS:
                if not row.get(column):
                    row_errors.append(f"{column} is required")

            if tc_id and tc_id in seen_ids:
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

            rows.append(row)

        invalid_row_count = sum(
            1
            for error in errors
            if "tc_id" in error
        )
        extra_value_errors = sum(
            1
            for error in errors
            if "message" in error
        )

        valid_rows = max(
            0,
            len(rows) - invalid_row_count - extra_value_errors,
        )

        return {
            "valid": len(errors) == 0 and len(rows) > 0,
            "filename": file.filename,
            "total_rows": len(rows) + extra_value_errors,
            "valid_rows": valid_rows,
            "errors": errors,
            "columns": REQUIRED_COLUMNS,
            "scenarios": rows,
        }

    except csv.Error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to parse CSV: {exc}",
        ) from exc


@router.post("/execute")

@router.post("/execute")
async def execute_csv_scenarios(
    file: UploadFile = File(...),
    selected_tc_ids: list[str] = Form(...),
):
    """Execute selected CSV scenarios mapped to approved pytest tests."""

    # Validate the uploaded CSV first.
    validation = await validate_csv(file)

    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV validation failed.",
                "errors": validation["errors"],
            },
        )

    # Normalize repeated values and comma-separated values.
    # Examples:
    # ["TC-001", "TC-003"]       -> ["TC-001", "TC-003"]
    # ["TC-001,TC-003"]          -> ["TC-001", "TC-003"]
    # ["TC-001, TC-003", "TC-002"] -> ["TC-001", "TC-003", "TC-002"]
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

    # Reject duplicates after normalization.
    if len(normalized_ids) != len(set(normalized_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate scenario IDs were selected.",
        )

    csv_ids = {
        scenario["TC_ID"]
        for scenario in validation["scenarios"]
    }

    missing_from_csv = set(normalized_ids) - csv_ids

    if missing_from_csv:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Selected scenario IDs are not present in the CSV.",
                "ids": sorted(missing_from_csv),
            },
        )

    unmapped_ids = set(normalized_ids) - set(SCENARIO_TEST_MAP)

    if unmapped_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Some scenarios do not have approved test mappings yet."
                ),
                "ids": sorted(unmapped_ids),
            },
        )

    # Preserve the user's selection order.
    pytest_ids = [
        SCENARIO_TEST_MAP[tc_id]
        for tc_id in normalized_ids
    ]

    # Reuse the existing run lifecycle.
    from app.main import RunRequest, start_run

    result = start_run(
        RunRequest(test_ids=pytest_ids)
    )

    return {
        **result,
        "selected_tc_ids": normalized_ids,
        "pytest_test_ids": pytest_ids,
    }

