"""
Generic Playwright Execution Engine for Veriqon.
Executes configuration-driven test scenarios and dynamic workflows against any registered
web application without requiring dedicated Python test scripts.
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
from typing import Any, Callable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)
from sqlalchemy.orm import Session

from app import db_service
from app import scenarios_service

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"


class AmbiguityError(Exception):
    """Raised when a locator matches multiple visible interactive elements unexpectedly."""
    pass


class ScenarioExecutionError(Exception):
    pass


# Global tracking of active Playwright browser sessions for cancellation
active_browser_sessions: dict[str, dict[str, Any]] = {}


def cancel_scenario_run(run_id: str) -> bool:
    """Cancels and terminates an active browser automation session."""
    session = active_browser_sessions.get(str(run_id))
    if session:
        session["cancelled"] = True
        try:
            page = session.get("page")
            if page:
                page.close()
        except Exception:
            pass
        try:
            context = session.get("context")
            if context:
                context.close()
        except Exception:
            pass
        try:
            browser = session.get("browser")
            if browser:
                browser.close()
        except Exception:
            pass
        return True
    return False


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


def check_ambiguity(loc: Locator, locator_desc: str) -> Locator:
    """
    Checks if a Playwright locator matches multiple visible elements.
    If multiple elements match:
      - Counts visible elements.
      - If count of visible elements > 1, raises AmbiguityError.
      - If count == 1, returns that single visible element.
      - If count == 0, returns the original locator (so Playwright's timeout error will report appropriately).
    """
    try:
        total = loc.count()
        if total > 1:
            visible_elements: list[Locator] = []
            for i in range(total):
                nth_loc = loc.nth(i)
                try:
                    if nth_loc.is_visible():
                        visible_elements.append(nth_loc)
                except Exception:
                    pass

            if len(visible_elements) > 1:
                raise AmbiguityError(
                    f"Ambiguity detected: locator '{locator_desc}' matched {len(visible_elements)} visible elements "
                    f"(out of {total} total matching elements). "
                    "Please specify an accessible role/name, unique label, or more specific selector to avoid unintended actions."
                )
            elif len(visible_elements) == 1:
                return visible_elements[0]
    except AmbiguityError:
        raise
    except Exception:
        # Fallback if page navigation in progress or count cannot be evaluated synchronously
        pass
    return loc


def resolve_locator_safely(
    page: Page,
    locator_type: str | None,
    locator_value: str,
    role_hint: str | None = None,
) -> Locator:
    """
    Resolve Playwright locator using multi-locator priority strategies with ambiguity detection:
      1. Accessible role & accessible name
      2. Associated label
      3. Placeholder
      4. Other reliable user-facing text
      5. CSS selector
      6. XPath
    """
    l_type = (locator_type or "smart").lower().strip()
    l_val = (locator_value or "").strip()
    desc = f"{l_type}='{l_val}'"

    if not l_val:
        raise ValueError("Locator value cannot be empty.")

    # 1. Explicit ARIA Role
    if l_type == "role":
        # Supports "button:Submit" or role_hint with l_val as accessible name
        if ":" in l_val:
            role_part, name_part = l_val.split(":", 1)
            raw_loc = page.get_by_role(role_part.strip(), name=name_part.strip())
        elif role_hint:
            raw_loc = page.get_by_role(role_hint, name=l_val)
        else:
            raw_loc = page.get_by_role(l_val)
        return check_ambiguity(raw_loc, desc)

    # 2. Associated Form Label
    elif l_type == "label":
        raw_loc = page.get_by_label(l_val)
        return check_ambiguity(raw_loc, desc)

    # 3. Placeholder
    elif l_type == "placeholder":
        raw_loc = page.get_by_placeholder(l_val)
        return check_ambiguity(raw_loc, desc)

    # 4. Visible Text
    elif l_type == "text":
        raw_loc = page.get_by_text(l_val)
        return check_ambiguity(raw_loc, desc)

    # 5. CSS Selector
    elif l_type == "css":
        raw_loc = page.locator(l_val)
        return check_ambiguity(raw_loc, desc)

    # 6. XPath
    elif l_type == "xpath":
        raw_loc = page.locator(f"xpath={l_val}" if not l_val.startswith("xpath=") else l_val)
        return check_ambiguity(raw_loc, desc)

    # 7. Common HTML Attributes
    elif l_type == "id":
        raw_loc = page.locator(f"#{l_val}")
        return check_ambiguity(raw_loc, desc)
    elif l_type == "name":
        raw_loc = page.locator(f"[name='{l_val}']")
        return check_ambiguity(raw_loc, desc)
    elif l_type == "testid":
        raw_loc = page.get_by_test_id(l_val)
        return check_ambiguity(raw_loc, desc)

    # 8. Smart Dynamic Resolution: Priority order
    else:
        # Check if clearly XPath
        if l_val.startswith(("//", "(//")):
            raw_loc = page.locator(f"xpath={l_val}")
            return check_ambiguity(raw_loc, desc)

        # Check if clearly CSS ID or class or attribute
        if (l_val.startswith("#") and " " not in l_val and ":" not in l_val) or \
           (l_val.startswith(".") and " " not in l_val) or \
           (l_val.startswith("[") and l_val.endswith("]")):
            raw_loc = page.locator(l_val)
            return check_ambiguity(raw_loc, desc)

        # Try ARIA Role & Name if role_hint provided
        if role_hint:
            try:
                candidate = page.get_by_role(role_hint, name=l_val)
                if candidate.count() > 0:
                    return check_ambiguity(candidate, desc)
            except Exception:
                pass

        # If role_hint is link/nav/menu or unspecified, check treeitem, menuitem, tab, button
        if role_hint in ("link", "nav", "menu", None):
            for nav_role in ("treeitem", "menuitem", "tab", "link", "button"):
                try:
                    candidate = page.get_by_role(nav_role, name=l_val)
                    if candidate.count() > 0:
                        return check_ambiguity(candidate, desc)
                except Exception:
                    pass

        # Try Associated Label
        try:
            candidate = page.get_by_label(l_val)
            if candidate.count() > 0:
                return check_ambiguity(candidate, desc)
        except Exception:
            pass

        # Try Placeholder
        try:
            candidate = page.get_by_placeholder(l_val)
            if candidate.count() > 0:
                return check_ambiguity(candidate, desc)
        except Exception:
            pass

        # Try common button/link roles
        try:
            btn_candidate = page.get_by_role("button", name=l_val)
            if btn_candidate.count() > 0:
                return check_ambiguity(btn_candidate, desc)
        except Exception:
            pass

        try:
            link_candidate = page.get_by_role("link", name=l_val)
            if link_candidate.count() > 0:
                return check_ambiguity(link_candidate, desc)
        except Exception:
            pass

        # Try Visible Text (exact and substring)
        try:
            text_candidate = page.get_by_text(l_val, exact=True)
            if text_candidate.count() > 0:
                return check_ambiguity(text_candidate, desc)
        except Exception:
            pass

        try:
            text_candidate = page.get_by_text(l_val, exact=False)
            if text_candidate.count() > 0:
                return check_ambiguity(text_candidate, desc)
        except Exception:
            pass

        # Try interactive tag text locators
        try:
            tag_text = page.locator(
                f"a:has-text('{l_val}'), button:has-text('{l_val}'), [role='treeitem']:has-text('{l_val}'), [role='menuitem']:has-text('{l_val}')"
            )
            if tag_text.count() > 0:
                return check_ambiguity(tag_text, desc)
        except Exception:
            pass

        # If l_val contains spaces and doesn't look like a CSS/XPath selector, treat as text locator
        is_selector_syntax = any(c in l_val for c in "#.[]:=>+~/@")
        if not is_selector_syntax and " " in l_val:
            raw_loc = page.locator(f"text='{l_val}'")
            return check_ambiguity(raw_loc, desc)

        # Fallback to standard Playwright locator
        raw_loc = page.locator(l_val)
        return check_ambiguity(raw_loc, desc)


def ensure_navigation_expanded(page: Page, log: Callable[[str], None] | None = None) -> bool:
    """
    Checks if an application navigation drawer / sidebar is currently collapsed,
    and expands it if so. Generic across Oracle APEX, Bootstrap, Ant Design, Material UI, and standard admin templates.
    """
    nav_toggle_selectors = [
        "#t_Button_navControl",
        "button.a-Button--navControl",
        "button[aria-controls*='TreeNav']",
        "button[aria-controls*='nav' i]",
        "button[aria-label*='Main Navigation' i]",
        "button[aria-label*='navigation' i]",
        "button[aria-label*='Toggle navigation' i]",
        "button[aria-label*='menu' i]",
        "button.navbar-toggler",
        "[data-action='toggle-nav']",
        ".t-Header-nav-list button",
    ]
    for sel in nav_toggle_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                aria_exp = btn.get_attribute("aria-expanded")
                # Expand if not expanded
                if aria_exp == "false" or (sel == "#t_Button_navControl" and aria_exp != "true"):
                    if log:
                        log(f"Navigation menu is collapsed ({sel}, aria-expanded={aria_exp}). Automatically expanding...")
                    btn.click()
                    page.wait_for_timeout(1000)
                    return True
        except Exception:
            continue
    return False


def robust_click(
    page: Page,
    locator_type: str | None,
    locator_val: str,
    role_hint: str | None = None,
    timeout: int = 15000,
    log: Callable[[str], None] | None = None,
) -> None:
    """
    Performs a resilient click operation against modern dynamic SPAs (APEX, React, Oracle Cloud):
      1. Pre-waits for DOM readiness.
      2. Multi-attempt click with fresh locator resolution on each attempt to survive DOM detachment.
      3. Automatic expansion of collapsed navigation sidebars/drawers when targeting menu items.
      4. Automatic fallback to force-click.
      5. Automatic fallback to direct href navigation for <a> tags.
      6. Automatic fallback to JavaScript evaluation (el.click()).
      7. Automatic fallback to full-DOM text match and click.
    """
    if not locator_val:
        raise ValueError("Locator value cannot be empty for click action.")

    try:
        page.wait_for_load_state("domcontentloaded", timeout=3000)
    except Exception:
        pass

    last_error = None
    attempt_timeout = min(timeout, 8000)

    for attempt in range(1, 4):
        try:
            loc = resolve_locator_safely(page, locator_type, locator_val, role_hint=role_hint)
            cnt = loc.count()
            if log:
                log(f"[DEBUG] Attempt {attempt} locator: {loc} (count={cnt})")
            # If locator has 0 count on attempt, try expanding nav drawer in case target is in collapsed menu
            if cnt == 0:
                if ensure_navigation_expanded(page, log=log):
                    loc = resolve_locator_safely(page, locator_type, locator_val, role_hint=role_hint)
                    cnt = loc.count()
                    if log:
                        log(f"[DEBUG] After nav expansion, locator count={cnt}")

            loc.first.wait_for(state="visible", timeout=attempt_timeout)
            loc.first.click(timeout=attempt_timeout)
            return
        except Exception as exc:
            last_error = exc
            err_msg = str(exc)
            if log:
                log(f"[DEBUG] Click attempt {attempt} failed: {exc.__class__.__name__}: {err_msg[:120]}")

    # Fallback 1: Force click
    try:
        if log:
            log(f"Attempting force click on '{locator_val}'...")
        loc = resolve_locator_safely(page, locator_type, locator_val, role_hint=role_hint)
        loc.first.click(force=True, timeout=5000)
        return
    except Exception as exc:
        last_error = exc

    # Fallback 2: Direct href navigation if element is an anchor link
    try:
        loc = resolve_locator_safely(page, locator_type, locator_val, role_hint=role_hint)
        tag = loc.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == "a":
            href = loc.first.get_attribute("href")
            if href:
                if log:
                    log(f"Target is a hyperlink. Navigating directly to href: {href}")
                if href.startswith(("http://", "https://")):
                    target_url = href
                else:
                    origin = page.url.split("/ords")[0] if "/ords" in page.url else page.url.rstrip("/")
                    target_url = f"{origin}{href}" if href.startswith("/") else f"{origin}/{href}"
                page.goto(target_url, wait_until="domcontentloaded", timeout=timeout)
                return
    except Exception:
        pass

    # Fallback 3: JavaScript click
    try:
        if log:
            log(f"Attempting JavaScript evaluation click on '{locator_val}'...")
        loc = resolve_locator_safely(page, locator_type, locator_val, role_hint=role_hint)
        loc.first.evaluate("el => el.click()")
        return
    except Exception as exc:
        last_error = exc

    # Fallback 4: DOM search by text match across all interactive nodes
    try:
        if log:
            log(f"Searching DOM for interactive element matching text '{locator_val}'...")
        clicked = page.evaluate("""(targetText) => {
            const clean = targetText.trim().toLowerCase();
            const elements = Array.from(document.querySelectorAll('a, button, [role="treeitem"], [role="menuitem"], [role="tab"], li, span, div.a-TreeView-content'));
            for (const el of elements) {
                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (txt === clean) {
                    el.click();
                    return true;
                }
            }
            for (const el of elements) {
                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (txt.includes(clean)) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""", locator_val)
        if clicked:
            if log:
                log(f"Successfully clicked DOM element matching text '{locator_val}'.")
            page.wait_for_timeout(1000)
            return
    except Exception as exc:
        last_error = exc

    if last_error:
        raise last_error

    if last_error:
        raise last_error


# =====================================================================
# Modular Action Handlers (8 Core Actions + Helpers)
# =====================================================================

def handle_open_app(
    page: Page,
    base_url: str,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """Action 1: Open Application. Opens base URL or safe relative override."""
    raw_path = action_params.get("path") or action_params.get("url") or locator_val or "/"
    if raw_path.startswith(("http://", "https://", "file://", "about:", "data:")):
        target = raw_path
    elif raw_path.startswith("/") and base_url:
        target = f"{base_url}{raw_path}"
    elif base_url:
        target = f"{base_url}/{raw_path}"
    else:
        target = raw_path

    log(f"Opening application at: {target}")
    page.goto(target, wait_until="domcontentloaded", timeout=max(step_timeout, 45000))
    try:
        page.wait_for_load_state("load", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    return f"Opened application at {target}", target


def handle_login(
    page: Page,
    base_url: str,
    interp_context: dict[str, Any],
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """
    Action 2: Login. Uses saved application credentials from vault.
    Never exposes or logs secret credentials.
    """
    user_val = interp_context.get("username", "")
    pass_val = interp_context.get("password", "")

    if not user_val or not pass_val:
        raise ValueError(
            "Cannot perform login: No credentials configured for this application in the database vault. "
            "Please configure credentials under the Credentials tab before running."
        )

    # 1. Identify Username field
    user_loc = None
    custom_user = action_params.get("username_locator") or (locator_val if locator_type in ("label", "id", "name", "css", "xpath") else None)
    if custom_user:
        user_loc = resolve_locator_safely(page, action_params.get("username_locator_type") or locator_type, custom_user, role_hint="textbox")
    else:
        # Multi-locator strategy for username
        username_attempts = [
            lambda: page.get_by_role("textbox", name="Username"),
            lambda: page.get_by_role("textbox", name="User ID"),
            lambda: page.get_by_role("textbox", name="Email"),
            lambda: page.get_by_label(re.compile("username|email|user id", re.I)),
            lambda: page.get_by_placeholder(re.compile("username|email", re.I)),
            lambda: page.locator("input[id*='signin-form-username']").first,
            lambda: page.locator("input[name='username']").first,
            lambda: page.locator("#P9999_USERNAME").first,
            lambda: page.locator("#username").first,
            lambda: page.locator("input[type='email']").first,
        ]
        for attempt in username_attempts:
            try:
                candidate = attempt()
                if candidate.count() > 0 and candidate.is_visible():
                    user_loc = candidate
                    break
            except Exception:
                continue

    if not user_loc:
        raise ValueError("Could not automatically locate the Username field. Please specify a username locator in the action settings.")

    # 2. Identify Password field
    pass_loc = None
    custom_pass = action_params.get("password_locator")
    if custom_pass:
        pass_loc = resolve_locator_safely(page, action_params.get("password_locator_type"), custom_pass, role_hint="textbox")
    else:
        pass_attempts = [
            lambda: page.get_by_role("textbox", name="Password"),
            lambda: page.get_by_label(re.compile("password", re.I)),
            lambda: page.locator("input[type='password']").first,
            lambda: page.locator("input[id*='signin-form-password']").first,
            lambda: page.locator("#P9999_PASSWORD").first,
            lambda: page.locator("#password").first,
            lambda: page.locator("input[name='password']").first,
        ]
        for attempt in pass_attempts:
            try:
                candidate = attempt()
                if candidate.count() > 0 and candidate.is_visible():
                    pass_loc = candidate
                    break
            except Exception:
                continue

    if not pass_loc:
        raise ValueError("Could not automatically locate the Password field. Please specify a password locator in the action settings.")

    # 3. Identify Submit button
    btn_loc = None
    custom_btn = action_params.get("submit_locator")
    if custom_btn:
        btn_loc = resolve_locator_safely(page, action_params.get("submit_locator_type"), custom_btn, role_hint="button")
    else:
        btn_attempts = [
            lambda: page.get_by_role("button", name="Sign In"),
            lambda: page.get_by_role("button", name="Sign in"),
            lambda: page.get_by_role("button", name="Log In"),
            lambda: page.get_by_role("button", name="Login"),
            lambda: page.get_by_role("button", name="Next"),
            lambda: page.locator("button:has-text('Sign In')").first,
            lambda: page.locator("button:has-text('Next')").first,
            lambda: page.locator("button[type='submit']").first,
            lambda: page.locator("input[type='submit']").first,
            lambda: page.locator("#B9999_LOGIN").first,
        ]
        for attempt in btn_attempts:
            try:
                candidate = attempt()
                if candidate.count() > 0 and candidate.is_visible():
                    btn_loc = candidate
                    break
            except Exception:
                continue

    if not btn_loc:
        raise ValueError("Could not automatically locate the Login/Submit button. Please specify a submit button locator in the action settings.")

    log(f"Entering username for account '{user_val}' into login form...")
    user_loc.fill(user_val, timeout=step_timeout)

    log("Entering encrypted vault password into password field...")
    pass_loc.fill(pass_val, timeout=step_timeout)

    log("Submitting login form...")
    btn_loc.click(timeout=step_timeout)

    # Allow post-login transitions, redirects, and async tree widgets to fully settle
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(2500)

    # Auto-expand navigation drawer if collapsed (e.g. Oracle APEX, modern SPAs) so menu links are available
    ensure_navigation_expanded(page, log=log)

    # Optional post-login verification condition
    post_cond_type = action_params.get("post_login_condition")
    if post_cond_type == "url_contains" and action_params.get("post_login_value"):
        expected_part = action_params["post_login_value"]
        if expected_part not in page.url:
            raise AssertionError(f"Post-login verification failed: URL does not contain '{expected_part}'. Current URL: {page.url}")
    elif post_cond_type == "selector_visible" and action_params.get("post_login_value"):
        post_loc = page.locator(action_params["post_login_value"])
        post_loc.wait_for(state="visible", timeout=step_timeout)

    return f"Logged in with vault user '{user_val}'", f"Authenticated as {user_val}"


def handle_navigate(
    page: Page,
    base_url: str,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """
    Action 3: Navigate.
    Automatically detects whether the target is a menu/link name (to click)
    or a URL path / route (to navigate directly).
    """
    nav_method = action_params.get("method") or action_params.get("nav_type")
    raw_target = action_params.get("path") or action_params.get("url") or locator_val or ""
    raw_target = raw_target.strip()

    is_path = (
        nav_method == "path"
        or raw_target.startswith(("/", "http://", "https://", "./", "../"))
        or "?" in raw_target
        or raw_target.endswith((".html", ".jsp", ".aspx", ".php"))
    )

    if not is_path and (nav_method == "click" or raw_target):
        log(f"Navigating by clicking UI link/menu item '{raw_target}'...")
        ensure_navigation_expanded(page, log=log)
        robust_click(page, locator_type, raw_target, role_hint="link", timeout=step_timeout, log=log)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=step_timeout)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        return f"Navigated to '{raw_target}'", raw_target
    else:
        path = raw_target or "/"
        if path.startswith(("http://", "https://", "file://", "about:", "data:")):
            target = path
        elif path.startswith("/") and base_url:
            target = f"{base_url.rstrip('/')}{path}"
        elif base_url:
            target = f"{base_url.rstrip('/')}/{path}"
        else:
            target = path

        log(f"Navigating to page path: {target}")
        page.goto(target, wait_until="domcontentloaded", timeout=max(step_timeout, 45000))
        try:
            page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        return f"Navigated to {target}", target


def handle_fill_input(
    page: Page,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """Action 4: Fill Input. Enters value into input field with priority locators."""
    val = str(action_params.get("value", ""))
    loc = resolve_locator_safely(page, locator_type, locator_val, role_hint="textbox")

    log(f"Filling input '{locator_val}' with value '{val}'...")
    clear_first = action_params.get("clear_first", True)
    if clear_first:
        loc.fill(val, timeout=step_timeout)
    else:
        loc.type(val, delay=int(action_params.get("delay", 20)), timeout=step_timeout)

    return f"Filled '{val}' into '{locator_val}'", val


def handle_click_element(
    page: Page,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """Action 5: Click Element. Clicks target element with resilience against DOM transitions."""
    click_type = action_params.get("click_type", "click")
    log(f"Clicking element '{locator_val}' ({click_type})...")

    if click_type == "double":
        loc = resolve_locator_safely(page, locator_type, locator_val, role_hint="button")
        loc.dblclick(timeout=step_timeout)
    else:
        robust_click(page, locator_type, locator_val, role_hint="button", timeout=step_timeout, log=log)

    return f"Clicked element '{locator_val}'", locator_val


def handle_select_option(
    page: Page,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """
    Action 6: Select Option.
    Supports native HTML select controls. Reports custom dropdowns clearly.
    """
    loc = resolve_locator_safely(page, locator_type, locator_val, role_hint="combobox")
    opt = action_params.get("value") or action_params.get("label") or action_params.get("option")
    if opt is None:
        raise ValueError("Must provide an option label or value to select.")

    # Check element tag
    try:
        tag_name = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag_name != "select":
            raise ValueError(
                f"Element '{locator_val}' is a <{tag_name}>, not a native HTML <select> dropdown. "
                "For custom ARIA dropdowns, use 'Click Element' on the dropdown trigger, followed by 'Click Element' on the target option."
            )
    except Exception as e:
        if "not a native HTML <select>" in str(e):
            raise

    log(f"Selecting option '{opt}' in dropdown '{locator_val}'...")
    loc.select_option(opt, timeout=step_timeout)
    return f"Selected '{opt}' in '{locator_val}'", str(opt)


def handle_verify_element(
    page: Page,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """
    Action 7: Verify Element.
    Supports visible, hidden, contains_text, exact_text, input_value, url_contains, page_title.
    """
    verify_type = action_params.get("verify_type") or action_params.get("type") or "visible"
    expected = str(action_params.get("expected") or action_params.get("value") or action_params.get("text") or "")

    log(f"Executing verification: type='{verify_type}', target='{locator_val}', expected='{expected}'")

    if verify_type == "visible":
        loc = resolve_locator_safely(page, locator_type, locator_val)
        is_vis = loc.is_visible()
        if not is_vis:
            raise AssertionError(f"Verification failed: Element '{locator_val}' is not visible.")
        return "Element is visible", "visible"

    elif verify_type == "hidden":
        loc = resolve_locator_safely(page, locator_type, locator_val)
        is_vis = loc.is_visible()
        if is_vis:
            raise AssertionError(f"Verification failed: Element '{locator_val}' is unexpectedly visible.")
        return "Element is hidden", "hidden"

    elif verify_type == "contains_text":
        loc = resolve_locator_safely(page, locator_type, locator_val)
        text = loc.inner_text(timeout=step_timeout).strip()
        if expected.lower() not in text.lower():
            raise AssertionError(f"Verification failed: Expected text '{expected}' was not found in '{text}'.")
        return text, expected

    elif verify_type == "exact_text":
        loc = resolve_locator_safely(page, locator_type, locator_val)
        text = loc.inner_text(timeout=step_timeout).strip()
        if text != expected.strip():
            raise AssertionError(f"Verification failed: Expected exact text '{expected}', but found '{text}'.")
        return text, expected

    elif verify_type == "input_value":
        loc = resolve_locator_safely(page, locator_type, locator_val, role_hint="textbox")
        actual_val = loc.input_value(timeout=step_timeout)
        if actual_val != expected:
            raise AssertionError(f"Verification failed: Expected input value '{expected}', but found '{actual_val}'.")
        return actual_val, expected

    elif verify_type == "url_contains":
        cur_url = page.url
        if expected not in cur_url:
            raise AssertionError(f"Verification failed: Current URL '{cur_url}' does not contain expected substring '{expected}'.")
        return cur_url, expected

    elif verify_type == "page_title":
        cur_title = page.title()
        if expected.lower() not in cur_title.lower():
            raise AssertionError(f"Verification failed: Page title '{cur_title}' does not contain '{expected}'.")
        return cur_title, expected

    else:
        raise ValueError(f"Unknown verify_type: '{verify_type}'. Supported: visible, hidden, contains_text, exact_text, input_value, url_contains, page_title.")


def handle_wait_for_element(
    page: Page,
    action_params: dict[str, Any],
    locator_type: str | None,
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """
    Action 8: Wait for Element.
    Supports waiting for element condition (visible, hidden, attached, detached) or duration in ms.
    """
    condition = action_params.get("condition") or "visible"

    if condition == "duration" or not locator_val:
        ms = int(action_params.get("duration_ms") or action_params.get("timeout_ms") or action_params.get("ms") or 1000)
        log(f"Pausing execution for {ms}ms...")
        page.wait_for_timeout(ms)
        return f"Waited {ms}ms", f"{ms}ms"

    loc = resolve_locator_safely(page, locator_type, locator_val)
    wait_timeout = int(action_params.get("timeout_ms") or step_timeout)
    log(f"Waiting for element '{locator_val}' to reach state '{condition}' (timeout: {wait_timeout}ms)...")
    loc.wait_for(state=condition, timeout=wait_timeout)
    return f"Element '{locator_val}' is {condition}", condition


# =====================================================================
# Main Execution Runner
# =====================================================================

def run_generic_scenario(
    db: Session,
    run_uuid: uuid.UUID,
    project: dict[str, Any],
    scenario: dict[str, Any],
    decrypted_credentials: dict[str, str] | None = None,
    dataset_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute a generic test scenario or dynamic workflow step-by-step using Playwright.
    Records step-by-step execution results, screenshots, videos, and logs.
    """
    project_uuid = project["id"]
    project_ext_id = project["external_id"]
    run_id_str = str(run_uuid)
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

    log(f"Starting execution for: '{scenario.get('name', 'Workflow')}' (Run ID: {run_uuid})")
    log(f"Target Application: '{project.get('name', 'Application')}' at {base_url}")
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
        # Launch browser with stealth flags and chrome channel to support enterprise WAFs (Akamai, Cloudflare)
        browser_type = getattr(pw, browser_name, pw.chromium)
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        launch_kwargs: dict[str, Any] = {
            "headless": is_headless,
            "args": launch_args,
        }
        if browser_name == "chromium":
            try:
                browser: Browser = browser_type.launch(**launch_kwargs, channel="chrome")
            except Exception:
                browser = browser_type.launch(**launch_kwargs)
        else:
            browser = browser_type.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {
            "base_url": base_url if base_url else None,
            "viewport": {"width": 1440, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "ignore_https_errors": True,
        }
        if capture_video:
            context_kwargs["record_video_dir"] = str(temp_video_dir)
            context_kwargs["record_video_size"] = {"width": 1440, "height": 900}

        context: BrowserContext = browser.new_context(**context_kwargs)
        page: Page = context.new_page()

        active_browser_sessions[run_id_str] = {
            "browser": browser,
            "context": context,
            "page": page,
            "cancelled": False,
        }

        for step in steps:
            if active_browser_sessions.get(run_id_str, {}).get("cancelled"):
                log("[CANCELLED] Execution stopped by user request.")
                execution_aborted = True
                overall_status = "cancelled"
                break

            step_order = step.get("step_order", 1)
            raw_action_type = (step.get("action_type") or "").strip().lower()
            locator_type = step.get("locator_type")
            locator_val_raw = step.get("locator_value") or ""
            locator_val = interpolate_variables(locator_val_raw, interp_context)
            action_params_raw = step.get("action_params") or {}
            step_desc = step.get("description") or f"Step {step_order}: {raw_action_type}"
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
                    action_type=raw_action_type,
                    description=step_desc,
                    status="skipped",
                    duration_ms=0,
                )
                skipped_count += 1
                continue

            log(f"[RUNNING] Step {step_order}: {step_desc} (action: {raw_action_type})")
            t_start = time.perf_counter()
            step_status = "passed"
            error_message = None
            actual_val = None
            expected_val = str(action_params.get("value") or action_params.get("text") or action_params.get("expected") or "")
            screenshot_art_id = None

            try:
                # Dispatch action to modular handlers
                if raw_action_type in ("open_app", "open_application"):
                    actual_val, expected_val = handle_open_app(
                        page, base_url, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("login", "perform_login"):
                    actual_val, expected_val = handle_login(
                        page, base_url, interp_context, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("navigate", "open_page"):
                    actual_val, expected_val = handle_navigate(
                        page, base_url, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("fill_input", "fill", "type", "enter_text"):
                    actual_val, expected_val = handle_fill_input(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("click_element", "click"):
                    actual_val, expected_val = handle_click_element(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("select_option", "select"):
                    actual_val, expected_val = handle_select_option(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("verify_element", "verify"):
                    actual_val, expected_val = handle_verify_element(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("wait_for_element", "wait"):
                    actual_val, expected_val = handle_wait_for_element(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                # Legacy Action Aliases
                elif raw_action_type == "assert_visible":
                    p = dict(action_params, verify_type="visible")
                    actual_val, expected_val = handle_verify_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "assert_hidden":
                    p = dict(action_params, verify_type="hidden")
                    actual_val, expected_val = handle_verify_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "assert_text":
                    p = dict(action_params, verify_type="contains_text", expected=expected_val)
                    actual_val, expected_val = handle_verify_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "assert_value":
                    p = dict(action_params, verify_type="input_value", expected=expected_val)
                    actual_val, expected_val = handle_verify_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "assert_title":
                    p = dict(action_params, verify_type="page_title", expected=expected_val)
                    actual_val, expected_val = handle_verify_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "assert_url":
                    p = dict(action_params, verify_type="url_contains", expected=expected_val)
                    actual_val, expected_val = handle_verify_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "wait_for_selector":
                    p = dict(action_params, condition="visible")
                    actual_val, expected_val = handle_wait_for_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "wait_for_timeout":
                    p = dict(action_params, condition="duration")
                    actual_val, expected_val = handle_wait_for_element(page, p, locator_type, locator_val, step_timeout, log)

                elif raw_action_type == "wait_for_navigation":
                    page.wait_for_load_state(action_params.get("state", "load"), timeout=step_timeout)
                    actual_val = "Page load state reached"

                elif raw_action_type == "press_key":
                    key = action_params.get("key", "Enter")
                    if locator_val:
                        loc = resolve_locator_safely(page, locator_type, locator_val)
                        loc.press(key, timeout=step_timeout)
                    else:
                        page.keyboard.press(key)
                    actual_val = f"Pressed key '{key}'"

                elif raw_action_type == "check":
                    loc = resolve_locator_safely(page, locator_type, locator_val)
                    loc.check(timeout=step_timeout)
                    actual_val = f"Checked checkbox '{locator_val}'"

                elif raw_action_type == "uncheck":
                    loc = resolve_locator_safely(page, locator_type, locator_val)
                    loc.uncheck(timeout=step_timeout)
                    actual_val = f"Unchecked checkbox '{locator_val}'"

                elif raw_action_type == "hover":
                    loc = resolve_locator_safely(page, locator_type, locator_val)
                    loc.hover(timeout=step_timeout)
                    actual_val = f"Hovered over '{locator_val}'"

                elif raw_action_type == "clear":
                    loc = resolve_locator_safely(page, locator_type, locator_val)
                    loc.clear(timeout=step_timeout)
                    actual_val = f"Cleared input '{locator_val}'"

                elif raw_action_type == "capture_screenshot":
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
                    actual_val = f"Screenshot saved to {shot_name}"

                else:
                    raise ValueError(f"Unsupported action_type: '{raw_action_type}'")

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
                action_type=raw_action_type,
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

        # Teardown browser
        try:
            page.close()
            context.close()
            browser.close()
        except Exception as close_err:
            log(f"Error during browser teardown: {close_err}")
        finally:
            active_browser_sessions.pop(run_id_str, None)

    # Process recorded video if enabled
    if capture_video and temp_video_dir.exists():
        video_files = list(temp_video_dir.glob("*.webm"))
        if video_files:
            target_video_file = run_artifact_dir / "recording.webm"
            try:
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
    if overall_status == "cancelled":
        exit_code = 130
        summary["error"] = "Run cancelled by user"
    else:
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
    workflow_label = scenario.get("name") or "Dynamic Workflow"
    db_service.save_test_results(
        db,
        run_uuid,
        [
            {
                "name": f"Workflow: {workflow_label}",
                "status": overall_status,
                "duration": sum(s.get("duration_ms", 0) for s in steps) / 1000.0,
                "error": f"{failed_count} step(s) failed." if failed_count > 0 else None,
            }
        ],
    )

    log(f"Workflow execution completed with status: {overall_status.upper()}")
    log(f"Summary: {passed_count}/{total_steps} passed, {failed_count} failed, {skipped_count} skipped.")

    return {
        "run_id": str(run_uuid),
        "status": overall_status,
        "summary": summary,
        "exit_code": exit_code,
    }
