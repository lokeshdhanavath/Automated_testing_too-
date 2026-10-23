"""
Veriqon Element Inspector API
Provides real-time element discovery, visual inspection, and interactive element picking
for registered web applications using Playwright.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from app.database import get_db
from app import db_service, credentials_service
from app.scenario_engine import ensure_navigation_expanded, robust_click, resolve_locator_safely

logger = logging.getLogger("veriqon.inspector")

router = APIRouter(prefix="/api/inspector", tags=["Element Inspector"])

# Global session cache for active inspection sessions: project_id -> session dict
active_inspector_sessions: Dict[str, Dict[str, Any]] = {}

# Client-side DOM scanner script
DOM_SCANNER_SCRIPT = """() => {
    function getAssociatedLabel(el) {
        if (el.id) {
            try {
                const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (lbl && lbl.innerText) return lbl.innerText.trim();
            } catch (e) {}
        }
        const parentLabel = el.closest('label');
        if (parentLabel && parentLabel.innerText) {
            return parentLabel.innerText.replace(el.innerText || '', '').trim();
        }
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel.trim();
        const ariaLabelledBy = el.getAttribute('aria-labelledby');
        if (ariaLabelledBy) {
            try {
                const byEl = document.getElementById(ariaLabelledBy);
                if (byEl && byEl.innerText) return byEl.innerText.trim();
            } catch (e) {}
        }
        const title = el.getAttribute('title');
        if (title) return title.trim();
        return '';
    }

    function getElementCategory(el) {
        const tag = el.tagName.toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();

        if (tag === 'button' || role === 'button' || ['submit', 'button', 'reset'].includes(type)) {
            return 'button';
        }
        if (tag === 'a' || ['link', 'treeitem', 'menuitem', 'tab'].includes(role)) {
            return 'link';
        }
        if (tag === 'select' || role === 'combobox' || role === 'listbox') {
            return 'select';
        }
        if (tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'hidden', 'submit', 'button'].includes(type))) {
            return 'input';
        }
        if (type === 'checkbox' || role === 'checkbox') return 'checkbox';
        if (type === 'radio' || role === 'radio') return 'radio';
        return 'other';
    }

    const interactiveSelectors = [
        'button',
        'a[href]',
        'input:not([type="hidden"])',
        'select',
        'textarea',
        '[role="button"]',
        '[role="link"]',
        '[role="treeitem"]',
        '[role="menuitem"]',
        '[role="tab"]',
        '[role="checkbox"]',
        '[role="combobox"]',
        '.a-TreeView-label',
        '[data-action]'
    ].join(',');

    const elements = Array.from(document.querySelectorAll(interactiveSelectors));
    const results = [];
    const seenLocators = new Set();

    let counter = 1;
    for (const el of elements) {
        const rect = el.getBoundingClientRect();
        // Skip invisible or zero-size elements
        if (rect.width <= 0 || rect.height <= 0 || el.offsetParent === null) continue;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) continue;

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || (tag === 'button' ? 'button' : tag === 'a' ? 'link' : tag === 'input' ? 'textbox' : '');
        const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
        const label = getAssociatedLabel(el);
        const placeholder = el.getAttribute('placeholder') || '';
        const id = el.id || '';
        const name = el.getAttribute('name') || '';
        const type = el.getAttribute('type') || '';
        const category = getElementCategory(el);

        let accessibleName = label || text || placeholder || id || name;
        if (accessibleName.length > 50) accessibleName = accessibleName.substring(0, 50) + '...';

        let categoryPrefix = 'Element';
        if (category === 'button') categoryPrefix = 'Button';
        else if (category === 'link') categoryPrefix = role === 'treeitem' ? 'Menu Item' : 'Link';
        else if (category === 'input') categoryPrefix = 'Input Field';
        else if (category === 'select') categoryPrefix = 'Dropdown';
        else if (category === 'checkbox') categoryPrefix = 'Checkbox';

        const friendlyName = accessibleName ? `${categoryPrefix}: "${accessibleName}"` : `${categoryPrefix} (${tag})`;

        // Determine best locator strategy
        let locatorStrategy = 'smart';
        let locatorValue = '';

        if (role && text && text.length <= 40) {
            locatorStrategy = 'role';
            locatorValue = role === 'link' || role === 'button' || role === 'treeitem' ? text : `${role}:${text}`;
        } else if (label && label.length <= 40) {
            locatorStrategy = 'label';
            locatorValue = label;
        } else if (placeholder) {
            locatorStrategy = 'placeholder';
            locatorValue = placeholder;
        } else if (text && text.length <= 30 && !text.includes('\\n')) {
            locatorStrategy = 'text';
            locatorValue = text;
        } else if (id && !id.startsWith('a-') && !id.startsWith('B') && id.length < 35) {
            locatorStrategy = 'id';
            locatorValue = id;
        } else if (name) {
            locatorStrategy = 'name';
            locatorValue = name;
        } else {
            locatorStrategy = 'css';
            locatorValue = id ? `#${id}` : tag;
        }

        const locKey = `${locatorStrategy}:${locatorValue}`;
        const isDuplicate = seenLocators.has(locKey);
        seenLocators.add(locKey);

        let selectOptions = [];
        if (tag === 'select') {
            selectOptions = Array.from(el.querySelectorAll('option')).map(opt => ({
                value: opt.value,
                label: (opt.innerText || opt.textContent || '').trim()
            }));
        }

        results.push({
            id: `el-${counter++}`,
            category,
            tag,
            role,
            type,
            text: text.substring(0, 80),
            label,
            placeholder,
            element_id: id,
            name_attr: name,
            friendly_name: friendlyName,
            locator_strategy: locatorStrategy,
            locator_value: locatorValue,
            is_ambiguous: isDuplicate,
            options: selectOptions,
            rect: {
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }
        });
    }

    return results;
}"""


class InspectRequest(BaseModel):
    path: Optional[str] = None
    with_login: bool = False
    expand_navigation: bool = True
    force_refresh: bool = False
    viewport_width: int = 1440
    viewport_height: int = 900


class InspectElementItem(BaseModel):
    id: str
    category: str
    tag: str
    role: str
    type: str
    text: str
    label: str
    placeholder: str
    element_id: str
    name_attr: str
    friendly_name: str
    locator_strategy: str
    locator_value: str
    is_ambiguous: bool = False
    options: List[Dict[str, str]] = []
    rect: Dict[str, int]


class InspectResponse(BaseModel):
    project_id: str
    project_name: str
    page_url: str
    page_title: str
    screenshot: str  # Base64 data URI
    viewport: Dict[str, int]
    elements: List[InspectElementItem]
    categories_count: Dict[str, int]
    authenticated: bool = False


class InteractRequest(BaseModel):
    action: str  # "click", "navigate", "login", "expand_nav"
    target: Optional[str] = None
    locator_type: Optional[str] = "smart"
    value: Optional[str] = None


def _get_or_create_session(project_id: str, base_url: str, viewport: Dict[str, int]) -> Dict[str, Any]:
    """Retrieves an existing Playwright inspector session or starts a fresh one."""
    current_time = time.time()

    # Clean expired sessions (> 10 minutes inactive)
    for p_id in list(active_inspector_sessions.keys()):
        sess = active_inspector_sessions[p_id]
        if current_time - sess.get("last_active", 0) > 600:
            try:
                sess["browser"].close()
                sess["pw"].stop()
            except Exception:
                pass
            active_inspector_sessions.pop(p_id, None)

    if project_id in active_inspector_sessions:
        session = active_inspector_sessions[project_id]
        session["last_active"] = current_time
        return session

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(
        viewport=viewport,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    )

    session = {
        "pw": pw,
        "browser": browser,
        "page": page,
        "base_url": base_url,
        "authenticated": False,
        "last_active": current_time,
    }
    active_inspector_sessions[project_id] = session
    return session


def _close_session(project_id: str):
    """Closes an inspector session cleanly."""
    session = active_inspector_sessions.pop(project_id, None)
    if session:
        try:
            session["browser"].close()
            session["pw"].stop()
        except Exception:
            pass


@router.post("/{project_id}/inspect", response_model=InspectResponse)
def inspect_application_page(
    project_id: str,
    payload: InspectRequest = InspectRequest(),
    db: Session = Depends(get_db),
):
    """
    Renders the target application page, extracts all visible interactive elements
    with clean accessible locators, and returns a visual snapshot for the frontend element picker.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    base_url = (project.get("base_url") or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="Application does not have a configured base URL.")

    raw_path = (payload.path or "").strip()
    if raw_path.startswith(("http://", "https://")):
        target_url = raw_path
    elif raw_path.startswith("/"):
        target_url = f"{base_url}{raw_path}"
    elif raw_path:
        target_url = f"{base_url}/{raw_path}"
    else:
        target_url = base_url

    if payload.force_refresh:
        _close_session(project_id)

    viewport = {"width": payload.viewport_width, "height": payload.viewport_height}
    session = _get_or_create_session(project_id, base_url, viewport)
    page: Page = session["page"]

    try:
        # Check if we need to navigate or perform initial load
        if payload.force_refresh or page.url == "about:blank" or (target_url != page.url and not payload.with_login):
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(1500)

        # Handle automatic login if requested and not yet authenticated
        if payload.with_login and not session.get("authenticated"):
            # Ensure at base URL / login URL first
            if "login" not in page.url.lower():
                page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1000)

            creds_list = credentials_service.list_credentials(db, project["id"])
            if creds_list:
                dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
                user = dec.get("username", "")
                secret = dec.get("secret", "")
                if user and secret:
                    try:
                        u_loc = (
                            page.get_by_role("textbox", name="Username")
                            or page.get_by_label("Username")
                            or page.locator("#P9999_USERNAME")
                            or page.locator("input[name='username']")
                        )
                        p_loc = (
                            page.get_by_role("textbox", name="Password")
                            or page.get_by_label("Password")
                            or page.locator("#P9999_PASSWORD")
                            or page.locator("input[type='password']")
                        )
                        b_loc = (
                            page.get_by_role("button", name="Sign In")
                            or page.get_by_role("button", name="Log In")
                            or page.locator("button[type='submit']")
                        )

                        if u_loc.count() > 0 and p_loc.count() > 0:
                            u_loc.first.fill(user)
                            p_loc.first.fill(secret)
                            b_loc.first.click()
                            try:
                                page.wait_for_load_state("load", timeout=12000)
                            except Exception:
                                pass
                            page.wait_for_timeout(2000)
                            session["authenticated"] = True
                    except Exception as log_err:
                        logger.warning(f"Auto-login failed: {log_err}")

        # Expand navigation if requested
        if payload.expand_navigation:
            ensure_navigation_expanded(page)

        # Run client-side DOM scanner
        raw_elements = page.evaluate(DOM_SCANNER_SCRIPT)

        # Capture screenshot
        screenshot_bytes = page.screenshot(type="png", full_page=False)
        screenshot_b64 = f"data:image/png;base64,{base64.b64encode(screenshot_bytes).decode('utf-8')}"

        page_url = page.url
        page_title = page.title()

        cat_counts: Dict[str, int] = {
            "buttons": sum(1 for e in raw_elements if e["category"] == "button"),
            "links": sum(1 for e in raw_elements if e["category"] == "link"),
            "inputs": sum(1 for e in raw_elements if e["category"] == "input"),
            "selects": sum(1 for e in raw_elements if e["category"] == "select"),
            "total": len(raw_elements),
        }

        return InspectResponse(
            project_id=project_id,
            project_name=project.get("name", project_id),
            page_url=page_url,
            page_title=page_title,
            screenshot=screenshot_b64,
            viewport=viewport,
            elements=raw_elements,
            categories_count=cat_counts,
            authenticated=session.get("authenticated", False),
        )

    except Exception as exc:
        _close_session(project_id)
        logger.error(f"Failed to inspect application '{project_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unable to inspect application page: {str(exc)}",
        )


