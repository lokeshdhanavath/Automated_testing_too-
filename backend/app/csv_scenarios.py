import csv
import difflib
import io
import re
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import db_service
from app.database import SessionLocal
from app.models.elements import AppElement, Element

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
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

SCENARIO_TEST_MAP = {
    "TC-001": "tests/test_login.py::test_login_page_loads[chromium]",
    "TC-002": "tests/test_login.py::test_login_with_valid_credentials[chromium]",
    "TC-003": "tests/test_login.py::test_navigate_to_my_timesheet[chromium]",
    "TC-007": "tests/test_projects.py::test_adding_one_project_adds_one_row[chromium]",
    "TC-008": "tests/test_validation.py::test_over_max_hours_cleared[chromium]",
}

ACTION_MAP = {
    "open_app": "open_app",
    "open": "open_app",
    "open_url": "open_app",
    "navigate": "navigate",
    "goto": "navigate",
    "url": "open_app",
    "login": "login",
    "sign_in": "login",
    "signin": "login",
    "auth": "login",
    "click": "click_element",
    "click_element": "click_element",
    "press": "click_element",
    "tap": "click_element",
    "fill": "fill_input",
    "fill_input": "fill_input",
    "type": "fill_input",
    "input": "fill_input",
    "enter": "fill_input",
    "select": "select_option",
    "select_option": "select_option",
    "choose": "select_option",
    "search_and_select": "select_option",
    "search_select": "select_option",
    "combobox": "select_option",
    "verify": "verify_element",
    "verify_visible": "verify_element",
    "verify_contains": "verify_element",
    "verify_exact": "verify_element",
    "verify_element": "verify_element",
    "assert": "verify_element",
    "assert_visible": "verify_element",
    "wait": "wait",
    "pause": "wait",
    "sleep": "wait",
    "delay": "wait",
    "wait_timeout": "wait",
    "wait_for_timeout": "wait",
    "wait_for_element": "wait_for_element",
    "press_key": "press_key",
    "key": "press_key",
    "check": "check",
    "uncheck": "uncheck",
    "hover": "hover",
    "clear": "clear",
}

ELEMENT_REQUIRED_ACTIONS = {
    "click_element",
    "fill_input",
    "select_option",
    "verify_element",
    "wait_for_element",
    "press_key",
    "check",
    "uncheck",
    "hover",
    "clear",
}


def _get_project_mapping(project_id: str | None = None) -> dict[str, str]:
    db = SessionLocal()
    try:
        project = db_service.resolve_project(db, project_id)
        db_mappings = db_service.get_scenario_mappings(db, project["id"])
        return {**SCENARIO_TEST_MAP, **db_mappings}
    finally:
        db.close()


def find_matching_header(fieldnames: list[str], candidate_keys: list[str]) -> str | None:
    """Find a column in fieldnames that matches any candidate alias (case/space/symbol insensitive)."""
    if not fieldnames:
        return None
    norm_map = {re.sub(r"[^a-z0-9]", "", f.lower()): f for f in fieldnames}
    for cand in candidate_keys:
        cand_norm = re.sub(r"[^a-z0-9]", "", cand.lower())
        if cand_norm in norm_map:
            return norm_map[cand_norm]
    # Substring search
    for cand in candidate_keys:
        cand_norm = re.sub(r"[^a-z0-9]", "", cand.lower())
        for norm_f, original_f in norm_map.items():
            if cand_norm in norm_f:
                return original_f
    return None


