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
import sys
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

PROJECT_ROOT = Path(__file__).resolve().parents[3] if "dashboard" in Path(__file__).resolve().parts else Path(__file__).resolve().parents[2]
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"


def bring_browser_to_front_windows(browser_type: str = "", page_title: str = ""):
    """Brings the interactive Playwright browser window to the foreground on Windows desktop."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32

        keywords = ["chrome", "chromium", "firefox", "edge", "msedge", "webkit", "veriqon", "timesheet", "oracle", "sign in", "hcm"]
        if browser_type:
            keywords.append(browser_type.lower())
        if page_title:
            clean_t = page_title.strip().lower()
            if len(clean_t) > 3:
                keywords.append(clean_t[:25])

        target_hwnds = []

        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    for kw in keywords:
                        if kw in title:
                            target_hwnds.append(hwnd)
                            break
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        for hwnd in target_hwnds:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            if hasattr(user32, "SwitchToThisWindow"):
                user32.SwitchToThisWindow(hwnd, True)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def update_live_browser_hud(page: Page, step_num: int, total_steps: int, action_name: str, desc: str, element_locator: Locator | None = None):
    """
    Renders an in-browser live progress HUD badge at top of the page so the user
    can visually watch execution progress in real-time on screen.
    Uses closed shadow DOM and data attributes so Playwright locators never pierce or match HUD text.
    """
    try:
        clean_text = f"Step {step_num}/{total_steps}: {desc[:65]}"
        js_code = """
        (text) => {
            // Remove legacy HUD elements if present
            const old = document.getElementById('__veriqon_live_hud');
            if (old) old.remove();

            let host = document.getElementById('__veriqon_live_hud_host');
            if (!host) {
                host = document.createElement('div');
                host.id = '__veriqon_live_hud_host';
                host.setAttribute('aria-hidden', 'true');
                host.setAttribute('data-playwright-skip', 'true');
                host.style.cssText = 'all:initial;position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:2147483647;pointer-events:none;';
                const shadow = host.attachShadow({ mode: 'open' });
                const style = document.createElement('style');
                style.textContent = `
                    #hud_badge {
                        background: rgba(15,23,42,0.94);
                        color: #ffffff;
                        padding: 8px 20px;
                        border-radius: 9999px;
                        font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
                        font-size: 13px;
                        font-weight: 600;
                        box-shadow: 0 8px 30px rgba(0,0,0,0.4),0 0 0 1px rgba(255,255,255,0.18);
                        backdrop-filter: blur(8px);
                        display: flex;
                        align-items: center;
                        gap: 10px;
                        pointer-events: none;
                    }
                    #hud_dot {
                        display: inline-block;
                        width: 9px;
                        height: 9px;
                        border-radius: 50%;
                        background: #10b981;
                        box-shadow: 0 0 10px #10b981;
                        flex-shrink: 0;
                    }
                    #hud_text::after {
                        content: attr(data-step-title);
                        letter-spacing: 0.3px;
                    }
                `;
                const badge = document.createElement('div');
                badge.id = 'hud_badge';
                const dot = document.createElement('span');
                dot.id = 'hud_dot';
                const txt = document.createElement('span');
                txt.id = 'hud_text';
                badge.appendChild(dot);
                badge.appendChild(txt);
                shadow.appendChild(style);
                shadow.appendChild(badge);
                document.documentElement.appendChild(host);
            }
            const txt = host.shadowRoot ? host.shadowRoot.getElementById('hud_text') : null;
            if (txt) {
                txt.setAttribute('data-step-title', text);
            }
        }
        """
        page.evaluate(js_code, clean_text)
    except Exception:
        pass


def wait_for_oracle_adf_ready(page: Page, timeout_ms: int = 10000, log: Callable[[str], None] | None = None) -> None:
    """
    Ensures Oracle ADF partial page refresh (PPR) requests and blocking glass panes
    (such as #_FOd1, .AFBlockingGlassPane) are fully dismissed before interacting with elements.
    """
    try:
        is_adf = page.evaluate("() => typeof window.AdfPage !== 'undefined' && typeof window.AdfPage.PAGE !== 'undefined'")
        if is_adf:
            t0 = time.perf_counter()
            page.wait_for_function(
                "() => !window.AdfPage || !window.AdfPage.PAGE || window.AdfPage.PAGE.isSynchronizedWithServer()",
                timeout=timeout_ms
            )
            page.wait_for_function(
                """() => {
                    const glasses = document.querySelectorAll('div[id*="_FOd1"], div.AFBlockingGlassPane, div[id*="glassPane"]');
                    for (const g of glasses) {
                        const style = window.getComputedStyle(g);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && g.offsetParent !== null) {
                            return false;
                        }
                    }
                    return true;
                }""",
                timeout=timeout_ms
            )
            elapsed = int((time.perf_counter() - t0) * 1000)
            if elapsed > 150 and log:
                log(f"Oracle ADF synchronized and glass pane cleared ({elapsed}ms).")
    except Exception:
        pass


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


def normalize_app_url(url: str) -> str:
    """
    Normalizes application URLs to their valid entry points:
    Oracle Identity Cloud Service (IDCS):
    A naked GET on /ui/v1/signin without OAuth query parameters displays:
    'You cannot bookmark and access the /signin URL directly.'
    Converting it to /ui/v1/myconsole ensures Oracle IDCS generates the OAuth
    session parameters and renders the Sign-In page with username & password fields.
    """
    if not url:
        return url
    u = url.strip()
    if "identity.oraclecloud.com" in u:
        if u.endswith("/ui/v1/signin"):
            u = u[:-len("/ui/v1/signin")] + "/ui/v1/myconsole"
        elif u.endswith("/signin"):
            u = u[:-len("/signin")] + "/ui/v1/myconsole"
        elif "/ui/v1/signin?" not in u and not u.endswith("/ui/v1/myconsole"):
            if u.endswith("/"):
                u = u + "ui/v1/myconsole"
            elif u.endswith(".oraclecloud.com"):
                u = u + "/ui/v1/myconsole"
    return u


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
        # Exclude veriqon internal HUD / badges from matching
        filtered = loc.filter(has_not=loc.page.locator("#__veriqon_live_hud_host, #__veriqon_live_hud, [data-playwright-skip]"))
        if filtered.count() > 0:
            loc = filtered
    except Exception:
        pass
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
        if l_val.startswith("#") and any(c in l_val for c in ("|", ":", "[", "]", "$")):
            clean_id = l_val.lstrip("#").replace('\\', '\\\\').replace('"', '\\"')
            raw_loc = page.locator(f'[id="{clean_id}"]')
        else:
            raw_loc = page.locator(l_val)
        return check_ambiguity(raw_loc, desc)

    # 6. XPath
    elif l_type == "xpath":
        raw_loc = page.locator(f"xpath={l_val}" if not l_val.startswith("xpath=") else l_val)
        return check_ambiguity(raw_loc, desc)

    # 7. Common HTML Attributes
    elif l_type == "id":
        clean_id = l_val.lstrip("#").replace(chr(92), chr(92)+chr(92)).replace(chr(34), chr(92)+chr(34))
        raw_loc = page.locator(f'[id="{clean_id}"], [id$=":{clean_id}"], [id$="_{clean_id}"], [id*="{clean_id}"]')
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

        # Check if clearly CSS ID
        if l_val.startswith("#"):
            clean_id = l_val.lstrip("#").replace('\\', '\\\\').replace('"', '\\"')
            raw_loc = page.locator(f'[id="{clean_id}"]')
            return check_ambiguity(raw_loc, desc)

        # Check if clearly class or attribute selector
        if (l_val.startswith(".") and " " not in l_val) or \
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

            # In APEX & component libraries, tree items use .a-TreeView-label or text
            try:
                tree_label = page.locator(f".a-TreeView-label:has-text('{l_val}')")
                if tree_label.count() > 0:
                    return check_ambiguity(tree_label, desc)
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

        # Try Oracle ADF / Enterprise Form Field by Label (matches input/combobox in the same table row or next to label)
        try:
            adf_field_selectors = [
                f"//tr[contains(., '{l_val}')]//input",
                f"//tr[contains(., '{l_val}')]//*[@role='combobox']",
                f"//tr[contains(., '{l_val}')]//select",
                f"//label[contains(text(), '{l_val}')]/following::input[1]",
                f"//td[contains(text(), '{l_val}')]/following::input[1]",
                f"//label[contains(., '{l_val}')]/..//input",
                f"//div[contains(@class, 'x19') or contains(@class, 'form')][contains(., '{l_val}')]//input",
            ]
            for sel in adf_field_selectors:
                cand = page.locator(sel).filter(has_not=page.locator("#__veriqon_live_hud_host, #__veriqon_live_hud, [data-playwright-skip]"))
                if cand.count() > 0 and cand.first.is_visible():
                    return check_ambiguity(cand, desc)
        except Exception:
            pass

        # Try Visible Text (exact and substring, ignoring HUD elements)
        if role_hint != "textbox":
            try:
                text_candidate = page.get_by_text(l_val, exact=True).filter(has_not=page.locator("#__veriqon_live_hud_host, #__veriqon_live_hud, [data-playwright-skip]"))
                if text_candidate.count() > 0:
                    return check_ambiguity(text_candidate, desc)
            except Exception:
                pass

            try:
                text_candidate = page.get_by_text(l_val, exact=False).filter(has_not=page.locator("#__veriqon_live_hud_host, #__veriqon_live_hud, [data-playwright-skip]"))
                if text_candidate.count() > 0:
                    return check_ambiguity(text_candidate, desc)
            except Exception:
                pass
        else:
            try:
                input_by_text = page.locator(
                    f"//tr[contains(., '{l_val}')]//input | "
                    f"//label[contains(., '{l_val}')]/following::input[1] | "
                    f"//td[contains(., '{l_val}')]/following::input[1] | "
                    f"//div[contains(@class, 'x19') or contains(@class, 'form')][contains(., '{l_val}')]//input"
                ).filter(has_not=page.locator("#__veriqon_live_hud_host, #__veriqon_live_hud, [data-playwright-skip]"))
                if input_by_text.count() > 0 and input_by_text.first.is_visible():
                    return check_ambiguity(input_by_text, desc)
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

        # Check if ID pattern (e.g. pt1:_UIScil1u, itemNode_..., groupNode_...) or ID in DOM
        clean_id = l_val.lstrip("#").replace(chr(92), chr(92)+chr(92)).replace(chr(34), chr(92)+chr(34))
        is_id_pattern = bool(
            re.match(r"^[a-zA-Z0-9_\-:]+$", clean_id)
            and ("_" in clean_id or ":" in clean_id or "node" in clean_id.lower() or "btn" in clean_id.lower() or "item" in clean_id.lower())
        )
        if is_id_pattern:
            id_loc = page.locator(f'[id="{clean_id}"], [id$=":{clean_id}"], [id$="_{clean_id}"], [id*="{clean_id}"]')
            return check_ambiguity(id_loc, desc)
        try:
            id_candidate = page.locator(f'[id="{clean_id}"]')
            if id_candidate.count() > 0:
                return check_ambiguity(id_candidate, desc)
        except Exception:
            pass

        # Fallback to standard Playwright locator
        raw_loc = page.locator(l_val)
        if raw_loc.count() == 0 and len(page.frames) > 1:
            for frame in page.frames[1:]:
                try:
                    f_cand = frame.locator(l_val)
                    if f_cand.count() > 0:
                        return check_ambiguity(f_cand, desc)
                except Exception:
                    pass
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
    # 1. Check if toggle button explicitly indicates collapsed state
    for sel in nav_toggle_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                aria_exp = btn.get_attribute("aria-expanded")
                if aria_exp == "false":
                    if log:
                        log(f"Navigation menu toggle is collapsed (aria-expanded='false'). Expanding via {sel}...")
                    btn.click()
                    page.wait_for_timeout(600)
                    return True
                elif aria_exp == "true":
                    # Explicitly already expanded
                    return False
        except Exception:
            continue

    # 2. Check if tree container is collapsed by class or width
    try:
        is_collapsed = page.evaluate("""() => {
            const body = document.body;
            if (body && (body.classList.contains('apex-side-nav-collapsed') || body.classList.contains('js-navCollapsed'))) return true;
            const tree = document.querySelector('#t_TreeNav, .a-TreeView, .t-Body-nav');
            if (tree) {
                const rect = tree.getBoundingClientRect();
                if (rect.width <= 10 || tree.classList.contains('js-defaultCollapsed') || tree.getAttribute('aria-hidden') === 'true') {
                    return true;
                }
            }
            return false;
        }""")
        if is_collapsed:
            for sel in nav_toggle_selectors:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    if log:
                        log(f"Navigation container is collapsed. Expanding via {sel}...")
                    btn.click()
                    page.wait_for_timeout(600)
                    return True
    except Exception:
        pass

    return False


def robust_click(
    page: Page,
    locator_type: str | None,
    locator_val: str,
    role_hint: str | None = None,
    timeout: int = 10000,
    log: Callable[[str], None] | None = None,
) -> None:
    """
    High-performance resilient click operation for modern dynamic web applications:
      1. Immediate fast-path locator check (< 100ms).
      2. High-speed DOM search across accessible roles and treeview items (< 20ms).
      3. Automatic navigation expansion only if required.
      4. Targeted fallback to force-click or JS click without excessive waiting.
    """
    wait_for_oracle_adf_ready(page, timeout_ms=4000, log=log)
    if not locator_val:
        raise ValueError("Locator value cannot be empty for click action.")

    clean_target = locator_val.strip()

    # Fast-Path 1: Direct locator resolution & immediate click if element exists
    try:
        loc = resolve_locator_safely(page, locator_type, clean_target, role_hint=role_hint)
        if loc.count() > 0 and loc.first.is_visible():
            loc.first.click(timeout=3000)
            return
    except Exception as exc:
        if log:
            log(f"[DEBUG] Immediate locator check failed: {exc}")

    # Fast-Path 2: Try expanding navigation menu if target might be inside a collapsed drawer
    try:
        if ensure_navigation_expanded(page, log=log):
            loc = resolve_locator_safely(page, locator_type, clean_target, role_hint=role_hint)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=3000)
                return
    except Exception:
        pass

    # Fast-Path 3: High-speed in-browser DOM text matching (resolves APEX treeitems & SPAs in < 20ms)
    try:
        clicked = page.evaluate("""(targetText) => {
            const idEl = document.getElementById(targetText) || document.querySelector(`[id*="${targetText}"]`);
            if (idEl && idEl.offsetParent !== null) {
                idEl.click();
                return true;
            }
            const clean = targetText.trim().toLowerCase();
            const elements = Array.from(document.querySelectorAll(
                '.a-TreeView-label, .a-TreeView-content, [role="treeitem"], [role="menuitem"], [role="tab"], a, button, li, span'
            ));
            for (const el of elements) {
                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (txt === clean && el.offsetParent !== null) {
                    el.click();
                    return true;
                }
            }
            for (const el of elements) {
                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (txt.includes(clean) && el.offsetParent !== null) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""", clean_target)
        if clicked:
            if log:
                log(f"Successfully clicked '{clean_target}' via fast interactive DOM resolver.")
            page.wait_for_timeout(400)
            return
    except Exception as exc:
        if log:
            log(f"[DEBUG] Fast DOM resolver failed: {exc}")

    # Fallback 1: Standard wait-for-visible with tight timeout
    last_error = None
    try:
        loc = resolve_locator_safely(page, locator_type, clean_target, role_hint=role_hint)
        click_timeout = max(timeout, 12000)
        loc.first.wait_for(state="visible", timeout=click_timeout)
        loc.first.click(timeout=min(click_timeout, 8000))
        return
    except Exception as exc:
        last_error = exc

    # Fallback 2: Force click with 2s timeout
    try:
        loc = resolve_locator_safely(page, locator_type, clean_target, role_hint=role_hint)
        loc.first.click(force=True, timeout=2000)
        return
    except Exception as exc:
        last_error = exc

    # Fallback 3: JavaScript direct element click
    try:
        loc = resolve_locator_safely(page, locator_type, clean_target, role_hint=role_hint)
        loc.first.wait_for(state="attached", timeout=min(click_timeout, 5000))
        loc.first.evaluate("el => el.click()", timeout=3000)
        return
    except Exception as exc:
        last_error = exc

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
    # High-speed navigation with resilient wait for enterprise redirects (Oracle HCM / APEX)
    page.goto(target, wait_until="domcontentloaded", timeout=max(step_timeout, 45000))
    try:
        page.wait_for_load_state("load", timeout=10000)
    except Exception:
        pass
    # No forced delay; user can configure explicit Wait action as needed
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

    # 1. Identify Username field with resilient polling for slow enterprise redirects
    user_loc = None
    custom_user = action_params.get("username_locator") or (locator_val if locator_type in ("label", "id", "name", "css", "xpath") else None)
    u_type = action_params.get("username_locator_type") or locator_type

    username_attempts = [
        lambda: page.locator('[id="idcs-signin-basic-signin-form-username|input"]').first,
        lambda: page.locator("input[id*='signin-form-username']").first,
        lambda: page.get_by_role("textbox", name="Username"),
        lambda: page.get_by_role("textbox", name="User ID"),
        lambda: page.get_by_role("textbox", name="Email"),
        lambda: page.get_by_label(re.compile("username|email|user id", re.I)),
        lambda: page.get_by_placeholder(re.compile("username|email", re.I)),
        lambda: page.locator("input[name='username']").first,
        lambda: page.locator("#P9999_USERNAME").first,
        lambda: page.locator("#username").first,
        lambda: page.locator("input[type='email']").first,
    ]

    username_deadline = time.time() + max(step_timeout / 1000, 35)
    while time.time() < username_deadline:
        if custom_user:
            try:
                candidate = resolve_locator_safely(page, u_type, custom_user, role_hint="textbox")
                if candidate.count() > 0 and candidate.is_visible():
                    user_loc = candidate
                    break
            except Exception:
                pass
        else:
            for attempt in username_attempts:
                try:
                    candidate = attempt()
                    if candidate.count() > 0 and candidate.is_visible():
                        user_loc = candidate
                        break
                except Exception:
                    continue
        if user_loc:
            break
        page.wait_for_timeout(500)

    if not user_loc:
        raise ValueError("Could not automatically locate the Username field. Please specify a username locator in the action settings.")

    # Fill username
    log(f"Entering username for account '{user_val}' into login form...")
    user_loc.fill(user_val, timeout=step_timeout)

    # Check for Multi-Step Login (e.g. Oracle Cloud IDCS, Google, Okta, Azure AD)
    # where the password field is hidden until "Next" / "Continue" is clicked
    next_btn = None
    for next_attempt in [
        lambda: page.locator("#idcs-signin-basic-signin-form-submit").first,
        lambda: page.locator("button[id*='signin-form-submit']").first,
        lambda: page.get_by_role("button", name=re.compile(r"^(next|continue)$", re.I)),
        lambda: page.locator("button:has-text('Next'), button:has-text('Continue')").first,
    ]:
        try:
            cand = next_attempt()
            if cand.count() > 0 and cand.is_visible():
                next_btn = cand
                break
        except Exception:
            pass

    # Check if password field is currently visible on the page
    pass_visible = False
    custom_pass = action_params.get("password_locator")
    if custom_pass:
        try:
            cand_p = resolve_locator_safely(page, action_params.get("password_locator_type"), custom_pass, role_hint="textbox")
            pass_visible = cand_p.count() > 0 and cand_p.is_visible()
        except Exception:
            pass
    else:
        try:
            pass_cand = page.locator("input[type='password'], [id*='password']").first
            pass_visible = pass_cand.count() > 0 and pass_cand.is_visible()
        except Exception:
            pass

    # If password is NOT yet visible and a Next button exists, click Next first
    if not pass_visible and next_btn:
        log("Detected multi-step login. Submitting username via 'Next' button...")
        next_btn.click(timeout=step_timeout)
        page.wait_for_timeout(1500)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    # 2. Identify Password field with resilient polling
    pass_loc = None
    pass_attempts = [
        lambda: page.locator('[id="idcs-signin-basic-signin-form-password|input"]').first,
        lambda: page.locator("input[id*='signin-form-password']").first,
        lambda: page.get_by_role("textbox", name="Password"),
        lambda: page.get_by_label(re.compile("password", re.I)),
        lambda: page.locator("input[type='password']").first,
        lambda: page.locator("#P9999_PASSWORD").first,
        lambda: page.locator("#password").first,
        lambda: page.locator("input[name='password']").first,
    ]

    pass_deadline = time.time() + max(step_timeout / 1000, 30)
    while time.time() < pass_deadline:
        if custom_pass:
            try:
                candidate = resolve_locator_safely(page, action_params.get("password_locator_type"), custom_pass, role_hint="textbox")
                if candidate.count() > 0 and candidate.is_visible():
                    pass_loc = candidate
                    break
            except Exception:
                pass
        else:
            for attempt in pass_attempts:
                try:
                    candidate = attempt()
                    if candidate.count() > 0 and candidate.is_visible():
                        pass_loc = candidate
                        break
                except Exception:
                    continue
        if pass_loc:
            break
        page.wait_for_timeout(500)

    if not pass_loc:
        raise ValueError("Could not automatically locate the Password field. Please specify a password locator in the action settings.")

    # Fill password
    log("Entering encrypted vault password into password field...")
    try:
        pass_loc.wait_for(state="visible", timeout=step_timeout)
    except Exception:
        pass
    pass_loc.fill(pass_val, timeout=step_timeout)

    # 3. Identify Submit / Sign In button
    btn_loc = None
    custom_btn = action_params.get("submit_locator")
    if custom_btn:
        btn_loc = resolve_locator_safely(page, action_params.get("submit_locator_type"), custom_btn, role_hint="button")
    else:
        btn_attempts = [
            lambda: page.locator("#idcs-signin-basic-signin-form-submit").first,
            lambda: page.get_by_role("button", name="Sign In"),
            lambda: page.get_by_role("button", name="Sign in"),
            lambda: page.get_by_role("button", name="Log In"),
            lambda: page.get_by_role("button", name="Login"),
            lambda: page.locator("button:has-text('Sign In')").first,
            lambda: page.locator("button:has-text('Sign in')").first,
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

    log("Submitting login form...")
    try:
        # Check for inner native button if btn_loc is a web component wrapper
        inner_btn = btn_loc.locator("button, input[type='submit']").first
        if inner_btn.count() > 0 and inner_btn.is_visible():
            inner_btn.click(timeout=step_timeout)
        else:
            btn_loc.click(timeout=step_timeout)
    except Exception as exc:
        log(f"Direct button click notice: {exc}. Attempting force-click or Enter key...")
        try:
            btn_loc.click(force=True, timeout=5000)
        except Exception:
            pass

    # Resilient submit trigger: Also press Enter on the password field to guarantee form submission
    try:
        page.wait_for_timeout(300)
        if "/signin" in page.url.lower() or "idcs" in page.url.lower() or page.locator("input[type='password']:visible").count() > 0:
            pass_loc.press("Enter")
    except Exception:
        pass

    log("Waiting for post-login page load...")

    # A. Wait for URL redirect away from login page OR arrival of dashboard/in-app elements
    initial_login_url = page.url
    try:
        page.wait_for_function(
            """(initUrl) => {
                const cur = window.location.href;
                // 1. If in-app dashboard / header / navigator elements are visible, login succeeded!
                const appHeader = document.querySelector('header, nav, [role="navigation"], #pt1, [id*="UIScil"], .fuse-home, #t_TreeNav, .app-header, main, [role="main"]');
                if (appHeader && appHeader.offsetParent !== null) return true;

                // 2. If password input and submit buttons are gone from the page
                const passEl = document.querySelector('input[type="password"]');
                const submitEl = document.querySelector('#idcs-signin-basic-signin-form-submit, button[type="submit"]');
                const passGone = !passEl || passEl.offsetParent === null;
                const submitGone = !submitEl || submitEl.offsetParent === null;
                if (passGone && submitGone && cur !== initUrl) return true;

                // 3. If URL changed away from login/signin/idcs domain
                const isStillLoginUrl = cur === initUrl || cur.includes('/signin') || cur.includes('/login') || cur.includes('identity.oraclecloud.com/ui');
                if (!isStillLoginUrl) return true;

                // 4. If error alert is displayed, return true immediately so error check can report it
                const errAlert = document.querySelector('.oj-message-error, .oj-message-detail, [role="alert"], .alert-danger, .error-msg');
                if (errAlert && errAlert.offsetParent !== null) return true;

                return false;
            }""",
            arg=initial_login_url,
            timeout=20000,
        )
    except Exception as exc:
        log(f"Login redirect transition note: {exc}")

    # B. Check if login failed with error message on page (e.g. invalid credentials)
    try:
        err_msg = page.evaluate("""() => {
            const errEl = document.querySelector('.oj-message-error, .oj-message-detail, [role="alert"], .alert-danger, .error-msg, .app-alert');
            if (errEl && errEl.offsetParent !== null) {
                const txt = errEl.innerText || errEl.textContent || '';
                return txt.trim();
            }
            return null;
        }""")
        if err_msg and any(w in err_msg.lower() for w in ("invalid", "incorrect", "denied", "failed", "unsuccessful")):
            raise ValueError(f"Login authentication failed: {err_msg}")
    except ValueError:
        raise
    except Exception:
        pass

    # C. High-speed destination page load (skip slow networkidle / load event)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=6000)
    except Exception:
        pass

    # D. Quick single non-blocking check for visible spinner
    try:
        spin = page.locator(".oj-progress-circle:visible, .loading-overlay:visible, .splash-screen:visible, #loading-spinner:visible").first
        if spin.count() > 0 and spin.is_visible():
            spin.wait_for(state="hidden", timeout=1200)
    except Exception:
        pass

    # E. Settle delay (honors explicit wait_after_ms if configured by user):
    user_wait = action_params.get("wait_after_ms")
    if user_wait is not None and int(user_wait) > 0:
        post_login_duration = int(user_wait)
        log(f"Post-login wait ({post_login_duration}ms)...")
        page.wait_for_timeout(post_login_duration)

    # F. Auto-expand navigation drawer ONLY if an Oracle APEX tree nav is present
    try:
        if page.locator("#t_TreeNav").count() > 0:
            ensure_navigation_expanded(page, log=log)
    except Exception:
        pass

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
    raw_target = action_params.get("path") or action_params.get("url") or action_params.get("target") or locator_val or ""
    raw_target = raw_target.strip()

    is_explicit_click = nav_method == "click" or locator_type in ("id", "css", "xpath", "name", "role", "label", "text", "testid")
    is_path = (
        not is_explicit_click
        and (
            nav_method == "path"
            or raw_target.startswith(("/", "http://", "https://", "./", "../"))
            or "?" in raw_target
            or raw_target.endswith((".html", ".jsp", ".aspx", ".php"))
        )
    )

    if not is_path:
        target_name = action_params.get("element_friendly_name") or raw_target
        log(f"Navigating by clicking UI link/menu item '{target_name}' (locator: {locator_type or 'smart'}={raw_target})...")
        robust_click(page, locator_type, raw_target, role_hint="link", timeout=step_timeout, log=log)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=min(step_timeout, 8000))
        except Exception:
            pass
        return f"Navigated to '{target_name}'", raw_target
    else:
        clean_base = normalize_app_url(base_url) if base_url else ""
        path = raw_target or "/"
        if path.startswith(("http://", "https://", "file://", "about:", "data:")):
            target = normalize_app_url(path)
        elif path.startswith("/") and clean_base:
            target = normalize_app_url(f"{clean_base.rstrip('/')}{path}")
        elif clean_base:
            target = normalize_app_url(f"{clean_base.rstrip('/')}/{path}")
        else:
            target = normalize_app_url(path)

        log(f"Navigating to page path: {target}")
        page.goto(target, wait_until="domcontentloaded", timeout=max(step_timeout, 45000))
        try:
            page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
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
    wait_for_oracle_adf_ready(page, timeout_ms=6000, log=log)
    loc = resolve_locator_safely(page, locator_type, locator_val, role_hint="textbox")

    # If loc resolved to a label, td, or container, resolve to the associated <input> or <textarea>
    try:
        tag_name = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag_name not in ("input", "textarea") and not loc.evaluate("el => el.isContentEditable"):
            inner = loc.locator("input, textarea")
            if inner.count() > 0 and inner.first.is_visible():
                loc = inner.first
            else:
                parent_row = loc.locator("xpath=ancestor::tr[1]")
                if parent_row.count() > 0 and parent_row.locator("input, textarea").count() > 0:
                    loc = parent_row.locator("input, textarea").first
                else:
                    following_inp = loc.locator("xpath=following::input[1]")
                    if following_inp.count() > 0 and following_inp.first.is_visible():
                        loc = following_inp.first
                    else:
                        parent_div = loc.locator("xpath=ancestor::div[contains(@class, 'x19') or contains(@class, 'form')][1]")
                        if parent_div.count() > 0 and parent_div.locator("input, textarea").count() > 0:
                            loc = parent_div.locator("input, textarea").first
    except Exception:
        pass

    log(f"Filling input '{locator_val}' with value '{val}'...")
    clear_first = action_params.get("clear_first", True)
    try:
        if clear_first:
            loc.fill(val, timeout=step_timeout)
        else:
            loc.type(val, delay=int(action_params.get("delay", 20)), timeout=step_timeout)
    except Exception as fill_err:
        wait_for_oracle_adf_ready(page, timeout_ms=4000, log=log)
        # Fallback to direct JavaScript input set if Playwright strict editable check fails
        try:
            loc.evaluate("(el, v) => { el.focus(); el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }", val)
        except Exception:
            raise fill_err

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

    wait_for_oracle_adf_ready(page, timeout_ms=6000, log=log)
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
    Action 6: Select Option / Search & Select.
    Universally supports:
    1. Native HTML <select> dropdowns.
    2. Searchable inputs & comboboxes (types search query and clicks filtered option or hits Enter).
    3. Custom ARIA dropdown triggers (clicks trigger to open popup listbox, then selects matching item).
    """
    opt = (
        action_params.get("value")
        or action_params.get("label")
        or action_params.get("option")
        or action_params.get("text")
    )
    if opt is None or str(opt).strip() == "":
        raise ValueError("Must provide an option label or value to select.")

    opt_str = str(opt).strip()

    # Auto-remediation: Detect if locator_val is actually a navigation tile/link/button (e.g. Hire an Employee)
    is_nav_action = any(
        k in locator_val.lower()
        for k in ("hire an employee", "create employee", "new person", "submit", "next", "continue")
    )
    if is_nav_action:
        log(f"[AUTO-REMEDIATION] Target '{locator_val}' is a navigation tile/button, not a dropdown select. Executing click navigation...")
        robust_click(page, locator_type, locator_val, role_hint="button", timeout=step_timeout, log=log)
        wait_for_oracle_adf_ready(page, timeout_ms=8000, log=log)
        page.wait_for_timeout(1000)
        return f"Navigated via click on '{locator_val}'", locator_val

    wait_for_oracle_adf_ready(page, timeout_ms=8000, log=log)
    loc = resolve_locator_safely(page, locator_type, locator_val, role_hint="combobox")

    # If loc resolved to a container, table cell, or label, resolve to the associated input/combobox
    try:
        tag_chk = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag_chk in ("label", "td", "th", "span", "div"):
            inner = loc.locator("input, [role='combobox'], select, a[id*='lovIcon']")
            if inner.count() > 0 and inner.first.is_visible():
                loc = inner.first
            else:
                parent_row = loc.locator("xpath=ancestor::tr[1]")
                if parent_row.count() > 0 and parent_row.locator("input, [role='combobox'], select, a[id*='lovIcon']").count() > 0:
                    loc = parent_row.locator("input, [role='combobox'], select, a[id*='lovIcon']").first
                else:
                    following_inp = loc.locator("xpath=following::input[1]")
                    if following_inp.count() > 0 and following_inp.first.is_visible():
                        loc = following_inp.first
    except Exception:
        pass

    # 1. Check if the element itself or an internal child is a native <select>
    try:
        tag_name = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag_name == "select":
            log(f"Selecting option '{opt_str}' in native <select> '{locator_val}'...")
            try:
                loc.select_option(label=opt_str, timeout=min(step_timeout, 4000))
                return f"Selected '{opt_str}' in '{locator_val}'", opt_str
            except Exception:
                try:
                    loc.select_option(value=opt_str, timeout=min(step_timeout, 4000))
                    return f"Selected value '{opt_str}' in '{locator_val}'", opt_str
                except Exception:
                    loc.select_option(opt_str, timeout=min(step_timeout, 4000))
                    return f"Selected '{opt_str}' in '{locator_val}'", opt_str
        elif loc.locator("select").count() > 0:
            child_select = loc.locator("select").first
            log(f"Selecting option '{opt_str}' in child <select> of '{locator_val}'...")
            try:
                child_select.select_option(label=opt_str, timeout=min(step_timeout, 4000))
                return f"Selected '{opt_str}' in '{locator_val}'", opt_str
            except Exception:
                child_select.select_option(opt_str, timeout=min(step_timeout, 4000))
                return f"Selected '{opt_str}' in '{locator_val}'", opt_str
    except Exception:
        pass

    # 2. Modern Custom Dropdown / ARIA Combobox / Search-and-Select Handling
    log(f"Handling custom dropdown / search-and-select for '{locator_val}' with target option '{opt_str}'...")

    # Case A: Element is an input field (searchable combobox / LOV / autocomplete)
    is_input = False
    try:
        is_input = loc.evaluate("el => el.tagName.toLowerCase() === 'input' || el.getAttribute('role') === 'combobox'")
    except Exception:
        pass

    if is_input:
        log(f"Focusing and typing search query '{opt_str}' into combobox '{locator_val}'...")
        try:
            loc.click(timeout=min(step_timeout, 4000))
        except Exception:
            wait_for_oracle_adf_ready(page, timeout_ms=4000, log=log)
            try:
                loc.click(force=True, timeout=2000)
            except Exception:
                loc.evaluate("el => el.focus()")
        try:
            loc.fill(opt_str, timeout=step_timeout)
        except Exception:
            loc.press_sequentially(opt_str, timeout=step_timeout)

        page.wait_for_timeout(350)

        # Look for matching option in the popup listbox / dropdown menu
        option_clicked = False
        candidates = [
            page.locator(f'[role="option"]:has-text("{opt_str}")').first,
            page.locator(f'.oj-listbox-results li:has-text("{opt_str}")').first,
            page.locator(f'.select2-results__option:has-text("{opt_str}")').first,
            page.locator(f'.dropdown-menu :text-matches("{re.escape(opt_str)}", "i")').first,
            page.locator(f'.a-Icon-lov:has-text("{opt_str}")').first,
            page.locator(f'li[role="treeitem"]:has-text("{opt_str}")').first,
            page.locator(f'[role="listbox"] :text-matches("{re.escape(opt_str)}", "i")').first,
            page.get_by_role("option", name=opt_str).first,
            page.locator(f'text="{opt_str}"').first,
        ]

        for cand in candidates:
            try:
                if cand.count() > 0 and cand.is_visible():
                    cand.click(timeout=2000)
                    option_clicked = True
                    log(f"Clicked matching option element for '{opt_str}'.")
                    break
            except Exception:
                continue

        if not option_clicked:
            log(f"Confirming search-and-select with Enter key...")
            loc.press("Enter")
            wait_for_oracle_adf_ready(page, timeout_ms=4000, log=log)

        return f"Selected '{opt_str}' in combobox '{locator_val}'", opt_str

    # Case B: Element is a trigger button / dropdown container
    log(f"Clicking dropdown trigger '{locator_val}' to expand menu...")
    try:
        loc.click(timeout=min(step_timeout, 4000))
    except Exception:
        wait_for_oracle_adf_ready(page, timeout_ms=4000, log=log)
        try:
            loc.click(force=True, timeout=2000)
        except Exception:
            loc.evaluate("el => el.click()")
    page.wait_for_timeout(350)

    # Check if a popup search input appeared (e.g. Oracle APEX Popup LOV, Select2, Modal LOV)
    popup_search = page.locator('.ui-dialog input[type="text"], .a-PopupLOV-search, .select2-search__field, [role="dialog"] input[type="search"]').first
    try:
        if popup_search.count() > 0 and popup_search.is_visible():
            log(f"Popup search filter detected. Typing '{opt_str}'...")
            popup_search.fill(opt_str, timeout=3000)
            page.wait_for_timeout(350)
    except Exception:
        pass

    option_selectors = [
        page.get_by_role("option", name=opt_str).first,
        page.locator(f'[role="option"]:has-text("{opt_str}")').first,
        page.locator(f'.a-PopupLOV-results li:has-text("{opt_str}")').first,
        page.locator(f'.select2-results__option:has-text("{opt_str}")').first,
        page.locator(f'.dropdown-item:has-text("{opt_str}")').first,
        page.locator(f'.oj-listbox-results li:has-text("{opt_str}")').first,
        page.locator(f'ul li:has-text("{opt_str}")').first,
        page.locator(f'text="{opt_str}"').first,
    ]

    for cand in option_selectors:
        try:
            if cand.count() > 0 and cand.is_visible():
                cand.click(timeout=min(step_timeout, 4000))
                log(f"Successfully selected option '{opt_str}'.")
                return f"Selected '{opt_str}' in '{locator_val}'", opt_str
        except Exception:
            continue

    log(f"Selecting option '{opt_str}' via keyboard Enter...")
    page.keyboard.press("Enter")
    return f"Selected '{opt_str}' in '{locator_val}'", opt_str


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


def handle_wait(
    page: Page,
    action_params: dict[str, Any],
    locator_val: str,
    step_timeout: int,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """
    Action: Wait / Pause execution.
    Pauses execution for a user-specified duration (in seconds or ms).
    Supports numeric values, strings with units ('5s', '5000ms', '3 sec'),
    or action_params keys ('seconds', 'duration_ms', 'duration', 'timeout_ms', 'value').
    """
    raw_val = (
        action_params.get("seconds")
        or action_params.get("duration")
        or action_params.get("duration_ms")
        or action_params.get("timeout_ms")
        or action_params.get("value")
        or locator_val
        or 3
    )

    s = str(raw_val).strip().lower()
    ms: int = 3000
    ms_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", s)
    if ms_match:
        ms = int(float(ms_match.group(1)))
    else:
        num_match = re.search(r"(\d+(?:\.\d+)?)", s)
        if num_match:
            val = float(num_match.group(1))
            if "seconds" in action_params or "s" in s or val <= 60:
                ms = int(val * 1000)
            else:
                ms = int(val)
        else:
            ms = 3000

    ms = max(10, min(ms, 600000))
    sec = round(ms / 1000.0, 2)
    sec_display = int(sec) if sec == int(sec) else sec
    log(f"Pausing execution for {sec_display}s ({ms}ms)...")
    page.wait_for_timeout(ms)
    return f"Paused for {sec_display}s", f"{sec_display}s"


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
        return handle_wait(page, action_params, locator_val, step_timeout, log)

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
    base_url = normalize_app_url((project.get("base_url") or "").rstrip("/"))
    browser_name = (scenario.get("browser") or project.get("browser", "chromium")).lower()
    is_headless = scenario.get("headless") if scenario.get("headless") is not None else project.get("headless", True)
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
            clean_k = str(k).strip()
            interp_context[clean_k] = str(v)
            interp_context[clean_k.lower()] = str(v)
            interp_context[clean_k.lower().replace(" ", "_")] = str(v)
            interp_context[clean_k.lower().replace("_", " ")] = str(v)
        log(f"Loaded CSV input parameters ({len(dataset_row)} fields): {dataset_row}")

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
        if not is_headless:
            launch_args.extend([
                "--start-maximized",
                "--window-position=50,50",
                "--window-size=1440,900",
            ])
        launch_kwargs: dict[str, Any] = {
            "headless": is_headless,
            "args": launch_args,
        }
        if not is_headless:
            # Comfortable pace when live mode is active so user can clearly watch live execution on screen
            launch_kwargs["slow_mo"] = 150
        if browser_name in ("chromium", "chrome"):
            try:
                browser: Browser = browser_type.launch(**launch_kwargs, channel="chrome")
            except Exception:
                browser = browser_type.launch(**launch_kwargs)
        elif browser_name in ("msedge", "edge"):
            try:
                browser = browser_type.launch(**launch_kwargs, channel="msedge")
            except Exception:
                browser = browser_type.launch(**launch_kwargs)
        else:
            browser = browser_type.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {
            "base_url": base_url if base_url else None,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "ignore_https_errors": True,
        }
        if not is_headless and sys.platform == "win32" and browser_name in ("chromium", "chrome", "msedge", "edge"):
            context_kwargs["no_viewport"] = True
        else:
            context_kwargs["viewport"] = {"width": 1440, "height": 900}

        if capture_video:
            context_kwargs["record_video_dir"] = str(temp_video_dir)
            context_kwargs["record_video_size"] = {"width": 1440, "height": 900}

        context: BrowserContext = browser.new_context(**context_kwargs)
        # Mask navigator.webdriver to bypass enterprise WAFs (Akamai, Cloudflare)
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page: Page = context.new_page()
        if not is_headless:
            try:
                page.bring_to_front()
                bring_browser_to_front_windows(browser_name, project.get("name", ""))
            except Exception:
                pass

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
            step_on_fail = (step.get("on_fail") or failure_policy or "stop").lower()

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
            if not is_headless:
                try:
                    update_live_browser_hud(page, step_order, total_steps, raw_action_type, step_desc)
                    bring_browser_to_front_windows(browser_name, page.title())
                except Exception:
                    pass
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

                elif raw_action_type in ("select_option", "select", "choose", "search_and_select", "search_select", "combobox"):
                    actual_val, expected_val = handle_select_option(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("verify_element", "verify"):
                    actual_val, expected_val = handle_verify_element(
                        page, action_params, locator_type, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("wait", "pause", "sleep", "wait_for_timeout"):
                    actual_val, expected_val = handle_wait(
                        page, action_params, locator_val, step_timeout, log
                    )

                elif raw_action_type in ("wait_for_element", "wait_for_selector"):
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

                raw_wait_after = action_params.get("wait_after_ms")
                if raw_wait_after is None:
                    raw_sec = action_params.get("wait_after_seconds") or action_params.get("wait_seconds") or action_params.get("wait_s")
                    if raw_sec is not None:
                        raw_wait_after = float(raw_sec) * 1000
                try:
                    wait_ms = int(float(raw_wait_after or 0))
                except (ValueError, TypeError):
                    wait_ms = 0

                if wait_ms > 0:
                    log(f"Post-action wait: {wait_ms}ms ({round(wait_ms / 1000, 2)}s)")
                    page.wait_for_timeout(wait_ms)

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

                if step_on_fail == "stop":
                    execution_aborted = True
                    log("Per-step on_fail=stop. Aborting remaining steps.")
                elif step_on_fail == "continue":
                    log("Per-step on_fail=continue. Continuing to next step.")
                elif step_on_fail.startswith("retry:"):
                    log(f"Per-step on_fail={step_on_fail}. Marking failed and continuing.")
                else:
                    if failure_policy == "stop": execution_aborted = True

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

        # Guarantee final video frames are captured before browser teardown
        if capture_video:
            try:
                page.wait_for_timeout(600)
            except Exception:
                pass

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