@router.post("/{project_id}/interact", response_model=InspectResponse)
def interact_with_inspector(
    project_id: str,
    payload: InteractRequest,
    db: Session = Depends(get_db),
):
    """
    Executes an action (e.g. click a menu item or login) within the active inspector session,
    allowing the user to advance pages and pick elements from subsequent views.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    base_url = (project.get("base_url") or "").rstrip("/")
    session = _get_or_create_session(project_id, base_url, {"width": 1440, "height": 900})
    page: Page = session["page"]

    try:
        if payload.action == "login":
            creds_list = credentials_service.list_credentials(db, project["id"])
            if not creds_list:
                raise HTTPException(status_code=400, detail="No vault credentials configured for this application.")
            dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
            user = dec.get("username", "")
            secret = dec.get("secret", "")

            u_loc = (
                page.get_by_role("textbox", name="Username")
                or page.get_by_label("Username")
                or page.locator("#P9999_USERNAME")
                or page.locator("input[name='username']")
            )
            p_loc = (
                page.get_by_role("textbox", name="Password")
                or page.get_by_label("Password")
                or page.locator("#P9999_PASSWORD")
                or page.locator("input[type='password']")
            )
            b_loc = (
                page.get_by_role("button", name="Sign In")
                or page.get_by_role("button", name="Log In")
                or page.locator("button[type='submit']")
            )

            if u_loc.count() > 0 and p_loc.count() > 0:
                u_loc.first.fill(user)
                p_loc.first.fill(secret)
                b_loc.first.click()
                try:
                    page.wait_for_load_state("load", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                ensure_navigation_expanded(page)
                session["authenticated"] = True

        elif payload.action == "click" and payload.target:
            robust_click(page, payload.locator_type, payload.target)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            ensure_navigation_expanded(page)

        elif payload.action == "navigate" and payload.target:
            dest = payload.target
            if dest.startswith("/"):
                dest = f"{base_url}{dest}"
            page.goto(dest, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            ensure_navigation_expanded(page)

        elif payload.action == "expand_nav":
            ensure_navigation_expanded(page)
            page.wait_for_timeout(800)

        raw_elements = page.evaluate(DOM_SCANNER_SCRIPT)
        screenshot_bytes = page.screenshot(type="png", full_page=False)
        screenshot_b64 = f"data:image/png;base64,{base64.b64encode(screenshot_bytes).decode('utf-8')}"

        cat_counts: Dict[str, int] = {
            "buttons": sum(1 for e in raw_elements if e["category"] == "button"),
            "links": sum(1 for e in raw_elements if e["category"] == "link"),
            "inputs": sum(1 for e in raw_elements if e["category"] == "input"),
            "selects": sum(1 for e in raw_elements if e["category"] == "select"),
            "total": len(raw_elements),
        }

        return InspectResponse(
            project_id=project_id,
            project_name=project.get("name", project_id),
            page_url=page.url,
            page_title=page.title(),
            screenshot=screenshot_b64,
            viewport={"width": 1440, "height": 900},
            elements=raw_elements,
            categories_count=cat_counts,
            authenticated=session.get("authenticated", False),
        )

    except Exception as exc:
        logger.error(f"Interaction error in inspector for '{project_id}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Interaction error: {str(exc)}")


@router.post("/{project_id}/close")
def close_inspector_session(project_id: str):
    """Closes an active inspection session."""
    _close_session(project_id)
    return {"status": "closed", "project_id": project_id}