def compact_text(text: str) -> str:
    """Strip all non-alphanumeric chars for resilient fuzzy/compound matching."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def find_nearby_catalog_element(
    target: str,
    catalog_items: list[dict[str, Any]],
    action_type: str = "",
) -> tuple[dict[str, Any] | None, float, str]:
    """
    Fuzzy & nearby element matcher.
    Resolves spelling variations, typos, synonyms, or abbreviations in target strings
    against the project's element catalog.
    Returns (best_item, confidence_score, match_reason).
    """
    if not target or not catalog_items:
        return None, 0.0, "No target or empty catalog"

    raw_target = target.strip()
    clean_target = re.sub(r"[\+\-\_\.\#\:\,\(\)\"\'\[\]]", " ", raw_target.lower()).strip()
    target_words = set(
        w for w in clean_target.split()
        if w not in ("field", "btn", "button", "input", "link", "element", "txt", "box", "selector")
    )
    comp_target = compact_text(clean_target).replace("username", "user").replace("signin", "login")

    best_item: dict[str, Any] | None = None
    best_score: float = 0.0
    best_reason: str = ""

    for item in catalog_items:
        candidates = [
            (item.get("friendly_name") or "", "friendly_name"),
            (item.get("label") or "", "label"),
            (item.get("placeholder") or "", "placeholder"),
            (item.get("locator_value") or "", "locator_value"),
        ]

        item_cat = (item.get("category") or "").lower()
        item_role = (item.get("role") or "").lower()

        # Action category compatibility bonus
        cat_bonus = 0.0
        if action_type in ("fill_input", "clear") and (item_cat == "input" or item_role == "textbox"):
            cat_bonus = 0.05
        elif action_type == "click_element" and (item_cat in ("button", "link") or item_role in ("button", "link")):
            cat_bonus = 0.05
        elif action_type == "select_option" and item_cat == "select":
            cat_bonus = 0.05

        for cand_text, attr_name in candidates:
            if not cand_text:
                continue
            clean_cand = re.sub(r"[\+\-\_\.\#\:\,\(\)\"\'\[\]]", " ", cand_text.lower()).strip()
            cand_words = set(
                w for w in clean_cand.split()
                if w not in ("field", "btn", "button", "input", "link", "element", "txt", "box", "selector")
            )
            comp_cand = compact_text(clean_cand).replace("username", "user").replace("signin", "login")

            score = 0.0
            reason = ""

            # 1. Exact raw match
            if raw_target.lower() == cand_text.strip().lower():
                score = 1.0
                reason = f"Exact match on {attr_name}"
            # 2. Normalized compound match (e.g. 'add_project' vs '+ Add Project')
            elif comp_target and comp_target == comp_cand:
                score = 0.98 + cat_bonus
                reason = f"Normalized match on {attr_name}"
            # 3. Compact substring match (e.g. 'add proj' in 'addproject')
            elif comp_target and (comp_target in comp_cand or comp_cand in comp_target):
                len_ratio = len(min(comp_target, comp_cand, key=len)) / max(len(max(comp_target, comp_cand, key=len)), 1)
                score = 0.88 + (0.07 * len_ratio) + cat_bonus
                reason = f"Nearby substring match on {attr_name}"
            # 4. Word subset containment (e.g. 'mon hours' in 'monday hours')
            elif target_words and target_words.issubset(cand_words):
                score = 0.92 + cat_bonus
                reason = f"Keyword match in {attr_name}"
            elif cand_words and cand_words.issubset(target_words):
                score = 0.90 + cat_bonus
                reason = f"Keyword containment in {attr_name}"
            # 5. Word overlap (Jaccard)
            elif target_words and (target_words & cand_words):
                overlap = len(target_words & cand_words) / len(target_words | cand_words)
                score = 0.70 + (0.22 * overlap) + cat_bonus
                reason = f"Word overlap ({int(overlap * 100)}%) on {attr_name}"
            # 6. SequenceMatcher fuzzy similarity (handles typos e.g. 'passwrod' vs 'password')
            else:
                ratio = difflib.SequenceMatcher(None, comp_target, comp_cand).ratio()
                if ratio > 0.60:
                    score = (ratio * 0.88) + cat_bonus
                    reason = f"Fuzzy similarity ({int(ratio * 100)}%) on {attr_name}"

            if score > best_score:
                best_score = score
                best_item = item
                best_reason = reason

    return best_item, min(best_score, 1.0), best_reason


def load_project_catalog_elements(db: Session, project_uuid: uuid.UUID) -> list[dict[str, Any]]:
    """Retrieve all catalog elements for a project across AppElement and Element tables."""
    catalog: list[dict[str, Any]] = []

    # 1. Primary Discovered Element Catalog (AppElement)
    try:
        app_els = db.query(AppElement).filter_by(project_id=project_uuid).all()
        for el in app_els:
            catalog.append({
                "id": str(el.id),
                "friendly_name": el.friendly_name or "",
                "label": el.label or "",
                "placeholder": el.placeholder or "",
                "category": el.category or "custom",
                "role": el.role or "",
                "tag_name": el.tag_name or "",
                "locator_strategy": el.locator_strategy or "smart",
                "locator_value": el.locator_value or "",
                "page_url": el.page_url or "",
                "fallback_type": None,
                "fallback_value": None,
            })
    except Exception:
        db.rollback()

    # 2. Legacy / Custom Elements (Element table if present)
    try:
        legacy_els = db.query(Element).filter_by(project_id=project_uuid).all()
        for el in legacy_els:
            catalog.append({
                "id": str(el.id),
                "friendly_name": el.name or "",
                "label": el.name or "",
                "placeholder": "",
                "category": el.element_kind or "custom",
                "role": el.element_kind or "",
                "tag_name": "",
                "locator_strategy": el.selector_type or "smart",
                "locator_value": el.selector_value or "",
                "page_url": el.page_url or "",
                "fallback_type": el.fallback_type,
                "fallback_value": el.fallback_value,
            })
    except Exception:
        db.rollback()

    return catalog


def extract_wait_seconds(raw_text: str | None) -> float | None:
    """Extract wait duration in seconds from flexible formats (e.g. 5, '5s', '3000ms', '2.5 sec')."""
    if not raw_text:
        return None
    s = str(raw_text).strip().lower()
    ms_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", s)
    if ms_match:
        return float(ms_match.group(1)) / 1000.0
    sec_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)?", s)
    if sec_match:
        val = float(sec_match.group(1))
        if val >= 100 and "s" not in s:
            return val / 1000.0
        return val
    return None


def parse_csv_to_steps(csv_text: str, project_id: str, db: Session) -> list[dict[str, Any]]:
    """
    Parse action-based CSV workflows with flexible column headers and
    intelligent nearby / fuzzy catalog element matching.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV is empty or missing its header row.")

    raw_headers = list(reader.fieldnames)
    headers = [h.strip() for h in raw_headers]

    # Flexible column detection
    col_action = find_matching_header(
        headers,
        ["action", "which_action", "which action", "action_type", "action type", "operation", "command", "step_action", "type", "step_type"],
    )
    col_target = find_matching_header(
        headers,
        ["target_element", "target element", "element", "target", "element_name", "locator", "control", "field", "component", "selector", "target_name"],
    )
    col_input = find_matching_header(
        headers,
        ["input_data", "input data", "filling_input_data", "filling input data", "value", "input", "data", "text", "val", "test_data", "parameter", "content"],
    )
    col_url = find_matching_header(headers, ["url", "link", "address", "page_url", "target_url"])
    col_wait = find_matching_header(
        headers,
        [
            "wait_after", "wait_after_s", "wait_after_seconds", "wait_after_sec",
            "wait_after_ms", "wait_s", "wait_sec", "wait", "delay", "delay_ms",
            "delay_s", "sleep", "pause", "wait_duration", "wait_seconds",
        ],
    )
    col_fail = find_matching_header(headers, ["on_fail", "onfail", "policy", "error_handling"])
    col_desc = find_matching_header(headers, ["description", "desc", "comment", "notes", "scenario", "name"])

    if not col_action:
        raise ValueError(
            "Could not identify an 'Action' column in the CSV. "
            "Please include a column like 'action', 'which action', or 'action_type'."
        )

    project = db_service.resolve_project(db, project_id)
    project_uuid = uuid.UUID(str(project["id"]))
    catalog = load_project_catalog_elements(db, project_uuid)

    steps: list[dict[str, Any]] = []

    for idx, raw_row in enumerate(reader, start=1):
        if not raw_row:
            continue
        row = {k.strip(): (v or "").strip() for k, v in raw_row.items() if k is not None}
        if not any(row.values()):
            continue

        raw_act = (row.get(col_action) or "").strip().lower()
        if not raw_act:
            continue

        clean_act = re.sub(r"[^a-z0-9_]", "", raw_act.replace(" ", "_").replace("-", "_"))
        action = ACTION_MAP.get(clean_act) or ACTION_MAP.get(raw_act)
        wait_from_action_name = None
        if not action:
            for p in ("wait", "pause", "sleep", "delay"):
                if raw_act.startswith(p):
                    action = "wait"
                    wait_from_action_name = extract_wait_seconds(raw_act)
                    break
        if not action:
            raise ValueError(f"Row {idx}: Unknown action '{raw_act}'. Supported actions: {list(ACTION_MAP.keys())[:12]}...")

        raw_target = (row.get(col_target) if col_target else "") or ""
        raw_val = (row.get(col_input) if col_input else "") or ""
        raw_url = (row.get(col_url) if col_url else "") or ""
        raw_wait = (row.get(col_wait) if col_wait else "") or "0"
        raw_fail = (row.get(col_fail) if col_fail else "") or "stop"
        raw_desc = (row.get(col_desc) if col_desc else "") or ""

        parsed_wait_sec = extract_wait_seconds(raw_wait)
        wait_ms = int(parsed_wait_sec * 1000) if (parsed_wait_sec is not None and parsed_wait_sec > 0) else 0

        on_fail = raw_fail.lower()
        if on_fail not in {"stop", "continue"} and not on_fail.startswith("retry:"):
            on_fail = "stop"

        params: dict[str, Any] = {
            "value": raw_val,
            "wait_after_ms": wait_ms,
            "original_target_input": raw_target,
        }

        locator_type: str | None = None
        locator_value: str = ""

        # Special Action 1: Navigation / Open App
        if action in ("open_app", "navigate"):
            target_url = raw_url or raw_val or raw_target or (project.get("base_url") or "")
            params["url"] = target_url
            description = raw_desc or f"Open application at {target_url}"
            steps.append({
                "step_order": idx,
                "action_type": action,
                "locator_type": None,
                "locator_value": target_url,
                "action_params": params,
                "on_fail": on_fail,
                "is_enabled": True,
                "timeout_ms": None,
                "description": description,
            })
            continue

        # Special Action 2: Login
        if action == "login":
            if raw_val:
                params["username"] = raw_val
            if raw_target:
                # If target element provided in login row, check if it's a catalog username or button
                matched_el, conf, reason = find_nearby_catalog_element(raw_target, catalog, "login")
                if matched_el:
                    if matched_el.get("category") == "button":
                        params["submit_locator"] = matched_el["locator_value"]
                        params["submit_friendly_name"] = matched_el["friendly_name"]
                    else:
                        params["username_locator"] = matched_el["locator_value"]
                        params["username_friendly_name"] = matched_el["friendly_name"]
            description = raw_desc or f"Login using application credentials"
            steps.append({
                "step_order": idx,
                "action_type": "login",
                "locator_type": None,
                "locator_value": "",
                "action_params": params,
                "on_fail": on_fail,
                "is_enabled": True,
                "timeout_ms": None,
                "description": description,
            })
            continue

        # Special Action 3: Wait / Pause Execution
        if action == "wait":
            sec = (
                extract_wait_seconds(raw_val)
                or extract_wait_seconds(raw_target)
                or wait_from_action_name
                or (wait_ms / 1000.0 if wait_ms > 0 else None)
                or 3.0
            )
            duration_ms = int(sec * 1000)
            sec_display = int(sec) if sec == int(sec) else sec
            desc = raw_desc or f"Wait {sec_display} second{'s' if sec_display != 1 else ''}"
            steps.append({
                "step_order": idx,
                "action_type": "wait",
                "locator_type": None,
                "locator_value": "",
                "action_params": {
                    "seconds": sec,
                    "duration_ms": duration_ms,
                    "value": str(sec_display),
                    "wait_after_ms": 0,
                },
                "on_fail": on_fail,
                "is_enabled": True,
                "timeout_ms": duration_ms + 10000,
                "description": desc,
            })
            continue

        # Actions requiring Target Elements
        if action in ELEMENT_REQUIRED_ACTIONS:
            if not raw_target:
                # If target is missing, check if URL or input was mistakenly swapped
                if raw_val and not raw_target and action == "click_element":
                    raw_target = raw_val
                    raw_val = ""
                    params["value"] = ""
                else:
                    raise ValueError(f"Row {idx}: Action '{raw_act}' requires a target element.")

            # Perform Fuzzy Nearby Catalog Matching
            matched_el, conf, match_reason = find_nearby_catalog_element(raw_target, catalog, action)

            if matched_el and conf >= 0.40:
                locator_type = matched_el["locator_strategy"]
                locator_value = matched_el["locator_value"]
                params.update({
                    "element_friendly_name": matched_el["friendly_name"],
                    "element_category": matched_el["category"],
                    "matched_from_catalog": True,
                    "match_confidence": round(conf, 2),
                    "match_reason": match_reason,
                    "catalog_id": matched_el.get("id"),
                })
            else:
                # If target looks like a direct selector (#id, .class, //xpath)
                if re.match(r"^[#\.\/\[]|^(xpath|css|id|name|text|role)=", raw_target, re.I):
                    locator_type = "smart"
                    locator_value = raw_target
                    params.update({
                        "element_friendly_name": raw_target,
                        "matched_from_catalog": False,
                        "direct_selector": True,
                    })
                elif matched_el:
                    # Pick closest nearby catalog match even with lower confidence
                    locator_type = matched_el["locator_strategy"]
                    locator_value = matched_el["locator_value"]
                    params.update({
                        "element_friendly_name": matched_el["friendly_name"],
                        "element_category": matched_el["category"],
                        "matched_from_catalog": True,
                        "match_confidence": round(conf, 2),
                        "match_reason": f"Nearby fallback: {match_reason}",
                        "nearby_warning": True,
                    })
                else:
                    # Generic smart locator fallback
                    locator_type = "smart"
                    locator_value = raw_target
                    params.update({
                        "element_friendly_name": raw_target,
                        "matched_from_catalog": False,
                    })

            # Action-specific parameter bindings
            if action == "verify_element":
                if raw_act == "verify_contains":
                    params.update({"verify_type": "contains_text", "expected": raw_val})
                elif raw_act == "verify_exact":
                    params.update({"verify_type": "exact_text", "expected": raw_val})
                else:
                    params.update({"verify_type": "visible" if not raw_val else "contains_text", "expected": raw_val})
            elif action == "select_option":
                params["option"] = raw_val
                params["value"] = raw_val

            friendly_label = params.get("element_friendly_name") or raw_target
            description = raw_desc or f"Step {idx}: {action.replace('_', ' ').capitalize()} '{friendly_label}'"
            if raw_val and action == "fill_input":
                description += f" with '{raw_val}'"

            steps.append({
                "step_order": idx,
                "action_type": action,
                "locator_type": locator_type or "smart",
                "locator_value": locator_value,
                "action_params": params,
                "on_fail": on_fail,
                "is_enabled": True,
                "timeout_ms": None,
                "description": description,
            })

    if not steps:
        raise ValueError("CSV contains no valid executable action rows.")

    return steps


