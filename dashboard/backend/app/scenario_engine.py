"""
Generic Playwright Execution Engine for Veriqon.
Executes configuration-driven test scenarios against any web application
without requiring dedicated Python test scripts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)
from sqlalchemy.orm import Session

from app import db_service
from app import scenarios_service

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"


def interpolate_variables(text_val: str, context: dict[str, Any]) -> str:
    """Replace {{variable_name}} placeholders with values from context."""
    if not isinstance(text_val, str) or "{{" not in text_val:
        return text_val

    def replacer(match):
        var_name = match.group(1).strip()
        val = context.get(var_name)
        if val is not None:
            return str(val)
        return match.group(0)

    return re.sub(r"\{\{([a-zA-Z0-9_\-\.]+)\}\}", replacer, text_val)


def _resolve_locator(page: Page, locator_type: str | None, locator_value: str):
    """Resolve Playwright locator from type and value."""
    l_type = (locator_type or "css").lower().strip()
    l_val = locator_value.strip()

    if l_type == "css":
        return page.locator(l_val)
    elif l_type == "xpath":
        return page.locator(f"xpath={l_val}")
    elif l_type == "id":
        return page.locator(f"#{l_val}")
    elif l_type == "name":
        return page.locator(f"[name='{l_val}']")
    elif l_type == "text":
        return page.get_by_text(l_val)
    elif l_type == "placeholder":
        return page.get_by_placeholder(l_val)
    elif l_type == "label":
        return page.get_by_label(l_val)
    elif l_type == "testid":
        return page.get_by_test_id(l_val)
    elif l_type == "role":
        return page.get_by_role(l_val)
    else:
        # Default fallback
        return page.locator(l_val)


class ScenarioExecutionError(Exception):
    pass


def run_generic_scenario(
    db: Session,
    run_uuid: uuid.UUID,
    project: dict[str, Any],
    scenario: dict[str, Any],
    decrypted_credentials: dict[str, str] | None = None,
    dataset_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute a generic test scenario step-by-step using Playwright.
    Records step-by-step execution results, screenshots, videos, and logs.
    """
    project_uuid = project["id"]
    project_ext_id = project["external_id"]
    base_url = (project.get("base_url") or "").rstrip("/")
    browser_name = project.get("browser", "chromium").lower()
    is_headless = project.get("headless", True)
    capture_screenshots = project.get("capture_screenshots", True)
    capture_video = project.get("capture_video", False)
    default_step_timeout_ms = (project.get("test_timeout_seconds") or 30) * 1000

    # Ensure artifacts directory exists for this run: artifacts/<project_id>/<run_id>/
    run_artifact_dir = ARTIFACTS_ROOT / project_ext_id / str(run_uuid)
    temp_video_dir = run_artifact_dir / "_temp_video"
    run_artifact_dir.mkdir(parents=True, exist_ok=True)
    if capture_video:
        temp_video_dir.mkdir(parents=True, exist_ok=True)

    log_file_path = run_artifact_dir / "run.log"
    logs: list[str] = []

    def log(msg: str):
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        formatted = f"[{now_str}] {msg}"
        logs.append(formatted)
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

    log(f"Starting execution for scenario: '{scenario['name']}' (Run ID: {run_uuid})")
    log(f"Target Application: '{project['name']}' at {base_url}")
    log(f"Browser: {browser_name} (Headless: {is_headless})")

    # Build interpolation context
    interp_context: dict[str, Any] = {
        "base_url": base_url,
        "environment": scenario.get("environment", "QA"),
    }
    if decrypted_credentials:
        interp_context["username"] = decrypted_credentials.get("username", "")
        interp_context["password"] = decrypted_credentials.get("secret", "")
    if dataset_row:
        for k, v in dataset_row.items():
            interp_context[k] = v

    steps: list[dict[str, Any]] = scenario.get("steps", [])
    failure_policy = scenario.get("failure_policy", "stop")
    scenario_uuid = None
    if scenario.get("id"):
        try:
            cand_uuid = uuid.UUID(scenario["id"]) if isinstance(scenario["id"], str) else scenario["id"]
            exists = db.execute(
                db_service.text("SELECT id FROM test_scenarios WHERE id = :id"),
                {"id": cand_uuid},
            ).scalar()
            if exists:
                scenario_uuid = cand_uuid
        except Exception:
            scenario_uuid = None

    # Mark run as running
    db_service.update_test_run(
        db,
        run_uuid,
        status="running",
        started_at=datetime.now(timezone.utc),
        log_path=str(log_file_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    )

    total_steps = len(steps)
    passed_count = 0
    failed_count = 0
    skipped_count = 0
    overall_status = "passed"
    execution_aborted = False

    with sync_playwright() as pw:
        # Launch browser
        browser_type = getattr(pw, browser_name, pw.chromium)
        browser: Browser = browser_type.launch(headless=is_headless)

        context_kwargs: dict[str, Any] = {
            "base_url": base_url if base_url else None,
            "viewport": {"width": 1280, "height": 720},
        }
        if capture_video:
            context_kwargs["record_video_dir"] = str(temp_video_dir)
            context_kwargs["record_video_size"] = {"width": 1280, "height": 720}

        context: BrowserContext = browser.new_context(**context_kwargs)
        page: Page = context.new_page()

        for step in steps:
            step_order = step.get("step_order", 1)
            action_type = (step.get("action_type") or "").strip().lower()
            locator_type = step.get("locator_type")
            locator_val_raw = step.get("locator_value") or ""
            locator_val = interpolate_variables(locator_val_raw, interp_context)
            action_params_raw = step.get("action_params") or {}
            step_desc = step.get("description") or f"Step {step_order}: {action_type}"
            is_enabled = step.get("is_enabled", True)
            step_timeout = step.get("timeout_ms") or default_step_timeout_ms

            # Interpolate parameters
            action_params: dict[str, Any] = {}
            for k, v in action_params_raw.items():
                if isinstance(v, str):
                    action_params[k] = interpolate_variables(v, interp_context)
                else:
                    action_params[k] = v

            if not is_enabled or execution_aborted:
                log(f"[SKIPPED] Step {step_order}: {step_desc}")
                scenarios_service.record_step_result(
                    db=db,
                    run_id=run_uuid,
                    scenario_id=scenario_uuid,
                    step_order=step_order,
                    action_type=action_type,
                    description=step_desc,
                    status="skipped",
                    duration_ms=0,
                )
                skipped_count += 1
                continue

            log(f"[RUNNING] Step {step_order}: {step_desc} (action: {action_type})")
            t_start = time.perf_counter()
            step_status = "passed"
            error_message = None
            actual_val = None
            expected_val = str(action_params.get("value") or action_params.get("text") or "")
            screenshot_art_id = None

            try:
                # Execute action
                if action_type == "navigate":
                    raw_url = action_params.get("url") or locator_val or "/"
                    url_to_go = interpolate_variables(raw_url, interp_context)
                    if url_to_go.startswith(("http://", "https://", "file://", "about:", "data:")):
                        target = url_to_go
                    elif url_to_go.startswith("/") and base_url:
                        target = f"{base_url}{url_to_go}"
                    elif base_url:
                        target = f"{base_url}/{url_to_go}"
                    else:
                        target = url_to_go
                    log(f"Navigating to: {target}")
                    page.goto(target, timeout=step_timeout)

                elif action_type == "click":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    loc.click(timeout=step_timeout)

                elif action_type == "fill":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    val = str(action_params.get("value", ""))
                    loc.fill(val, timeout=step_timeout)

                elif action_type == "type":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    val = str(action_params.get("value", ""))
                    loc.type(val, delay=int(action_params.get("delay", 50)), timeout=step_timeout)

                elif action_type == "clear":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    loc.clear(timeout=step_timeout)

                elif action_type == "press_key":
                    key = action_params.get("key", "Enter")
                    if locator_val:
                        loc = _resolve_locator(page, locator_type, locator_val)
                        loc.press(key, timeout=step_timeout)
                    else:
                        page.keyboard.press(key)

                elif action_type == "select_option":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    val = action_params.get("value") or action_params.get("label")
                    loc.select_option(val, timeout=step_timeout)

                elif action_type == "check":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    loc.check(timeout=step_timeout)

                elif action_type == "uncheck":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    loc.uncheck(timeout=step_timeout)

                elif action_type == "hover":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    loc.hover(timeout=step_timeout)

                elif action_type == "wait_for_timeout":
                    ms = int(action_params.get("timeout_ms") or action_params.get("ms") or 1000)
                    page.wait_for_timeout(ms)

                elif action_type == "wait_for_selector":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    state = action_params.get("state", "visible")
                    loc.wait_for(state=state, timeout=step_timeout)

                elif action_type == "wait_for_navigation":
                    page.wait_for_load_state(action_params.get("state", "load"), timeout=step_timeout)

                elif action_type == "assert_visible":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    is_vis = loc.is_visible()
                    actual_val = str(is_vis)
                    if not is_vis:
                        raise AssertionError(f"Element '{locator_val}' is not visible.")

                elif action_type == "assert_hidden":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    is_vis = loc.is_visible()
                    actual_val = str(not is_vis)
                    if is_vis:
                        raise AssertionError(f"Element '{locator_val}' is unexpectedly visible.")

                elif action_type == "assert_text":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    text_content = loc.inner_text(timeout=step_timeout).strip()
                    actual_val = text_content
                    expected = expected_val.strip()
                    exact = action_params.get("exact", False)
                    if exact:
                        if text_content != expected:
                            raise AssertionError(f"Expected exact text '{expected}', got '{text_content}'")
                    else:
                        if expected not in text_content:
                            raise AssertionError(f"Expected text '{expected}' to be contained in '{text_content}'")

                elif action_type == "assert_value":
                    loc = _resolve_locator(page, locator_type, locator_val)
                    val = loc.input_value(timeout=step_timeout)
                    actual_val = val
                    if val != expected_val:
                        raise AssertionError(f"Expected input value '{expected_val}', got '{val}'")

                elif action_type == "assert_title":
                    title = page.title()
                    actual_val = title
                    if expected_val not in title:
                        raise AssertionError(f"Expected title to contain '{expected_val}', got '{title}'")

                elif action_type == "assert_url":
                    cur_url = page.url
                    actual_val = cur_url
                    if expected_val not in cur_url:
                        raise AssertionError(f"Expected URL to contain '{expected_val}', got '{cur_url}'")

                elif action_type == "capture_screenshot":
                    shot_name = f"step_{step_order}_custom.png"
                    shot_path = run_artifact_dir / shot_name
                    page.screenshot(path=str(shot_path), full_page=True)
                    art = db_service.register_artifact(
                        db=db,
                        project_uuid=project_uuid,
                        run_uuid=run_uuid,
                        artifact_type="screenshot",
                        file_path=shot_path,
                    )
                    if art:
                        screenshot_art_id = art["id"]
                    log(f"Custom screenshot captured: {shot_path.name}")

                elif action_type == "login":
                    user_val = interp_context.get("username", "")
                    pass_val = interp_context.get("password", "")
                    if not user_val or not pass_val:
                        raise ValueError(
                            "Cannot perform login: no credentials available in the application's vault. "
                            "Please add a credential profile under the Credentials tab."
                        )

                    user_sel = locator_value if (has_loc and locator_value) else None
                    if not user_sel:
                        candidate_user_selectors = [
                            "input[name='username']",
                            "input[name='user']",
                            "input[type='email']",
                            "#P9999_USERNAME",
                            "#username",
                            "input[id*='user' i]",
                            "input[placeholder*='user' i]",
                            "input[placeholder*='email' i]",
                        ]
                        for c_sel in candidate_user_selectors:
                            try:
                                loc = page.locator(c_sel).first
                                if loc.count() > 0 and loc.is_visible():
                                    user_sel = c_sel
                                    break
                            except Exception:
                                continue
                        if not user_sel:
                            user_sel = "input[name='username'], #username, #P9999_USERNAME"

                    candidate_pass_selectors = [
                        "input[type='password']",
                        "input[name='password']",
                        "#P9999_PASSWORD",
                        "#password",
                        "input[id*='pass' i]",
                    ]
                    pass_sel = None
                    for p_sel in candidate_pass_selectors:
                        try:
                            loc = page.locator(p_sel).first
                            if loc.count() > 0 and loc.is_visible():
                                pass_sel = p_sel
                                break
                        except Exception:
                            continue
                    if not pass_sel:
                        pass_sel = "input[type='password'], #P9999_PASSWORD"

                    candidate_btn_selectors = [
                        "button[type='submit']",
                        "input[type='submit']",
                        "#B9999_LOGIN",
                        "#login-btn",
                        "button:has-text('Sign In')",
                        "button:has-text('Log In')",
                        "button:has-text('Login')",
                    ]
                    btn_sel = None
                    for b_sel in candidate_btn_selectors:
                        try:
                            loc = page.locator(b_sel).first
                            if loc.count() > 0 and loc.is_visible():
                                btn_sel = b_sel
                                break
                        except Exception:
                            continue
                    if not btn_sel:
                        btn_sel = "button[type='submit'], #B9999_LOGIN"

                    log(f"Executing login: entering username into '{user_sel}'")
                    page.locator(user_sel).first.fill(user_val, timeout=step_timeout_ms)
                    log(f"Entering password into '{pass_sel}'")
                    page.locator(pass_sel).first.fill(pass_val, timeout=step_timeout_ms)
                    log(f"Clicking submit via '{btn_sel}'")
                    page.locator(btn_sel).first.click(timeout=step_timeout_ms)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=step_timeout_ms)
                    except Exception:
                        pass
                    actual_val = f"Submitted login credentials for {user_val}"

                else:
                    raise ValueError(f"Unsupported action_type: '{action_type}'")

            except Exception as exc:
                step_status = "failed"
                overall_status = "failed"
                error_message = str(exc)
                log(f"[ERROR] Step {step_order} failed: {error_message}")

                # Capture failure screenshot
                if capture_screenshots:
                    try:
                        shot_name = f"failure_step_{step_order}.png"
                        shot_path = run_artifact_dir / shot_name
                        page.screenshot(path=str(shot_path), full_page=True)
                        art = db_service.register_artifact(
                            db=db,
                            project_uuid=project_uuid,
                            run_uuid=run_uuid,
                            artifact_type="screenshot",
                            file_path=shot_path,
                        )
                        if art:
                            screenshot_art_id = art["id"]
                        log(f"Failure screenshot captured: {shot_name}")
                    except Exception as shot_err:
                        log(f"Could not capture failure screenshot: {shot_err}")

                if failure_policy == "stop":
                    execution_aborted = True
                    log("Scenario failure policy is 'stop'. Aborting remaining steps.")

            t_duration_ms = int((time.perf_counter() - t_start) * 1000)

            # Record step result in database
            scenarios_service.record_step_result(
                db=db,
                run_id=run_uuid,
                scenario_id=scenario_uuid,
                step_order=step_order,
                action_type=action_type,
                description=step_desc,
                status=step_status,
                duration_ms=t_duration_ms,
                actual_value=actual_val,
                expected_value=expected_val or None,
                error_message=error_message,
                screenshot_artifact_id=screenshot_art_id,
            )

            if step_status == "passed":
                passed_count += 1
                log(f"[PASSED] Step {step_order} finished in {t_duration_ms}ms")
            else:
                failed_count += 1

        # Close page & context to flush video
        try:
            page.close()
            context.close()
            browser.close()
        except Exception as close_err:
            log(f"Error during browser teardown: {close_err}")

    # Process recorded video if enabled
    if capture_video and temp_video_dir.exists():
        video_files = list(temp_video_dir.glob("*.webm"))
        if video_files:
            target_video_file = run_artifact_dir / "recording.webm"
            try:
                # Move first recorded video to standard name
                shutil.move(str(video_files[0]), str(target_video_file))
                db_service.register_artifact(
                    db=db,
                    project_uuid=project_uuid,
                    run_uuid=run_uuid,
                    artifact_type="video",
                    file_path=target_video_file,
                )
                log(f"Video saved and registered: {target_video_file.name}")
            except Exception as vid_err:
                log(f"Failed to save video: {vid_err}")
        try:
            shutil.rmtree(temp_video_dir, ignore_errors=True)
        except Exception:
            pass

    # Register log artifact
    if log_file_path.exists():
        db_service.register_artifact(
            db=db,
            project_uuid=project_uuid,
            run_uuid=run_uuid,
            artifact_type="log",
            file_path=log_file_path,
        )

    # Save summary and complete run
    summary = {
        "total": total_steps,
        "passed": passed_count,
        "failed": failed_count,
        "skipped": skipped_count,
    }
    exit_code = 0 if overall_status == "passed" else 1

    db_service.update_test_run(
        db,
        run_uuid,
        status=overall_status,
        finished_at=datetime.now(timezone.utc),
        exit_code=exit_code,
        summary=summary,
    )

    # Also register results in test_run_results table for standard history view
    db_service.save_test_results(
        db,
        run_uuid,
        [
            {
                "name": f"Scenario: {scenario['name']}",
                "status": overall_status,
                "duration": sum(s.get("duration_ms", 0) for s in steps) / 1000.0,
                "error": f"{failed_count} step(s) failed." if failed_count > 0 else None,
            }
        ],
    )

    log(f"Scenario execution completed with status: {overall_status.upper()}")
    log(f"Summary: {passed_count}/{total_steps} passed, {failed_count} failed, {skipped_count} skipped.")

    return {
        "run_id": str(run_uuid),
        "status": overall_status,
        "summary": summary,
        "exit_code": exit_code,
    }