@router.post("/validate")
async def validate_csv(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
):
    """
    Validate CSV structure.
    Intelligently handles both Action-based Workflow CSVs (with fuzzy catalog element resolution)
    and Legacy Pytest Scenario CSVs.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a .csv file.",
        )

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="CSV file exceeds the 5 MB limit.",
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

        # -------------------------------------------------------------
        # BRANCH 1: Action-based Workflow CSV Detection
        # -------------------------------------------------------------
        col_act = find_matching_header(
            headers,
            ["action", "which_action", "which action", "action_type", "action type", "operation", "command", "step_action"],
        )
        col_tgt = find_matching_header(
            headers,
            ["target_element", "target element", "element", "target", "element_name", "locator", "field", "control"],
        )
        col_inp = find_matching_header(
            headers,
            ["input_data", "input data", "filling_input_data", "filling input data", "value", "input", "data", "text"],
        )

        is_action_csv = bool(col_act and (col_tgt or col_inp or "TC_ID" not in headers))

        if is_action_csv:
            db = SessionLocal()
            try:
                steps = parse_csv_to_steps(text_content, project_id or "apex-timesheet", db)
                scenarios = []
                for s in steps:
                    params = s.get("action_params", {})
                    matched_name = params.get("element_friendly_name") or s.get("locator_value") or ""
                    orig_target = params.get("original_target_input") or ""
                    conf = params.get("match_confidence")
                    val = params.get("value") or ""

                    steps_desc = f"{s['action_type']} on {matched_name}"
                    if conf is not None:
                        steps_desc += f" (Catalog: {int(conf * 100)}% match)"
                    if val:
                        steps_desc += f" [Value: {val}]"
                    wait_ms_val = params.get("wait_after_ms", 0)
                    if wait_ms_val > 0:
                        steps_desc += f" [Wait: {round(wait_ms_val / 1000.0, 1)}s]"

                    scenarios.append({
                        "TC_ID": f"STEP-{s['step_order']:03d}",
                        "Scenario": s.get("description") or f"Execute {s['action_type']}",
                        "Preconditions": "",
                        "Steps": steps_desc,
                        "Expected_Result": "Step completed successfully",
                        "Priority": "HIGH",
                        "valid": True,
                        "mapped": True,
                        "action_type": s["action_type"],
                        "target_element": matched_name,
                        "original_target": orig_target,
                        "matched_catalog": params.get("matched_from_catalog", False),
                        "match_confidence": conf,
                        "match_reason": params.get("match_reason", ""),
                        "input_data": val,
                        "wait_after_ms": params.get("wait_after_ms", 0),
                    })

                return {
                    "valid": True,
                    "csv_type": "action_workflow",
                    "filename": file.filename,
                    "total_rows": len(steps),
                    "valid_rows": len(steps),
                    "errors": [],
                    "columns": headers,
                    "steps": steps,
                    "scenarios": scenarios,
                }
            except Exception as exc:
                return {
                    "valid": False,
                    "csv_type": "action_workflow",
                    "filename": file.filename,
                    "total_rows": 0,
                    "valid_rows": 0,
                    "errors": [str(exc)],
                    "columns": headers,
                    "scenarios": [],
                }
            finally:
                db.close()

        # -------------------------------------------------------------
        # BRANCH 2: Legacy Pytest Scenario CSV
        # -------------------------------------------------------------
        if len(headers) != len(set(headers)):
            raise HTTPException(
                status_code=400,
                detail="CSV contains duplicate column names.",
            )

        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Required CSV columns are missing for test scenarios.",
                    "missing_columns": missing,
                    "required_columns": REQUIRED_COLUMNS,
                    "hint": "For action-based testing, provide columns like: 'Action', 'Target Element', and 'Input Data'.",
                },
            )

        scenario_map = _get_project_mapping(project_id)
        scenarios = []
        errors = []
        seen_ids = set()

        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                errors.append({"row": row_number, "message": "Row contains more values than the header."})
                continue

            row = {key.strip(): (value or "").strip() for key, value in raw_row.items() if key is not None}
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
                row_errors.append("Priority must be High, Medium, or Low")

            if row_errors:
                errors.append({"row": row_number, "tc_id": tc_id, "messages": row_errors})

            mapped = tc_id in scenario_map
            row_valid = len(row_errors) == 0

            scenarios.append({
                **row,
                "valid": row_valid,
                "mapped": mapped,
                "pytest_id": scenario_map.get(tc_id),
            })

        valid_rows = sum(1 for item in scenarios if item["valid"])

        return {
            "valid": len(errors) == 0 and len(scenarios) > 0,
            "csv_type": "legacy_scenarios",
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
    """Run selected scenarios. Supports both dynamic action workflows and legacy pytest suites."""
    validation = await validate_csv(file, project_id=project_id)

    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV validation failed. Fix the CSV errors first.",
                "errors": validation["errors"],
            },
        )

    # -----------------------------------------------------------------
    # Case A: Action-based Dynamic Workflow Execution
    # -----------------------------------------------------------------
    if validation.get("csv_type") == "action_workflow":
        steps = validation.get("steps", [])
        if not steps:
            raise HTTPException(status_code=400, detail="No executable action steps found in CSV.")

        from app.scenarios_api import trigger_dynamic_workflow_run
        from app.schemas.scenarios import DynamicWorkflowPayload, ScenarioStepPayload

        # Convert dict steps to ScenarioStepPayload
        step_payloads = []
        for s in steps:
            step_payloads.append(ScenarioStepPayload(
                step_order=s["step_order"],
                action_type=s["action_type"],
                locator_type=s.get("locator_type"),
                locator_value=s.get("locator_value"),
                action_params=s.get("action_params", {}),
                on_fail=s.get("on_fail", "stop"),
                description=s.get("description"),
            ))

        workflow_name = file.filename.replace(".csv", "").replace("_", " ").title() if file.filename else "CSV Workflow"
        payload = DynamicWorkflowPayload(
            name=f"{workflow_name} (CSV)",
            description="Dynamic workflow executed from CSV actions with catalog matching",
            steps=step_payloads,
        )

        target_proj = project_id or "apex-timesheet"
        result = trigger_dynamic_workflow_run(target_proj, payload)
        return {
            **result,
            "csv_type": "action_workflow",
            "executed_steps_count": len(step_payloads),
        }

    # -----------------------------------------------------------------
    # Case B: Legacy Pytest Scenarios Execution
    # -----------------------------------------------------------------
    normalized_ids = [
        tc_id.strip()
        for value in selected_tc_ids
        for tc_id in value.split(",")
        if tc_id.strip()
    ]

    if not normalized_ids:
        raise HTTPException(status_code=400, detail="Select at least one test scenario.")

    scenario_by_id = {scenario["TC_ID"]: scenario for scenario in validation["scenarios"]}
    scenario_map = _get_project_mapping(project_id)
    pytest_ids = [scenario_map[tc_id] for tc_id in normalized_ids if tc_id in scenario_map]

    from app.main import RunRequest, start_run
    result = start_run(RunRequest(project_id=project_id, test_ids=pytest_ids))

    return {
        **result,
        "selected_tc_ids": normalized_ids,
        "pytest_test_ids": pytest_ids,
    }


@router.post("/workflow/parse")
async def parse_registry_workflow_csv(
    file: UploadFile = File(...),
    project_id: str = Form(...),
) -> dict[str, Any]:
    """Validate a workflow CSV and resolve its named elements from the catalog with fuzzy matching."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="CSV file exceeds the 5 MB limit.")
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

    resolved_count = sum(1 for s in steps if s.get("action_params", {}).get("matched_from_catalog"))
    return {
        "filename": file.filename,
        "project_id": project_id,
        "total_steps": len(steps),
        "resolved_catalog_elements": resolved_count,
        "steps": steps,
    }
