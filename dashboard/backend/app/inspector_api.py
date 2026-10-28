"""
Veriqon High-Performance Element Inspector API
Provides instant, real-time element discovery, visual inspection, persistent browser sessions,
interactive element picking, and dynamic modal/dialog element selection for web applications.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import sys
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from app.database import get_db
from app import db_service, credentials_service
from app.models.elements import AppElement

logger = logging.getLogger("veriqon.inspector")

router = APIRouter(prefix="/api/inspector", tags=["Element Inspector"])

# Client-side DOM scanner script with modal/dialog detection and scoped locators
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

        if (tag === 'button' || role === 'button' || ['submit', 'button', 'reset'].includes(type) || el.classList.contains('t-Button') || el.classList.contains('project-option')) {
            return 'button';
        }
        if (
            tag === 'a' ||
            ['link', 'treeitem', 'menuitem', 'tab'].includes(role) ||
            el.closest('.a-TreeView') ||
            el.closest('#t_TreeNav') ||
            el.closest('.t-Body-nav') ||
            el.closest('nav') ||
            el.classList.contains('a-TreeView-label') ||
            el.classList.contains('nav-link')
        ) {
            return 'link';
        }
        if (tag === 'select' || role === 'combobox' || role === 'listbox') {
            return 'select';
        }
        if (tag === 'textarea' || tag === 'input' || el.classList.contains('hours-input') || el.classList.contains('project-name')) {
            return 'input';
        }
        if (type === 'checkbox' || role === 'checkbox') return 'checkbox';
        if (type === 'radio' || role === 'radio') return 'radio';
        return 'other';
    }

    // Modal & Dialog detection
    const dialogSelectors = [
        'dialog',
        '[role="dialog"]',
        '.ui-dialog',
        '.modal',
        '.t-Dialog-page',
        '.project-picker',
        '.popup-content',
        '.a-Dialog',
        '.modal-dialog',
        '.fade.show',
        '.ui-widget-overlay',
    ];

    const visibleDialogs = Array.from(document.querySelectorAll(dialogSelectors.join(','))).filter(d => {
        try {
            const s = window.getComputedStyle(d);
            const r = d.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0 && r.width > 0 && r.height > 0;
        } catch (e) {
            return false;
        }
    });

    const hasOpenDialog = visibleDialogs.length > 0;
    let activeDialogTitle = '';
    if (hasOpenDialog) {
        const topDialog = visibleDialogs[visibleDialogs.length - 1];
        const titleEl = topDialog.querySelector('.ui-dialog-title, .modal-title, h1, h2, h3, h4, [role="heading"]');
        activeDialogTitle = titleEl ? titleEl.innerText.trim() : (topDialog.getAttribute('aria-label') || 'Modal Dialog');
    }

    const interactiveSelectors = [
        'button',
        'a',
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
        '.a-TreeView-content',
        '.t-TreeNav-item',
        '.t-Button',
        '.hours-input',
        '.timesheet-header',
        '.timesheet-date',
        '.daily-total',
        '.project-name',
        '.project-option',
        '.project-picker-close',
        '#close_project_picker',
        '.assigned-project-name',
        '.mon-hours',
        '.tue-hours',
        '.wed-hours',
        '.thu-hours',
        '.fri-hours',
        '.sat-hours',
        '.sun-hours',
        'nav a',
        'aside a',
        '.nav-link',
        '[data-action]'
    ].join(',');

    const elements = Array.from(document.querySelectorAll(interactiveSelectors));
    const results = [];
    const seenLocators = new Set();

    let counter = 1;
    for (const el of elements) {
        const rect = el.getBoundingClientRect();
        // Skip zero-size elements
        if (rect.width <= 0 || rect.height <= 0) continue;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) continue;

        // Skip disconnected elements
        if (!el.isConnected) continue;

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || (tag === 'button' ? 'button' : tag === 'a' ? 'link' : tag === 'input' ? 'textbox' : '');
        const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
        const label = getAssociatedLabel(el);
        const placeholder = el.getAttribute('placeholder') || '';
        const id = el.id || '';
        const name = el.getAttribute('name') || '';
        const type = el.getAttribute('type') || '';
        const category = getElementCategory(el);

        // Check if inside a dialog/modal container
        const parentDialog = el.closest('dialog, [role="dialog"], .ui-dialog, .modal, .t-Dialog-page, .project-picker, .popup-content, .a-Dialog');
        const inDialog = !!parentDialog;
        let elementDialogTitle = '';
        if (inDialog) {
            const dt = parentDialog.querySelector('.ui-dialog-title, .modal-title, h1, h2, h3, h4');
            elementDialogTitle = dt ? dt.innerText.trim() : (parentDialog.getAttribute('aria-label') || activeDialogTitle || 'Dialog');
        }

        // Custom friendly names for APEX Timesheet elements
        let customName = '';
        let customLocatorStrategy = '';
        let customLocatorValue = '';

        if (id === 'p4-current') {
            customName = 'This Week';
        } else if (id === 'p4-previous') {
            customName = 'Last Week';
        } else if (id === 'p4-next') {
            customName = 'Next Week';
        } else if (id === 'add_project_btn') {
            customName = '+ Add Project';
        } else if (id === 'save') {
            customName = 'Save Timesheet';
        } else if (id === 'delete_project_btn') {
            customName = 'Delete Project';
        } else if (id === 'whereabouts') {
            customName = 'Whereabouts';
        } else if (id === 'close_project_picker' || el.classList.contains('project-picker-close')) {
            customName = 'Close Project Picker';
            customLocatorStrategy = 'css';
            customLocatorValue = '#close_project_picker, .project-picker-close';
        } else if (id === 'mon_total') {
            customName = 'Monday Total';
        } else if (id === 'tue_total') {
            customName = 'Tuesday Total';
        } else if (id === 'wed_total') {
            customName = 'Wednesday Total';
        } else if (id === 'thu_total') {
            customName = 'Thursday Total';
        } else if (id === 'fri_total') {
            customName = 'Friday Total';
        } else if (id === 'weekly_total') {
            customName = 'Weekly Total Hours';
        }

        // Project Option cards (modal popup)
        if (el.classList.contains('project-option') || el.closest('.project-option')) {
            const cleanTitle = text.replace(/[\\u25a0-\\u25ff\\u203a\\n\\r]+/g, ' ').replace(/\\s+/g, ' ').trim();
            customName = `Project Option: "${cleanTitle}"`;
            customLocatorStrategy = 'text';
            customLocatorValue = cleanTitle;
        }

        // Assigned project name field
        if (el.classList.contains('assigned-project-name') || (el.classList.contains('project-name') && tag === 'input')) {
            customName = 'Assigned Project Name';
            customLocatorStrategy = 'css';
            customLocatorValue = 'input.project-name';
        }

        // Monday-Sunday Hours inputs with specific classes
        if (el.classList.contains('mon-hours')) {
            customName = 'Monday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.mon-hours';
        } else if (el.classList.contains('tue-hours')) {
            customName = 'Tuesday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.tue-hours';
        } else if (el.classList.contains('wed-hours')) {
            customName = 'Wednesday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.wed-hours';
        } else if (el.classList.contains('thu-hours')) {
            customName = 'Thursday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.thu-hours';
        } else if (el.classList.contains('fri-hours')) {
            customName = 'Friday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.fri-hours';
        } else if (el.classList.contains('sat-hours')) {
            customName = 'Saturday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.sat-hours';
        } else if (el.classList.contains('sun-hours')) {
            customName = 'Sunday Hours';
            customLocatorStrategy = 'css';
            customLocatorValue = '.hours-input.sun-hours';
        } else if (el.classList.contains('hours-input') || el.closest('.hour-cell') || el.closest('.timesheet-grid')) {
            const allHours = Array.from(document.querySelectorAll('.hours-input, .hour-cell input, .timesheet-grid input[type="text"], .timesheet-grid input:not([type="hidden"])'));
            const idx = allHours.indexOf(el);
            if (idx >= 0) {
                const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
                const dayName = days[idx % 7];
                const rowNum = Math.floor(idx / 7) + 1;
                customName = `${dayName} Hours (Row ${rowNum})`;
            }
        }

        // Filter out technical dummy elements that aren't real user controls
        const isTechnicalId = (val) => {
            if (!val) return false;
            const l = val.toLowerCase();
            return l.includes('dummy') || l.startsWith('pflow') || l.startsWith('pinstance') || l.startsWith('apex_') || l === 't_body_skiptocontent';
        };

        if (id && isTechnicalId(id) && !label && !text && !placeholder) {
            continue; // Skip invisible system dummy controls
        }

        // Natural Name Builder: human-readable without technical prefixes
        function formatNaturalName(base, cat, inDiag) {
            let n = base.trim().replace(/^[\+\-\*\•\s]+/, '').trim();
            const lower = n.toLowerCase();
            if (cat === 'button') {
                return lower.includes('button') ? n : `${n} button`;
            }
            if (cat === 'link') {
                return lower.includes('link') || lower.includes('menu') ? n : `${n} link`;
            }
            if (cat === 'input') {
                if (lower.includes('field') || lower.includes('input') || lower.includes('hours')) return n;
                return `${n} field`;
            }
            if (cat === 'select') {
                return lower.includes('dropdown') || lower.includes('select') ? n : `${n} dropdown`;
            }
            if (cat === 'checkbox') {
                return lower.includes('checkbox') ? n : `${n} checkbox`;
            }
            if (cat === 'radio') {
                return lower.includes('radio') ? n : `${n} radio option`;
            }
            return n;
        }

        function buildDescription(name, cat, txt, ph, lbl) {
            const l = name.toLowerCase();
            if (l.includes('save')) return 'Saves the current form or timesheet';
            if (l.includes('add project')) return 'Adds a new project row or opens project selector';
            if (l.includes('delete project')) return 'Deletes the selected project entry';
            if (l.includes('this week')) return 'Switches timesheet view to the current week';
            if (l.includes('last week')) return 'Switches timesheet view to the previous week';
            if (l.includes('next week')) return 'Switches timesheet view to the next week';
            if (l.includes('whereabouts')) return 'Opens user whereabouts view';
            if (l.includes('monday hours')) return "Input for entering Monday's working hours";
            if (l.includes('tuesday hours')) return "Input for entering Tuesday's working hours";
            if (l.includes('wednesday hours')) return "Input for entering Wednesday's working hours";
            if (l.includes('thursday hours')) return "Input for entering Thursday's working hours";
            if (l.includes('friday hours')) return "Input for entering Friday's working hours";
            if (l.includes('saturday hours')) return "Input for entering Saturday's working hours";
            if (l.includes('sunday hours')) return "Input for entering Sunday's working hours";
            if (l.includes('my timesheet')) return 'Opens the My Timesheet page';
            if (l.includes('search')) return 'Enter a search term';
            if (l.includes('project name')) return 'Field for entering or selecting a project name';
            if (l.includes('sign in') || l.includes('log in')) return 'Submits credentials to sign in';
            if (l.includes('username') || l.includes('user name')) return 'Enter your username or email';
            if (l.includes('password')) return 'Enter your password';

            if (cat === 'button') return `Clicks the ${name.replace(/ button$/i, '')} button`;
            if (cat === 'link') return `Navigates to ${name.replace(/ link$/i, '')}`;
            if (cat === 'input') return ph ? `Enter ${ph}` : lbl ? `Input for ${lbl}` : 'Enter text';
            if (cat === 'select') return 'Select an option from the dropdown';
            if (cat === 'checkbox') return 'Toggles checkbox option';
            return 'Interactive control';
        }

        let baseName = customName || label || text || placeholder;
        if (!baseName && id && !isTechnicalId(id) && id.length < 25) {
            baseName = id.replace(/[-_]+/g, ' ').trim();
        }

        let friendlyName = '';
        if (baseName) {
            friendlyName = formatNaturalName(baseName, category, inDialog);
        } else {
            if (category === 'button') friendlyName = 'Button without a label';
            else if (category === 'input') friendlyName = placeholder ? `${placeholder} field` : 'Unnamed text field';
            else if (category === 'link') friendlyName = 'Unnamed link';
            else if (category === 'select') friendlyName = 'Unnamed dropdown';
            else if (category === 'checkbox') friendlyName = 'Unnamed checkbox';
            else friendlyName = 'Unnamed control';
        }

        if (friendlyName.length > 55) friendlyName = friendlyName.substring(0, 55) + '...';
        const description = buildDescription(friendlyName, category, text, placeholder, label);

        // Determine best locator strategy
        let locatorStrategy = customLocatorStrategy || 'smart';
        let locatorValue = customLocatorValue || '';

        if (!locatorValue) {
            if (id && !id.startsWith('a-') && id.length < 50) {
                locatorStrategy = 'id';
                locatorValue = id;
            } else if (customName && id) {
                locatorStrategy = 'id';
                locatorValue = id;
            } else if (inDialog && text && text.length <= 40) {
                // Scope locator to dialog container
                locatorStrategy = 'css';
                let dPrefix = '';
                if (parentDialog) {
                    const dTag = (parentDialog.tagName || 'div').toLowerCase();
                    let dClass = '';
                    if (typeof parentDialog.className === 'string') {
                        dClass = parentDialog.className.split(' ').filter(c => c && !c.includes(':') && !c.includes('ui-widget'))[0] || '';
                    }
                    dPrefix = dClass ? `.${dClass}` : dTag;
                }
                locatorValue = dPrefix ? `${dPrefix} >> text="${text}"` : `text="${text}"`;
            } else if (el.classList.contains('hours-input')) {
                const allHours = Array.from(document.querySelectorAll('.hours-input'));
                const idx = allHours.indexOf(el);
                locatorStrategy = 'css';
                locatorValue = idx >= 0 ? `.hours-input:nth-of-type(${idx + 1})` : '.hours-input';
            } else if ((role === 'treeitem' || el.closest('.a-TreeView')) && text && text.length <= 40) {
                locatorStrategy = 'role';
                locatorValue = text;
            } else if (role && text && text.length <= 40) {
                locatorStrategy = 'role';
                locatorValue = role === 'link' || role === 'button' ? text : `${role}:${text}`;
            } else if (label && label.length <= 40) {
                locatorStrategy = 'label';
                locatorValue = label;
            } else if (placeholder) {
                locatorStrategy = 'placeholder';
                locatorValue = placeholder;
            } else if (text && text.length <= 35 && !text.includes('\\n')) {
                locatorStrategy = 'text';
                locatorValue = text;
            } else if (id && !id.startsWith('a-') && id.length < 50) {
                locatorStrategy = 'id';
                locatorValue = id;
            } else if (name) {
                locatorStrategy = 'name';
                locatorValue = name;
            } else if (tag === 'a' && el.getAttribute('href') && !el.getAttribute('href').startsWith('#') && !el.getAttribute('href').startsWith('javascript:')) {
                locatorStrategy = 'css';
                locatorValue = `a[href="${el.getAttribute('href')}"]`;
            } else if (id) {
                locatorStrategy = 'id';
                locatorValue = id;
            } else {
                locatorStrategy = 'css';
                locatorValue = tag;
            }
        }

        // Deduplication key
        const dupKey = `${locatorStrategy}:${locatorValue}`;
        if (seenLocators.has(dupKey)) continue;
        seenLocators.add(dupKey);

        results.push({
            id: `el_${counter++}`,
            friendly_name: friendlyName,
            description: description,
            category: category,
            tag_name: tag,
            role: role || (category === 'link' && el.closest('.a-TreeView') ? 'treeitem' : undefined),
            text: text,
            label: label,
            placeholder: placeholder,
            element_id: id,
            name_attr: name,
            type_attr: type,
            locator_strategy: locatorStrategy,
            locator_value: locatorValue,
            suggested_action: category === 'input' ? 'fill_input' : category === 'select' ? 'select_option' : category === 'link' ? 'navigate' : 'click_element',
            in_dialog: inDialog,
            dialog_title: elementDialogTitle,
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                top: Math.round(rect.top),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                bottom: Math.round(rect.bottom)
            }
        });
    }

    return {
        elements: results,
        has_open_dialog: hasOpenDialog,
        active_dialog_title: activeDialogTitle
    };
}"""


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


def clean_page_identity(url: str, page_title: str = "") -> tuple[str, str]:
    """
    Strips volatile session tokens (session=..., cs=..., state=..., nonce=...)
    to form a canonical page URL for persistent element deduplication,
    and derives a friendly human-readable page name.
    """
    if not url:
        return "", "Home"
    parsed = urlparse(url)
    volatile_params = {"session", "cs", "tz", "state", "nonce", "code", "p_instance"}
    query_dict = parse_qs(parsed.query, keep_blank_values=False)
    filtered_query = {k: v for k, v in query_dict.items() if k.lower() not in volatile_params}
    clean_query = urlencode(filtered_query, doseq=True)
    clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", clean_query, ""))

    clean_title = (page_title or "").strip()
    if " - " in clean_title:
        parts = clean_title.split(" - ")
        page_name = parts[-1].strip() if len(parts[-1].strip()) > 2 else parts[0].strip()
    elif " | " in clean_title:
        parts = clean_title.split(" | ")
        page_name = parts[0].strip()
    elif clean_title:
        page_name = clean_title
    else:
        last_seg = parsed.path.strip("/").split("/")[-1] if parsed.path.strip("/") else "Home"
        page_name = last_seg.replace("-", " ").replace("_", " ").title()

    return clean_url, page_name


def redact_sensitive_url(url: str) -> str:
    """
    Redacts sensitive query parameters (tokens, passwords, session secrets, auth codes)
    so they are never displayed in the UI or written to logs.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        query_dict = parse_qs(parsed.query, keep_blank_values=True)
        sensitive_keys = {
            "session", "cs", "token", "access_token", "id_token", "auth",
            "secret", "password", "code", "state", "nonce", "sig", "signature", "key"
        }
        redacted_query = {}
        for k, vals in query_dict.items():
            if k.lower() in sensitive_keys:
                redacted_query[k] = ["[redacted]"]
            else:
                redacted_query[k] = vals
        clean_query = urlencode(redacted_query, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", clean_query, ""))
    except Exception:
        return url


# In-Browser Floating Capture Dock and Element Picker script (injected into target application browser)
INPAGE_CAPTURE_DOCK_SCRIPT = """(() => {
    function initVeriqonDock() {
        const projectId = window.__VERIQON_PROJECT_ID__ || '';
        if (!projectId) return;

        const isChildFrame = (window !== window.top);

        if (!isChildFrame && document.getElementById('veriqon-inpage-dock')) {
            return;
        }

        if (!document.body) {
            return;
        }

        // Styles for Dock, Toasts, Highlighting, and Modal
        if (!document.getElementById('veriqon-inpage-styles')) {
            const style = document.createElement('style');
            style.id = 'veriqon-inpage-styles';
            style.textContent = `
            #veriqon-inpage-dock {
                position: fixed;
                top: 18px;
                right: 22px;
                z-index: 2147483647 !important; display: flex !important; visibility: visible !important; opacity: 1 !important;
                background: rgba(15, 23, 42, 0.95);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(56, 189, 248, 0.6);
                border-radius: 12px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 20px rgba(56, 189, 248, 0.25);
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 13px;
                padding: 10px 14px;
                display: flex;
                flex-direction: column;
                gap: 8px;
                min-width: 260px;
                user-select: none;
                transition: width 0.2s, padding 0.2s;
            }
            #veriqon-inpage-dock.vq-minimized {
                min-width: 0;
                padding: 6px 10px;
            }
            #veriqon-inpage-dock.vq-minimized .vq-dock-body {
                display: none !important;
            }
            .vq-dock-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                cursor: grab;
            }
            .vq-dock-header:active {
                cursor: grabbing;
            }
            .vq-dock-brand {
                display: flex;
                align-items: center;
                gap: 6px;
                font-weight: 700;
                font-size: 12px;
                color: #38bdf8;
                letter-spacing: 0.5px;
                text-transform: uppercase;
            }
            .vq-dock-actions {
                display: flex;
                align-items: center;
                gap: 4px;
            }
            .vq-dock-ctrl-btn {
                background: transparent;
                border: none;
                color: #94a3b8;
                font-size: 15px;
                cursor: pointer;
                padding: 2px 6px;
                border-radius: 4px;
                line-height: 1;
            }
            .vq-dock-ctrl-btn:hover {
                color: #ffffff;
                background: rgba(255, 255, 255, 0.15);
            }
            .vq-dock-body {
                display: flex;
                flex-direction: column;
                gap: 6px;
            }
            .vq-dock-btn {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
                border: 1px solid transparent;
                cursor: pointer;
                transition: all 0.15s ease;
            }
            .vq-dock-btn-primary {
                background: #0284c7;
                color: #ffffff;
                border-color: #38bdf8;
            }
            .vq-dock-btn-primary:hover {
                background: #0369a1;
            }
            .vq-dock-btn-secondary {
                background: rgba(30, 41, 59, 0.9);
                color: #38bdf8;
                border-color: rgba(56, 189, 248, 0.4);
            }
            .vq-dock-btn-secondary:hover {
                background: rgba(56, 189, 248, 0.15);
                border-color: #38bdf8;
            }
            .vq-dock-btn.active-picking {
                background: #ef4444;
                color: white;
                border-color: #f87171;
                animation: vqPulse 1.5s infinite;
            }
            @keyframes vqPulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.75; }
            }
            .vq-toast {
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 2147483647;
                background: #0f172a;
                color: #10b981;
                border: 1px solid #10b981;
                padding: 10px 16px;
                border-radius: 8px;
                font-family: sans-serif;
                font-size: 13px;
                font-weight: 600;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                animation: vqFadeIn 0.25s ease;
            }
            @keyframes vqFadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            #veriqon-element-modal-overlay {
                position: fixed;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0, 0, 0, 0.65);
                backdrop-filter: blur(2px);
                z-index: 2147483646;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            #veriqon-element-modal {
                background: #0f172a;
                border: 1px solid #0284c7;
                border-radius: 12px;
                padding: 20px;
                width: 380px;
                max-width: 90vw;
                box-shadow: 0 20px 40px rgba(0,0,0,0.8), 0 0 20px rgba(2, 132, 199, 0.3);
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            .vq-modal-title {
                font-size: 15px;
                font-weight: 700;
                color: #38bdf8;
                margin: 0 0 4px 0;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            .vq-modal-subtitle {
                font-size: 11px;
                color: #94a3b8;
                margin-bottom: 14px;
            }
            .vq-chip-row {
                display: flex;
                gap: 6px;
                flex-wrap: wrap;
                margin-bottom: 12px;
            }
            .vq-chip {
                background: rgba(56, 189, 248, 0.12);
                color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.3);
                padding: 3px 8px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
            }
            .vq-field-group {
                margin-bottom: 12px;
                display: flex;
                flex-direction: column;
                gap: 4px;
            }
            .vq-field-label {
                font-size: 11px;
                font-weight: 600;
                color: #cbd5e1;
                text-transform: uppercase;
            }
            .vq-modal-input {
                background: #1e293b;
                border: 1px solid #334155;
                color: #f8fafc;
                padding: 8px 10px;
                border-radius: 6px;
                font-size: 13px;
                outline: none;
                width: 100%;
                box-sizing: border-box;
            }
            .vq-modal-input:focus {
                border-color: #38bdf8;
                box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
            }
            .vq-modal-actions {
                display: flex;
                gap: 8px;
                margin-top: 16px;
            }
            .vq-modal-actions button {
                flex: 1;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
                cursor: pointer;
            }
            .vq-btn-save {
                background: #10b981;
                color: white;
                border: none;
            }
            .vq-btn-save:hover {
                background: #059669;
            }
            .vq-btn-cancel {
                background: #334155;
                color: #cbd5e1;
                border: none;
            }
            .vq-btn-cancel:hover {
                background: #475569;
            }
        `;
        document.head.appendChild(style);
    }

    // Build the dock HTML (only on top frame)
    let dock = null;
    if (!isChildFrame) {
        dock = document.createElement('div');
        dock.id = 'veriqon-inpage-dock';
        dock.innerHTML = `
            <div class="vq-dock-header" id="vq-dock-drag-header">
                <div class="vq-dock-brand">
                    <span>⚡ Veriqon Capture</span>
                </div>
                <div class="vq-dock-actions">
                    <button class="vq-dock-ctrl-btn" id="vq-dock-min-btn" title="Minimize / Expand">_</button>
                </div>
            </div>
            <div class="vq-dock-body" id="vq-dock-body">
                <button class="vq-dock-btn vq-dock-btn-primary" id="vq-btn-capture-page">
                    📸 Capture This Page
                </button>
                <button class="vq-dock-btn vq-dock-btn-secondary" id="vq-btn-capture-element">
                    🎯 Capture Any Element
                </button>
            </div>
        `;
        document.body.appendChild(dock);

        // Draggable header
        const header = document.getElementById('vq-dock-drag-header');
        let isDragging = false;
        let startX = 0, startY = 0, startLeft = 0, startTop = 0;
        if (header) {
            header.addEventListener('mousedown', (e) => {
                if (e.target.id === 'vq-dock-min-btn') return;
                isDragging = true;
                startX = e.clientX;
                startY = e.clientY;
                const rect = dock.getBoundingClientRect();
                startLeft = rect.left;
                startTop = rect.top;
                dock.style.right = 'auto';
                dock.style.left = startLeft + 'px';
                dock.style.top = startTop + 'px';
            });
            document.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const dx = e.clientX - startX;
                const dy = e.clientY - startY;
                dock.style.left = Math.max(10, Math.min(window.innerWidth - 100, startLeft + dx)) + 'px';
                dock.style.top = Math.max(10, Math.min(window.innerHeight - 50, startTop + dy)) + 'px';
            });
            document.addEventListener('mouseup', () => { isDragging = false; });
        }

        // Minimize button
        const minBtn = document.getElementById('vq-dock-min-btn');
        if (minBtn) {
            minBtn.addEventListener('click', () => {
                dock.classList.toggle('vq-minimized');
                minBtn.innerText = dock.classList.contains('vq-minimized') ? '□' : '_';
            });
        }

        // Capture Page button
        const capturePageBtn = document.getElementById('vq-btn-capture-page');
        if (capturePageBtn) {
            capturePageBtn.addEventListener('click', async () => {
                capturePageBtn.innerText = '⏳ Capturing page...';
                capturePageBtn.disabled = true;
                try {
                    let data;
                    if (typeof window.__veriqon_native_capture__ === 'function') {
                        data = await window.__veriqon_native_capture__(projectId);
                    } else {
                        const resp = await fetch(`http://127.0.0.1:8000/api/inspector/${encodeURIComponent(projectId)}/capture-page`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' }
                        });
                        data = await resp.json();
                    }
                    if (data && (data.total_scanned !== undefined || data.elements)) {
                        const total = data.total_scanned !== undefined ? data.total_scanned : (data.elements ? data.elements.length : 0);
                        showToast(`✓ Captured ${total} elements (including open modal dialogs)!`);
                    } else {
                        showToast(`Capture failed: ${data && data.detail ? data.detail : 'Unknown error'}`, true);
                    }
                } catch (err) {
                    showToast(`Capture failed: ${err.message}`, true);
                } finally {
                    capturePageBtn.innerText = '📸 Capture This Page';
                    capturePageBtn.disabled = false;
                }
            });
        }
    }

    function showToast(text, isError = false) {
        const existing = document.getElementById('vq-inpage-toast');
        if (existing) existing.remove();
        const toast = document.createElement('div');
        toast.id = 'vq-inpage-toast';
        toast.className = 'vq-toast';
        if (isError) {
            toast.style.borderColor = '#ef4444';
            toast.style.color = '#f87171';
        }
        toast.innerText = text;
        document.body.appendChild(toast);
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, 3500);
    }

    // Element Picker mode setup
    let overlay = document.getElementById('veriqon-picker-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'veriqon-picker-overlay';
        overlay.style.position = 'fixed';
        overlay.style.pointerEvents = 'none';
        overlay.style.border = '2px solid #06b6d4';
        overlay.style.backgroundColor = 'rgba(6, 182, 212, 0.2)';
        overlay.style.borderRadius = '4px';
        overlay.style.zIndex = '2147483645';
        overlay.style.transition = 'all 0.05s ease';
        overlay.style.display = 'none';
        document.body.appendChild(overlay);
    }
    let badge = document.getElementById('veriqon-picker-badge');
    if (!badge) {
        badge = document.createElement('div');
        badge.id = 'veriqon-picker-badge';
        badge.style.position = 'fixed';
        badge.style.pointerEvents = 'none';
        badge.style.background = '#0f172a';
        badge.style.color = '#38bdf8';
        badge.style.fontFamily = 'system-ui, -apple-system, sans-serif';
        badge.style.fontSize = '12px';
        badge.style.fontWeight = '600';
        badge.style.padding = '4px 10px';
        badge.style.borderRadius = '5px';
        badge.style.boxShadow = '0 4px 14px rgba(0,0,0,0.5)';
        badge.style.zIndex = '2147483645';
        badge.style.display = 'none';
        badge.style.whiteSpace = 'nowrap';
        document.body.appendChild(badge);
    }

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

        if (tag === 'button' || role === 'button' || ['submit', 'button', 'reset'].includes(type) || el.classList.contains('t-Button') || el.classList.contains('project-option')) {
            return 'button';
        }
        if (tag === 'a' || ['link', 'treeitem', 'menuitem', 'tab'].includes(role) || el.closest('.a-TreeView') || el.classList.contains('a-TreeView-label') || el.classList.contains('nav-link')) {
            return 'link';
        }
        if (tag === 'select' || role === 'combobox' || role === 'listbox') return 'select';
        if (tag === 'textarea' || tag === 'input' || el.classList.contains('hours-input') || el.classList.contains('project-name')) return 'input';
        if (type === 'checkbox' || role === 'checkbox') return 'checkbox';
        if (type === 'radio' || role === 'radio') return 'radio';
        return 'other';
    }

    function findInteractiveTarget(el) {
        if (!el || el === document.body || el === document.documentElement) return null;
        if (el.id === 'veriqon-picker-overlay' || el.id === 'veriqon-picker-badge') return null;
        if (el.closest('#veriqon-inpage-dock') || el.closest('#veriqon-element-modal-overlay')) return null;
        const candidate = el.closest('button, a, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"], [role="treeitem"], [role="menuitem"], [role="tab"], [role="checkbox"], [role="radio"], [role="combobox"], .project-option, .t-Button, .a-TreeView-label, .hours-input, .project-name, .project-picker-close');
        return candidate || el;
    }

    function buildFriendlyNameAndDesc(el, tag, category, role, label, text, placeholder) {
        let name = '';
        let desc = '';
        const id = el.id || '';

        if (id === 'p4-current') { name = 'This Week'; desc = 'Switches timesheet view to the current week'; }
        else if (id === 'p4-previous') { name = 'Last Week'; desc = 'Switches timesheet view to the previous week'; }
        else if (id === 'p4-next') { name = 'Next Week'; desc = 'Switches timesheet view to the next week'; }
        else if (id === 'add_project_btn') { name = '+ Add Project'; desc = 'Adds a new project row or opens project selector'; }
        else if (id === 'save') { name = 'Save Timesheet'; desc = 'Saves the current timesheet'; }
        else if (id === 'delete_project_btn') { name = 'Delete Project'; desc = 'Deletes the selected project'; }
        else if (id === 'whereabouts') { name = 'Whereabouts'; desc = 'Opens user whereabouts view'; }
        else if (el.classList.contains('mon-hours')) { name = 'Monday Hours'; desc = "Input for Monday's working hours"; }
        else if (el.classList.contains('tue-hours')) { name = 'Tuesday Hours'; desc = "Input for Tuesday's working hours"; }
        else if (el.classList.contains('wed-hours')) { name = 'Wednesday Hours'; desc = "Input for Wednesday's working hours"; }
        else if (el.classList.contains('thu-hours')) { name = 'Thursday Hours'; desc = "Input for Thursday's working hours"; }
        else if (el.classList.contains('fri-hours')) { name = 'Friday Hours'; desc = "Input for Friday's working hours"; }
        else if (el.classList.contains('sat-hours')) { name = 'Saturday Hours'; desc = "Input for Saturday's working hours"; }
        else if (el.classList.contains('sun-hours')) { name = 'Sunday Hours'; desc = "Input for Sunday's working hours"; }
        else if (el.classList.contains('project-option')) {
            const clean = text.replace(/[\\u25a0-\\u25ff\\u203a\\n\\r]+/g, ' ').trim();
            name = `Project Option: "${clean}"`;
            desc = `Selects project "${clean}"`;
        }

        if (!name) {
            const base = label || text || placeholder || id.replace(/[-_]+/g, ' ').trim();
            const cleanBase = base.replace(/^[\+\-\*\•\s]+/, '').trim();
            if (category === 'button') name = cleanBase.toLowerCase().includes('button') ? cleanBase : `${cleanBase} button`;
            else if (category === 'link') name = cleanBase.toLowerCase().includes('link') ? cleanBase : `${cleanBase} link`;
            else if (category === 'input') name = cleanBase.toLowerCase().includes('field') || cleanBase.toLowerCase().includes('input') || cleanBase.toLowerCase().includes('hours') ? cleanBase : `${cleanBase} field`;
            else if (category === 'select') name = cleanBase.toLowerCase().includes('dropdown') ? cleanBase : `${cleanBase} dropdown`;
            else if (category === 'checkbox') name = cleanBase.toLowerCase().includes('checkbox') ? cleanBase : `${cleanBase} checkbox`;
            else name = cleanBase || `${tag} element`;

            if (category === 'button') desc = `Clicks the ${cleanBase} button`;
            else if (category === 'link') desc = `Navigates to ${cleanBase}`;
            else if (category === 'input') desc = placeholder ? `Enter ${placeholder}` : label ? `Input for ${label}` : 'Enter text';
            else if (category === 'select') desc = 'Select an option from dropdown';
            else desc = 'Interactive control';
        }

        return { name, desc };
    }

    function determineLocators(el, tag, text, label, placeholder) {
        if (el.id && !el.id.includes('dummy') && !el.id.startsWith('pflow') && el.id.length < 50) {
            return { strategy: 'id', value: el.id };
        }
        if (el.classList.contains('mon-hours')) return { strategy: 'css', value: '.hours-input.mon-hours' };
        if (el.classList.contains('tue-hours')) return { strategy: 'css', value: '.hours-input.tue-hours' };
        if (el.classList.contains('wed-hours')) return { strategy: 'css', value: '.hours-input.wed-hours' };
        if (el.classList.contains('thu-hours')) return { strategy: 'css', value: '.hours-input.thu-hours' };
        if (el.classList.contains('fri-hours')) return { strategy: 'css', value: '.hours-input.fri-hours' };
        if (el.classList.contains('sat-hours')) return { strategy: 'css', value: '.hours-input.sat-hours' };
        if (el.classList.contains('sun-hours')) return { strategy: 'css', value: '.hours-input.sun-hours' };
        if (el.classList.contains('project-option')) {
            const clean = text.replace(/[\\u25a0-\\u25ff\\u203a\\n\\r]+/g, ' ').trim();
            return { strategy: 'text', value: clean };
        }
        if (label) return { strategy: 'label', value: label };
        if (placeholder) return { strategy: 'placeholder', value: placeholder };
        if (text && text.length > 0 && text.length <= 40) return { strategy: 'text', value: text };

        const nameAttr = el.getAttribute('name');
        if (nameAttr) return { strategy: 'css', value: `[name="${CSS.escape(nameAttr)}"]` };

        const cls = Array.from(el.classList).filter(c => !c.startsWith('js-') && !c.includes('active') && !c.includes('focus')).slice(0, 2).join('.');
        if (cls) return { strategy: 'css', value: `${tag}.${cls}` };

        return { strategy: 'css', value: tag };
    }

    function extractMetadata(el) {
        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || (tag === 'button' ? 'button' : tag === 'a' ? 'link' : tag === 'input' ? 'textbox' : null);
        const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
        const label = getAssociatedLabel(el) || null;
        const placeholder = el.getAttribute('placeholder') || null;
        const category = getElementCategory(el);

        const parentDialog = el.closest('dialog, [role="dialog"], .ui-dialog, .modal, .t-Dialog-page, .project-picker, .popup-content, .a-Dialog');
        const inDialog = !!parentDialog;
        let dialogTitle = null;
        if (inDialog) {
            const dt = parentDialog.querySelector('.ui-dialog-title, .modal-title, h1, h2, h3, h4');
            dialogTitle = dt ? dt.innerText.trim() : (parentDialog.getAttribute('aria-label') || 'Dialog');
        }

        const { name, desc } = buildFriendlyNameAndDesc(el, tag, category, role, label, text, placeholder);
        const { strategy, value } = determineLocators(el, tag, text, label, placeholder);

        return {
            tag_name: tag,
            category: category,
            role: role,
            label: label,
            placeholder: placeholder,
            friendly_name: name,
            description: desc,
            locator_strategy: strategy,
            locator_value: value,
            in_dialog: inDialog,
            dialog_title: dialogTitle,
            page_url: window.location.href,
            page_title: document.title,
        };
    }

    const captureElemBtn = document.getElementById('vq-btn-capture-element');
    let pickerActive = false;

    function stopPicker() {
        pickerActive = false;
        window.__VERIQON_PICKER_ACTIVE__ = false;
        window.__VERIQON_PICKER_STATUS__ = "idle";
        if (captureElemBtn) {
            captureElemBtn.innerText = '🎯 Capture Any Element';
            captureElemBtn.classList.remove('active-picking');
        }
        if (overlay) overlay.style.display = 'none';
        if (badge) badge.style.display = 'none';

        // Also stop in child iframes
        try {
            document.querySelectorAll('iframe').forEach(f => {
                try {
                    if (f.contentWindow && typeof f.contentWindow.__VERIQON_REMOVE_PICKER__ === 'function') {
                        f.contentWindow.__VERIQON_REMOVE_PICKER__();
                    }
                } catch(e) {}
            });
        } catch(e) {}
    }

    function startPicker() {
        pickerActive = true;
        window.__VERIQON_PICKER_ACTIVE__ = true;
        window.__VERIQON_PICKER_STATUS__ = "picking";
        if (captureElemBtn) {
            captureElemBtn.innerText = '✕ Cancel Selection';
            captureElemBtn.classList.add('active-picking');
        }
        showToast('🎯 Click any element or modal dialog control to capture it');

        // Also propagate to child iframes (Oracle APEX modal pages)
        try {
            document.querySelectorAll('iframe').forEach(f => {
                try {
                    if (f.contentWindow && typeof f.contentWindow.__VERIQON_START_PICKER__ === 'function') {
                        f.contentWindow.__VERIQON_START_PICKER__();
                    }
                } catch(e) {}
            });
        } catch(e) {}
    }

    if (captureElemBtn) {
        captureElemBtn.addEventListener('click', () => {
            if (pickerActive) {
                stopPicker();
            } else {
                startPicker();
            }
        });
    }

    document.addEventListener('mousemove', (e) => {
        if (!pickerActive) return;
        if (e.target.closest('#veriqon-inpage-dock') || e.target.closest('#veriqon-element-modal-overlay')) {
            overlay.style.display = 'none';
            badge.style.display = 'none';
            return;
        }

        const target = findInteractiveTarget(document.elementFromPoint(e.clientX, e.clientY));
        if (!target) {
            overlay.style.display = 'none';
            badge.style.display = 'none';
            return;
        }

        const r = target.getBoundingClientRect();
        overlay.style.top = (r.top - 2) + 'px';
        overlay.style.left = (r.left - 2) + 'px';
        overlay.style.width = (r.width + 4) + 'px';
        overlay.style.height = (r.height + 4) + 'px';
        overlay.style.display = 'block';

        const tag = target.tagName.toLowerCase();
        const role = target.getAttribute('role') || tag;
        const txt = (target.innerText || target.getAttribute('aria-label') || target.getAttribute('placeholder') || target.id || tag).trim().slice(0, 25);
        badge.innerText = `🎯 [${role}] ${txt}`;
        let badgeTop = r.top - 28;
        if (badgeTop < 0) badgeTop = r.bottom + 6;
        badge.style.top = badgeTop + 'px';
        badge.style.left = Math.max(10, r.left) + 'px';
        badge.style.display = 'block';
    }, true);

    document.addEventListener('click', (e) => {
        if (!pickerActive) return;
        if (e.target.closest('#veriqon-inpage-dock') || e.target.closest('#veriqon-element-modal-overlay')) {
            return;
        }

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();

        const target = findInteractiveTarget(document.elementFromPoint(e.clientX, e.clientY));
        if (!target) return;

        const meta = extractMetadata(target);
        if (isChildFrame) {
            meta.in_dialog = true;
            meta.dialog_title = document.title || 'Modal Dialog';
            try {
                meta.page_url = window.top.location.href;
                meta.page_title = window.top.document.title;
            } catch(e) {}
            if (meta.locator_strategy === 'id') {
                meta.locator_strategy = 'css';
                meta.locator_value = `iframe >> #${meta.locator_value}`;
            } else if (meta.locator_strategy === 'css') {
                meta.locator_value = `iframe >> ${meta.locator_value}`;
            } else if (meta.locator_strategy === 'text') {
                meta.locator_strategy = 'css';
                meta.locator_value = `iframe >> text="${meta.locator_value}"`;
            }
        }

        window.__VERIQON_PICKER_RESULT__ = meta;
        window.__VERIQON_PICKER_STATUS__ = "selected";
        stopPicker();

        if (isChildFrame) {
            try {
                if (window.top && typeof window.top.__VERIQON_OPEN_MODAL__ === 'function') {
                    window.top.__VERIQON_OPEN_MODAL__(meta);
                    return;
                }
            } catch(e) {}
        }
        openNamingModal(meta);
    }, true);

    function openNamingModal(meta) {
        const existing = document.getElementById('veriqon-element-modal-overlay');
        if (existing) existing.remove();

        const overlayModal = document.createElement('div');
        overlayModal.id = 'veriqon-element-modal-overlay';
        overlayModal.innerHTML = `
            <div id="veriqon-element-modal">
                <div class="vq-modal-title">
                    <span>🎯 Save Selected Element</span>
                    <button id="vq-modal-close-btn" class="vq-dock-ctrl-btn">✕</button>
                </div>
                <div class="vq-modal-subtitle">Confirm mapped name and save to application catalog</div>

                <div class="vq-chip-row">
                    <span class="vq-chip">&lt;${meta.tag_name}&gt;</span>
                    <span class="vq-chip">${meta.category}</span>
                    ${meta.role ? `<span class="vq-chip">role="${meta.role}"</span>` : ''}
                    ${meta.in_dialog ? `<span class="vq-chip">Modal: ${meta.dialog_title || 'Dialog'}</span>` : ''}
                </div>

                <div class="vq-field-group">
                    <label class="vq-field-label">Mapped Name *</label>
                    <input id="vq-input-name" class="vq-modal-input" value="${(meta.friendly_name || '').replace(/"/g, '&quot;')}" placeholder="e.g. Save Timesheet button" />
                </div>

                <div class="vq-field-group">
                    <label class="vq-field-label">Description (Optional)</label>
                    <input id="vq-input-desc" class="vq-modal-input" value="${(meta.description || '').replace(/"/g, '&quot;')}" placeholder="e.g. Submits the timesheet for the week" />
                </div>

                <div style="font-size:11px; color:#64748b; margin-top:8px;">
                    Locator: <code>${meta.locator_strategy} = ${meta.locator_value}</code>
                </div>

                <div class="vq-modal-actions">
                    <button class="vq-btn-save" id="vq-btn-save-element">Save Element</button>
                    <button class="vq-btn-cancel" id="vq-btn-cancel-modal">Cancel</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlayModal);

        const nameInput = document.getElementById('vq-input-name');
        nameInput.focus();
        nameInput.select();

        const closeModal = () => { overlayModal.remove(); };
        document.getElementById('vq-modal-close-btn').addEventListener('click', closeModal);
        document.getElementById('vq-btn-cancel-modal').addEventListener('click', closeModal);

        async function saveElement() {
            const mappedName = nameInput.value.trim();
            if (!mappedName) {
                nameInput.style.borderColor = '#ef4444';
                return;
            }
            const desc = document.getElementById('vq-input-desc').value.trim();
            const payload = {
                friendly_name: mappedName,
                description: desc,
                category: meta.category,
                tag_name: meta.tag_name,
                role: meta.role,
                label: meta.label,
                placeholder: meta.placeholder,
                locator_strategy: meta.locator_strategy,
                locator_value: meta.locator_value,
                in_dialog: meta.in_dialog,
                dialog_title: meta.dialog_title,
                page_url: meta.page_url,
                page_name: meta.page_title || document.title,
            };

            const saveBtn = document.getElementById('vq-btn-save-element');
            saveBtn.innerText = 'Saving...';
            saveBtn.disabled = true;

            try {
                let resData;
                let ok = true;
                if (typeof window.__veriqon_native_save_element__ === 'function') {
                    resData = await window.__veriqon_native_save_element__(payload);
                } else {
                    const resp = await fetch(`http://127.0.0.1:8000/api/inspector/${encodeURIComponent(projectId)}/save-selected-element`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    ok = resp.ok;
                    resData = await resp.json();
                }
                if (ok && resData && !resData.detail) {
                    saveBtn.innerText = '✓ Saved Successfully!';
                    saveBtn.style.background = '#059669';
                    saveBtn.style.color = '#ffffff';

                    const modalBox = document.getElementById('veriqon-element-modal');
                    if (modalBox) {
                        const successAlert = document.createElement('div');
                        successAlert.id = 'vq-modal-success-banner';
                        successAlert.style.marginTop = '12px';
                        successAlert.style.padding = '10px 14px';
                        successAlert.style.background = 'rgba(16, 185, 129, 0.2)';
                        successAlert.style.border = '1px solid #10b981';
                        successAlert.style.borderRadius = '8px';
                        successAlert.style.color = '#34d399';
                        successAlert.style.fontWeight = '700';
                        successAlert.style.fontSize = '13px';
                        successAlert.style.textAlign = 'center';
                        successAlert.innerHTML = `✓ Saved Successfully!<div style="font-size:11px; font-weight:normal; color:#a7f3d0; margin-top:3px;">"${mappedName}" added to application catalog</div>`;
                        modalBox.appendChild(successAlert);
                    }

                    showToast(`✓ Saved successfully: "${mappedName}"!`);
                    setTimeout(() => {
                        closeModal();
                    }, 850);
                } else {
                    showToast(`Save failed: ${resData?.detail || 'Error'}`, true);
                    saveBtn.innerText = 'Save Element';
                    saveBtn.disabled = false;
                }
            } catch (err) {
                showToast(`Save failed: ${err.message}`, true);
                saveBtn.innerText = 'Save Element';
                saveBtn.disabled = false;
            }
        }

        document.getElementById('vq-btn-save-element').addEventListener('click', saveElement);
        nameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveElement();
            if (e.key === 'Escape') closeModal();
        });
    }

    window.__VERIQON_REMOVE_PICKER__ = stopPicker;
    window.__VERIQON_START_PICKER__ = startPicker;
    window.__VERIQON_OPEN_MODAL__ = openNamingModal;
    } // closes initVeriqonDock

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initVeriqonDock, { once: true });
    } else {
        initVeriqonDock();
    }

    // Keep dock alive on Oracle APEX and SPA page transitions with zero delay
    try {
        const _vqObserver = new MutationObserver(() => {
            if (!document.getElementById('veriqon-inpage-dock') && document.body) {
                initVeriqonDock();
            }
        });
        if (document.documentElement) {
            _vqObserver.observe(document.documentElement, { childList: true, subtree: true });
        }
    } catch (_e) {}
})();"""

PICKER_INJECTION_SCRIPT = INPAGE_CAPTURE_DOCK_SCRIPT


# ---------------------------------------------------------------------------
# Background Proactor Worker Engine (isolated from Uvicorn SelectorEventLoop)
# ---------------------------------------------------------------------------


def bring_browser_to_front_windows(browser_type: str = "", page_title: str = ""):
    """Brings the interactive Playwright browser window to the foreground on Windows desktop."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32

        keywords = ["chrome", "chromium", "firefox", "edge", "webkit", "veriqon", "timesheet", "oracle"]
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
    except Exception as exc:
        logger.debug(f"Failed to bring window to front: {exc}")

class InspectorEngine:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Any] = None
        self.pw: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.headed_browser: Optional[Browser] = None
        self.headed_browsers: Dict[str, Browser] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._ready_event = asyncio.Event()

    def _find_session(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Resolves the live active browser session by project_id, project_name, or active fallback."""
        if project_id and project_id in self.sessions:
            s = self.sessions[project_id]
            if s.get("page") and not s["page"].is_closed():
                return s

        for k, s in self.sessions.items():
            if (k == project_id or s.get("project_id") == project_id or s.get("project_name") == project_id) and s.get("page") and not s["page"].is_closed():
                return s

        # If there is only one active browser session in memory, bind to it
        active_list = [s for s in self.sessions.values() if s.get("page") and not s["page"].is_closed()]
        if len(active_list) == 1:
            return active_list[0]
        return None

    def _start_worker(self):
        import threading
        if self._thread and self._thread.is_alive():
            return

        def _worker_loop():
            # Use Windows ProactorEventLoop where available, otherwise standard event loop
            if sys.platform == "win32" and hasattr(asyncio, "ProactorEventLoop"):
                self._loop = asyncio.ProactorEventLoop()
            else:
                self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._init_playwright())
            self._loop.run_forever()

        self._thread = threading.Thread(target=_worker_loop, daemon=True, name="PlaywrightInspectorWorker")
        self._thread.start()

        # Wait up to 5s for worker loop initialization
        for _ in range(50):
            if self._loop and self.browser:
                break
            time.sleep(0.1)

    async def _init_playwright(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )

    async def get_headed_browser(self, browser_name: str = "chromium") -> Browser:
        b_name = (browser_name or "chromium").lower().strip()

        # Support connecting directly to an existing running Chrome browser (Option B - CDP)
        if b_name in ("cdp", "chrome-cdp", "existing-chrome"):
            try:
                current_b = await self.pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                logger.info("Connected to existing Chrome instance over CDP (port 9222)")
                self.headed_browsers[b_name] = current_b
                self.headed_browser = current_b
                return current_b
            except Exception as e:
                logger.warning(f"Could not connect to existing Chrome over CDP port 9222 ({e}). Launching standard browser.")

        current_b = self.headed_browsers.get(b_name)
        if current_b is None or not current_b.is_connected():
            stealth_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
            ]
            if sys.platform == "win32":
                stealth_args.extend([
                    "--start-maximized",
                    "--window-position=50,50",
                    "--window-size=1440,900",
                ])
            if b_name in ("chrome", "google-chrome"):
                try:
                    current_b = await self.pw.chromium.launch(
                        headless=False,
                        channel="chrome",
                        args=stealth_args
                    )
                except Exception as e:
                    logger.warning(f"Failed to launch Chrome channel ({e}), falling back to chromium")
                    current_b = await self.pw.chromium.launch(
                        headless=False,
                        args=stealth_args
                    )
            elif b_name == "firefox":
                try:
                    current_b = await self.pw.firefox.launch(headless=False)
                except Exception as e:
                    logger.warning(f"Failed to launch Firefox ({e}), falling back to chromium")
                    current_b = await self.pw.chromium.launch(headless=False, args=stealth_args)
            elif b_name == "webkit":
                try:
                    current_b = await self.pw.webkit.launch(headless=False)
                except Exception as e:
                    logger.warning(f"Failed to launch WebKit ({e}), falling back to chromium")
                    current_b = await self.pw.chromium.launch(headless=False, args=stealth_args)
            elif b_name in ("msedge", "edge"):
                try:
                    current_b = await self.pw.chromium.launch(
                        headless=False,
                        channel="msedge",
                        args=stealth_args
                    )
                except Exception:
                    current_b = await self.pw.chromium.launch(headless=False, args=stealth_args)
            else:
                current_b = await self.pw.chromium.launch(
                    headless=False,
                    args=stealth_args
                )
            self.headed_browsers[b_name] = current_b
            self.headed_browser = current_b
        return current_b

    def run_task(self, coro_func, *args, **kwargs):
        """Dispatches an async coroutine to the Proactor worker thread and waits synchronously for result."""
        self._start_worker()
        future = asyncio.run_coroutine_threadsafe(coro_func(*args, **kwargs), self._loop)
        return future.result(timeout=120)

    def _cleanup_expired_sessions(self):
        """Removes sessions inactive for more than 15 minutes (900 seconds)."""
        now = time.time()
        expired = [pid for pid, s in list(self.sessions.items()) if now - s.get("last_active", 0) > 900]
        for pid in expired:
            session = self.sessions.pop(pid, None)
            if session and session.get("page"):
                try:
                    asyncio.create_task(session["page"].close())
                except Exception:
                    pass

    async def _expand_nav(self, page: Page):
        """Fast navigation expander (< 200ms)."""
        nav_toggle_selectors = [
            "#t_Button_navControl",
            "button.a-Button--navControl",
            "button[aria-controls*='TreeNav']",
            "button[aria-controls*='nav' i]",
            "button[aria-label*='Main Navigation' i]",
            "button[aria-label*='navigation' i]",
            "button.navbar-toggler",
            "[data-action='toggle-nav']",
        ]
        for sel in nav_toggle_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    aria_exp = await btn.get_attribute("aria-expanded")
                    if aria_exp == "false":
                        await btn.click()
                        await page.wait_for_timeout(350)
                        break
            except Exception:
                continue

    async def _login_if_needed(self, page: Page, username: str, secret: str) -> bool:
        """Fast login handler supporting Oracle APEX, IDCS, and standard forms."""
        url_lower = page.url.lower()
        if not any(x in url_lower for x in ("login", "signin", "oauth", "authorize")):
            try:
                await page.wait_for_url(lambda u: any(x in u.lower() for x in ("login", "signin", "oauth", "authorize")), timeout=3000)
            except Exception:
                pass
        url_lower = page.url.lower()
        if not any(x in url_lower for x in ("login", "signin", "oauth", "authorize")):
            return False

        try:
            u_sel = "#P9999_USERNAME:visible, input[id*='signin-form-username']:visible, input[id*='username']:visible, input[name='username']:visible, input[placeholder*='user' i]:visible, input[type='text']:visible"
            p_sel = "#P9999_PASSWORD:visible, input[id*='signin-form-password']:visible, input[id*='password']:visible, input[name='password']:visible, input[type='password']:visible, input[placeholder*='pass' i]:visible"
            b_sel = "#B39857664851513779045, #idcs-signin-basic-signin-form-submit:visible, button.t-Button--hot:visible, button:has-text('Sign In'):visible, button:has-text('Sign in'):visible, button:has-text('Log In'):visible, button[type='submit']:visible"

            u_loc = page.locator(u_sel).first
            p_loc = page.locator(p_sel).first
            b_loc = page.locator(b_sel).first

            if await u_loc.count() == 0:
                try:
                    await page.wait_for_selector(u_sel, timeout=8000)
                    u_loc = page.locator(u_sel).first
                    p_loc = page.locator(p_sel).first
                    b_loc = page.locator(b_sel).first
                except Exception:
                    pass

            if await u_loc.count() > 0 and await p_loc.count() > 0:
                await u_loc.fill(username)
                await p_loc.fill(secret)
                await page.wait_for_timeout(400)
                if await b_loc.count() > 0:
                    await b_loc.click()
                else:
                    await p_loc.press("Enter")

                # Wait for navigation away from login and any intermediate transition screens
                start_wait = time.time()
                while time.time() - start_wait < 15:
                    await page.wait_for_timeout(500)
                    cur_url = page.url.lower()
                    cur_title = ""
                    try:
                        cur_title = (await page.title()).lower()
                    except Exception:
                        pass
                    
                    # If Oracle Cloud displays its transitional "Can't connect / Retry" screen, auto-click Retry!
                    if "can't connect" in cur_title:
                        try:
                            retry_btn = page.locator('button:has-text("Retry")').first
                            if await retry_btn.count() > 0:
                                await retry_btn.click()
                                await page.wait_for_timeout(1000)
                                continue
                        except Exception:
                            pass

                    on_login = any(x in cur_url for x in ("/login", "/signin", "oauth2/v1/authorize"))
                    is_transitional = cur_title.startswith("loading ") or cur_title == "" or "can't connect" in cur_title
                    if not on_login and not is_transitional:
                        break

                await page.wait_for_timeout(1000)
                await self._expand_nav(page)
                return True
        except Exception as e:
            logger.warning(f"Fast login failed: {e}")
        return False

    async def inspect(
        self,
        project_id: str,
        project_name: str,
        base_url: str,
        target_url: str,
        viewport: Dict[str, int],
        username: str = "",
        secret: str = "",
        with_login: bool = False,
        expand_navigation: bool = True,
        force_refresh: bool = False,
        preserve_state: bool = True,
    ) -> Dict[str, Any]:
        self._cleanup_expired_sessions()
        base_url = normalize_app_url(base_url)
        target_url = normalize_app_url(target_url)
        session = self.sessions.get(project_id)

        if force_refresh and session:
            try:
                await session["page"].close()
            except Exception:
                pass
            self.sessions.pop(project_id, None)
            session = None

        if not session or session["page"].is_closed():
            # Cold start: create new page context
            page = await self.browser.new_page(
                viewport=viewport,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            )
            await page.goto(target_url, wait_until="domcontentloaded", timeout=35000)

            authenticated = False
            if with_login and username and secret:
                authenticated = await self._login_if_needed(page, username, secret)

            if expand_navigation:
                await self._expand_nav(page)

            session = {
                "session_id": str(uuid.uuid4()),
                "project_id": project_id,
                "project_name": project_name,
                "page": page,
                "base_url": base_url,
                "authenticated": authenticated,
                "created_at": time.time(),
                "last_active": time.time(),
            }
            self.sessions[project_id] = session
        else:
            page = session["page"]
            session["last_active"] = time.time()

            # Warm persistent session: navigate only if preserve_state is False or user explicitly asked for new URL
            if not preserve_state and target_url and target_url != page.url and target_url != base_url:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)

            if with_login and not session.get("authenticated") and username and secret:
                if "login" in page.url.lower():
                    if await self._login_if_needed(page, username, secret):
                        session["authenticated"] = True

            if expand_navigation:
                await self._expand_nav(page)

        # High-speed DOM scan
        scan_res = await page.evaluate(DOM_SCANNER_SCRIPT)
        if isinstance(scan_res, dict):
            raw_elements = scan_res.get("elements", [])
            has_open_dialog = scan_res.get("has_open_dialog", False)
            active_dialog_title = scan_res.get("active_dialog_title", "")
        else:
            raw_elements = scan_res or []
            has_open_dialog = False
            active_dialog_title = ""

        # If page has not rendered interactive elements yet (common for Oracle JET / heavy SPAs)
        if len(raw_elements) == 0:
            try:
                await page.wait_for_selector("input, button, a, [role='button']", state="visible", timeout=6000)
                scan_res = await page.evaluate(DOM_SCANNER_SCRIPT)
                if isinstance(scan_res, dict):
                    raw_elements = scan_res.get("elements", [])
                    has_open_dialog = scan_res.get("has_open_dialog", False)
                    active_dialog_title = scan_res.get("active_dialog_title", "")
                else:
                    raw_elements = scan_res or []
            except Exception:
                pass

        # Scan child frames (e.g. APEX modal dialog pages inside iframes)
        if len(page.frames) > 1:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    f_res = await frame.evaluate(DOM_SCANNER_SCRIPT)
                    if isinstance(f_res, dict):
                        f_elems = f_res.get("elements", [])
                        if f_res.get("has_open_dialog"):
                            has_open_dialog = True
                    else:
                        f_elems = f_res or []
                    for fe in f_elems:
                        fe["in_dialog"] = True
                        fe["dialog_title"] = fe.get("dialog_title") or f"IFrame: {frame.name or 'modal'}"
                        fe["frame_name"] = frame.name
                        fe["frame_url"] = frame.url
                        raw_elements.append(fe)
                except Exception:
                    pass

        # High-speed compressed JPEG screenshot (~20 KB instead of 1.2 MB PNG)
        screenshot_bytes = await page.screenshot(type="jpeg", quality=65)
        screenshot_b64 = f"data:image/jpeg;base64,{base64.b64encode(screenshot_bytes).decode('utf-8')}"

        cat_counts = {
            "buttons": sum(1 for e in raw_elements if e["category"] == "button"),
            "links": sum(1 for e in raw_elements if e["category"] == "link"),
            "inputs": sum(1 for e in raw_elements if e["category"] == "input"),
            "selects": sum(1 for e in raw_elements if e["category"] == "select"),
            "total": len(raw_elements),
        }

        return {
            "project_id": project_id,
            "project_name": project_name,
            "session_id": session.get("session_id", ""),
            "page_url": page.url,
            "page_title": await page.title(),
            "screenshot": screenshot_b64,
            "viewport": viewport,
            "elements": raw_elements,
            "categories_count": cat_counts,
            "authenticated": session.get("authenticated", False),
            "has_open_dialog": has_open_dialog,
            "active_dialog_title": active_dialog_title,
            "session_active": True,
        }

    async def interact(
        self,
        project_id: str,
        project_name: str,
        base_url: str,
        action: str,
        target: Optional[str],
        locator_type: Optional[str],
        value: Optional[str] = None,
        username: str = "",
        secret: str = "",
    ) -> Dict[str, Any]:
        session = self.sessions.get(project_id)
        if not session or session["page"].is_closed():
            # If no active session, start one first
            return await self.inspect(
                project_id=project_id,
                project_name=project_name,
                base_url=base_url,
                target_url=base_url,
                viewport={"width": 1440, "height": 900},
                username=username,
                secret=secret,
                with_login=True,
            )

        page: Page = session["page"]
        session["last_active"] = time.time()

        if action == "login":
            if username and secret:
                if await self._login_if_needed(page, username, secret):
                    session["authenticated"] = True

        elif action == "click" and target:
            clean_target = target.strip()
            clicked = False

            # Check if clearly CSS or ID locator
            if clean_target.startswith("#") or clean_target.startswith(".") or ">>" in clean_target:
                try:
                    loc = page.locator(clean_target).first
                    if await loc.count() > 0:
                        await loc.click(timeout=3000)
                        clicked = True
                except Exception:
                    pass

            # Treeitem check (APEX nav)
            if not clicked:
                try:
                    treeitem = page.get_by_role("treeitem", name=clean_target)
                    if await treeitem.count() > 0 and await treeitem.first.is_visible():
                        await treeitem.first.click(timeout=3000)
                        clicked = True
                except Exception:
                    pass

            # Link check
            if not clicked:
                try:
                    link = page.get_by_role("link", name=clean_target)
                    if await link.count() > 0 and await link.first.is_visible():
                        await link.first.click(timeout=3000)
                        clicked = True
                except Exception:
                    pass

            # Button check
            if not clicked:
                try:
                    btn = page.get_by_role("button", name=clean_target)
                    if await btn.count() > 0 and await btn.first.is_visible():
                        await btn.first.click(timeout=3000)
                        clicked = True
                except Exception:
                    pass

            # Text / option check (e.g. project options)
            if not clicked:
                try:
                    text_loc = page.get_by_text(clean_target, exact=False).first
                    if await text_loc.count() > 0 and await text_loc.is_visible():
                        await text_loc.click(timeout=3000)
                        clicked = True
                except Exception:
                    pass

            # Fast in-page evaluate click fallback
            if not clicked:
                await page.evaluate("""(txt) => {
                    const needle = txt.toLowerCase().trim();
                    const candidates = Array.from(document.querySelectorAll('.project-option, .a-TreeView-label, [role="treeitem"], a, button, .t-Button'));
                    for (const el of candidates) {
                        const val = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (val === needle || val.includes(needle)) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""", clean_target)

            # Wait for modal dialog or DOM mutation
            try:
                await page.wait_for_selector('dialog, [role="dialog"], .ui-dialog, .modal, .project-picker, .project-option, .t-Dialog-page, .mon-hours', timeout=1500, state="visible")
            except Exception:
                pass
            await page.wait_for_timeout(350)
            await self._expand_nav(page)

        elif action == "fill" and target:
            clean_target = target.strip()
            val = value or ""
            filled = False
            for loc_candidate in [page.locator(f"#{clean_target}"), page.locator(clean_target), page.get_by_label(clean_target), page.get_by_placeholder(clean_target)]:
                try:
                    if await loc_candidate.count() > 0 and await loc_candidate.first.is_visible():
                        await loc_candidate.first.fill(val)
                        filled = True
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(200)

        elif action == "navigate" and target:
            dest = target.strip()
            if dest.startswith("/"):
                dest = f"{base_url}{dest}"
            await page.goto(dest, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(300)
            await self._expand_nav(page)

        elif action == "expand_nav":
            await self._expand_nav(page)

        # Return refreshed scan
        scan_res = await page.evaluate(DOM_SCANNER_SCRIPT)
        if isinstance(scan_res, dict):
            raw_elements = scan_res.get("elements", [])
            has_open_dialog = scan_res.get("has_open_dialog", False)
            active_dialog_title = scan_res.get("active_dialog_title", "")
        else:
            raw_elements = scan_res or []
            has_open_dialog = False
            active_dialog_title = ""

        # Scan child frames if any
        if len(page.frames) > 1:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    f_res = await frame.evaluate(DOM_SCANNER_SCRIPT)
                    f_elems = f_res.get("elements", []) if isinstance(f_res, dict) else (f_res or [])
                    if isinstance(f_res, dict) and f_res.get("has_open_dialog"):
                        has_open_dialog = True
                    for fe in f_elems:
                        fe["in_dialog"] = True
                        fe["dialog_title"] = fe.get("dialog_title") or f"IFrame: {frame.name or 'modal'}"
                        raw_elements.append(fe)
                except Exception:
                    pass

        screenshot_bytes = await page.screenshot(type="jpeg", quality=65)
        screenshot_b64 = f"data:image/jpeg;base64,{base64.b64encode(screenshot_bytes).decode('utf-8')}"

        cat_counts = {
            "buttons": sum(1 for e in raw_elements if e["category"] == "button"),
            "links": sum(1 for e in raw_elements if e["category"] == "link"),
            "inputs": sum(1 for e in raw_elements if e["category"] == "input"),
            "selects": sum(1 for e in raw_elements if e["category"] == "select"),
            "total": len(raw_elements),
        }

        return {
            "project_id": project_id,
            "project_name": project_name,
            "session_id": session.get("session_id", ""),
            "page_url": page.url,
            "page_title": await page.title(),
            "screenshot": screenshot_b64,
            "viewport": {"width": 1440, "height": 900},
            "elements": raw_elements,
            "categories_count": cat_counts,
            "authenticated": session.get("authenticated", False),
            "has_open_dialog": has_open_dialog,
            "active_dialog_title": active_dialog_title,
            "session_active": True,
        }

    async def replay_steps(
        self,
        project_id: str,
        project_name: str,
        base_url: str,
        steps: List[Dict[str, Any]],
        username: str = "",
        secret: str = "",
    ) -> Dict[str, Any]:
        """
        Replays preceding workflow steps in the persistent browser inspection session
        to bring the application to the exact state (e.g. open modal/dialog or dynamic row)
        so the user can inspect and pick elements that only appear after prior actions.
        """
        session = self.sessions.get(project_id)
        if not session or session["page"].is_closed():
            # Start fresh session
            await self.inspect(
                project_id=project_id,
                project_name=project_name,
                base_url=base_url,
                target_url=base_url,
                viewport={"width": 1440, "height": 900},
                username=username,
                secret=secret,
                with_login=True,
            )
            session = self.sessions.get(project_id)

        page: Page = session["page"]
        session["last_active"] = time.time()

        for step in steps:
            action_type = step.get("action_type") or step.get("type") or ""
            target = step.get("locator_value") or step.get("target") or step.get("url") or ""
            val = step.get("value") or ""

            # Check if login is needed before executing next step
            if ("login" in page.url.lower() or "signin" in page.url.lower()) and username and secret:
                await self._login_if_needed(page, username, secret)

            try:
                if action_type == "open_app":
                    await page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
                    if ("login" in page.url.lower() or "signin" in page.url.lower()) and username and secret:
                        await self._login_if_needed(page, username, secret)
                    await self._expand_nav(page)

                elif action_type == "login":
                    await self._login_if_needed(page, username, secret)

                elif action_type == "navigate":
                    if target.startswith("/") or target.startswith("http"):
                        dest = target if target.startswith("http") else f"{base_url}{target}"
                        await page.goto(dest, wait_until="domcontentloaded", timeout=20000)
                    else:
                        # Click menu or link
                        for finder in [
                            lambda: page.get_by_role("treeitem", name=target).first,
                            lambda: page.get_by_role("link", name=target).first,
                            lambda: page.get_by_text(target).first,
                        ]:
                            try:
                                loc = finder()
                                if await loc.count() > 0 and await loc.is_visible():
                                    await loc.click(timeout=3000)
                                    break
                            except Exception:
                                pass
                    await page.wait_for_timeout(400)
                    await self._expand_nav(page)

                elif action_type == "click_element":
                    clicked = False
                    for locator_candidate in [
                        page.locator(f"#{target}") if not target.startswith(("#", ".", "[")) else page.locator(target),
                        page.get_by_role("button", name=target),
                        page.get_by_text(target),
                    ]:
                        try:
                            if await locator_candidate.count() > 0 and await locator_candidate.first.is_visible():
                                await locator_candidate.first.click(timeout=3000)
                                clicked = True
                                break
                        except Exception:
                            pass
                    # Wait for modal dialog or DOM update
                    try:
                        await page.wait_for_selector('dialog, [role="dialog"], .ui-dialog, .modal, .project-picker, .project-option, .mon-hours', timeout=1500, state="visible")
                    except Exception:
                        pass
                    await page.wait_for_timeout(300)

                elif action_type == "fill_input":
                    for locator_candidate in [
                        page.locator(f"#{target}") if not target.startswith(("#", ".", "[")) else page.locator(target),
                        page.get_by_label(target),
                        page.get_by_placeholder(target),
                    ]:
                        try:
                            if await locator_candidate.count() > 0 and await locator_candidate.first.is_visible():
                                await locator_candidate.first.fill(val)
                                break
                        except Exception:
                            pass
                    await page.wait_for_timeout(150)

                elif action_type == "select_option":
                    for locator_candidate in [
                        page.locator(f"#{target}") if not target.startswith(("#", ".", "[")) else page.locator(target),
                        page.get_by_label(target),
                    ]:
                        try:
                            if await locator_candidate.count() > 0 and await locator_candidate.first.is_visible():
                                await locator_candidate.first.select_option(label=val)
                                break
                        except Exception:
                            pass
                    await page.wait_for_timeout(150)

                elif action_type == "wait_time":
                    dur = int(step.get("duration", 1000))
                    await page.wait_for_timeout(min(dur, 5000))
            except Exception as step_err:
                logger.warning(f"Step replay error on {action_type}: {step_err}")

        # Scan resulting state
        scan_res = await page.evaluate(DOM_SCANNER_SCRIPT)
        if isinstance(scan_res, dict):
            raw_elements = scan_res.get("elements", [])
            has_open_dialog = scan_res.get("has_open_dialog", False)
            active_dialog_title = scan_res.get("active_dialog_title", "")
        else:
            raw_elements = scan_res or []
            has_open_dialog = False
            active_dialog_title = ""

        # Scan child frames if any
        if len(page.frames) > 1:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    f_res = await frame.evaluate(DOM_SCANNER_SCRIPT)
                    f_elems = f_res.get("elements", []) if isinstance(f_res, dict) else (f_res or [])
                    if isinstance(f_res, dict) and f_res.get("has_open_dialog"):
                        has_open_dialog = True
                    for fe in f_elems:
                        fe["in_dialog"] = True
                        fe["dialog_title"] = fe.get("dialog_title") or f"IFrame: {frame.name or 'modal'}"
                        raw_elements.append(fe)
                except Exception:
                    pass

        screenshot_bytes = await page.screenshot(type="jpeg", quality=65)
        screenshot_b64 = f"data:image/jpeg;base64,{base64.b64encode(screenshot_bytes).decode('utf-8')}"

        cat_counts = {
            "buttons": sum(1 for e in raw_elements if e["category"] == "button"),
            "links": sum(1 for e in raw_elements if e["category"] == "link"),
            "inputs": sum(1 for e in raw_elements if e["category"] == "input"),
            "selects": sum(1 for e in raw_elements if e["category"] == "select"),
            "total": len(raw_elements),
        }

        return {
            "project_id": project_id,
            "project_name": project_name,
            "session_id": session.get("session_id", ""),
            "page_url": page.url,
            "page_title": await page.title(),
            "screenshot": screenshot_b64,
            "viewport": {"width": 1440, "height": 900},
            "elements": raw_elements,
            "categories_count": cat_counts,
            "authenticated": session.get("authenticated", False),
            "has_open_dialog": has_open_dialog,
            "active_dialog_title": active_dialog_title,
            "session_active": True,
        }

    async def get_status(self, project_id: str) -> Dict[str, Any]:
        return await self.get_browser_status(project_id)

    async def start_browser(
        self,
        project_id: str,
        project_name: str,
        base_url: str,
        username: str = "",
        secret: str = "",
        with_login: bool = True,
        visible: bool = True,
        browser_type: str = "chromium",
    ) -> Dict[str, Any]:
        self._cleanup_expired_sessions()
        base_url = normalize_app_url(base_url)
        session = self.sessions.get(project_id)
        browser_type = (browser_type or "chromium").lower().strip()

        dock_init = f"""(() => {{
            window.__VERIQON_PROJECT_ID__ = "{project_id}";
            window.__VERIQON_PROJECT_NAME__ = "{project_name}";
        }})();
        """ + INPAGE_CAPTURE_DOCK_SCRIPT

        # If session already open with same visibility and browser type, bring to front
        if session and not session["page"].is_closed():
            if session.get("visible", False) != visible or session.get("browser_type", "chromium") != browser_type:
                try:
                    await session["page"].close()
                except Exception:
                    pass
                try:
                    if session.get("context"):
                        await session["context"].close()
                except Exception:
                    pass
                old_b_type = session.get("browser_type")
                if old_b_type and old_b_type in self.headed_browsers:
                    try:
                        old_b = self.headed_browsers.pop(old_b_type, None)
                        if old_b and old_b.is_connected():
                            await old_b.close()
                    except Exception:
                        pass
                self.sessions.pop(project_id, None)
                session = None
            else:
                try:
                    current_url = session["page"].url or ""
                    if base_url and not current_url.startswith(base_url.rstrip("/")):
                        await session["page"].goto(base_url, wait_until="commit", timeout=30000)
                    await session["page"].bring_to_front()
                    await session["page"].evaluate(dock_init)
                    title = await session["page"].title()
                    bring_browser_to_front_windows(browser_type, title)
                except Exception:
                    pass
                session["last_active"] = time.time()
                return await self.get_browser_status(project_id)

        # Launch fresh context & page
        if visible:
            browser = await self.get_headed_browser(browser_type)
            if sys.platform == "win32" and browser_type in ("chromium", "chrome", "msedge", "edge"):
                context_args = {"no_viewport": True}
            else:
                context_args = {"viewport": {"width": 1440, "height": 900}}
            if browser_type in ("chromium", "chrome", "msedge", "edge"):
                if sys.platform == "win32":
                    context_args["user_agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                else:
                    context_args["user_agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            context = await browser.new_context(**context_args)
            await context.add_init_script(dock_init)

            # Expose native Python bridge functions to JavaScript (no Mixed Content / CORS issues)
            async def _native_capture_fn(_pid=project_id):
                try:
                    return await self.capture_current_page(project_id, project_name, base_url, username, secret)
                except Exception as exc:
                    logger.error(f"Error in _native_capture_fn: {exc}", exc_info=True)
                    return {"detail": str(exc), "error": True}

            async def _native_save_fn(payload_dict):
                try:
                    logger.info(f"Native save element received: {payload_dict.get('friendly_name')}")
                    try:
                        from dashboard.backend.app.database import SessionLocal
                    except ImportError:
                        from app.database import SessionLocal
                    with SessionLocal() as db_session:
                        res = save_selected_element_internal(project_id, payload_dict, db_session)
                        logger.info(f"Native save result: {res.get('friendly_name')}")
                        return res
                except Exception as exc:
                    logger.error(f"Error in _native_save_fn: {exc}", exc_info=True)
                    return {"detail": str(exc), "error": True}

            try:
                await context.expose_function("__veriqon_native_capture__", _native_capture_fn)
                await context.expose_function("__veriqon_native_save_element__", _native_save_fn)
            except Exception as e:
                logger.warning(f"Could not expose native functions: {e}")

            page = await context.new_page()
        else:
            page = await self.browser.new_page(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            )

        # Register session immediately so browser is tracked and observable
        session = {
            "session_id": str(uuid.uuid4()),
            "project_id": project_id,
            "project_name": project_name,
            "page": page,
            "context": context if visible else None,
            "browser": browser if visible else None,
            "base_url": base_url,
            "browser_type": browser_type,
            "authenticated": False,
            "visible": visible,
            "created_at": time.time(),
            "last_active": time.time(),
            "picker_active": False,
            "selected_element": None,
            "username": username,
            "secret": secret,
        }
        self.sessions[project_id] = session

        authenticated = False
        nav_error = None
        try:
            # Generous 30s timeout so Oracle Cloud and slow networks have time to resolve and redirect
            await page.goto(base_url, wait_until="commit", timeout=30000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass

            if with_login and username and secret:
                authenticated = await self._login_if_needed(page, username, secret)
            await self._expand_nav(page)
            try:
                await page.evaluate(dock_init)
            except Exception:
                pass
        except Exception as e:
            nav_error = str(e)
            logger.warning(f"Browser navigation to '{base_url}' warning/error: {e}")
            # Keep the real browser on the current page; never overwrite with fake error screens

        session["authenticated"] = authenticated
        session["last_active"] = time.time()
        if visible:
            try:
                title = await page.title()
                bring_browser_to_front_windows(browser_type, title)
            except Exception:
                pass
        return await self.get_browser_status(project_id)

    async def navigate_browser(self, project_id: str, new_url: str) -> Dict[str, Any]:
        session = self._find_session(project_id)
        if not session or session["page"].is_closed():
            raise RuntimeError(f"No active browser session for application '{project_id}'.")
        page: Page = session["page"]
        clean = normalize_app_url(new_url.strip())
        session["last_active"] = time.time()
        project_name = session.get("project_name", project_id)
        dock_init = f"""(() => {{
            window.__VERIQON_PROJECT_ID__ = "{project_id}";
            window.__VERIQON_PROJECT_NAME__ = "{project_name}";
        }})();
        """ + INPAGE_CAPTURE_DOCK_SCRIPT

        try:
            # 30s timeout to let live Oracle APEX sessions load cleanly
            await page.goto(clean, wait_until="commit", timeout=30000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass

            # If navigation redirected to login, attempt login with stored credentials
            u = session.get("username", "")
            s = session.get("secret", "")
            if u and s:
                try:
                    await self._login_if_needed(page, u, s)
                except Exception as exc:
                    logger.warning(f"Auto-login on navigation: {exc}")

            await self._expand_nav(page)
            try:
                await page.evaluate(dock_init)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Error navigating to {clean}: {e}")
            # Do NOT overwrite page with fallback HTML - preserve the user's live browser state

        return await self.get_browser_status(project_id)

    async def get_browser_status(self, project_id: str) -> Dict[str, Any]:
        session = self._find_session(project_id)
        if not session or session["page"].is_closed():
            return {
                "active": False,
                "visible": False,
                "project_id": project_id,
                "session_id": "",
                "current_url": "",
                "clean_url": "",
                "display_url": "",
                "page_title": "",
                "page_name": "",
                "picker_active": False,
                "authenticated": False,
                "browser_type": "chromium",
                "is_error_page": False,
                "last_active_seconds_ago": 0,
            }
        page = session["page"]
        raw_url = page.url or ""
        try:
            page_title = await page.title()
        except Exception:
            page_title = ""
        clean_url, page_name = clean_page_identity(raw_url, page_title)
        display_url = redact_sensitive_url(raw_url)
        is_error = raw_url.startswith("chrome-error://") or (raw_url == "about:blank" and not page.is_closed())
        return {
            "active": True,
            "visible": session.get("visible", False),
            "project_id": project_id,
            "session_id": session.get("session_id", ""),
            "current_url": raw_url,
            "clean_url": clean_url,
            "display_url": display_url,
            "page_title": page_title,
            "page_name": page_name,
            "picker_active": session.get("picker_active", False),
            "authenticated": session.get("authenticated", False),
            "browser_type": session.get("browser_type", "chromium"),
            "is_error_page": is_error,
            "last_active_seconds_ago": round(time.time() - session.get("last_active", time.time()), 1),
        }

    async def start_picker(self, project_id: str) -> Dict[str, Any]:
        session = self._find_session(project_id)
        if not session or session["page"].is_closed():
            raise RuntimeError("No active browser session found for this application. Please open the browser first.")
        page: Page = session["page"]
        session["last_active"] = time.time()
        session["picker_active"] = True
        session["selected_element"] = None
        await page.evaluate(PICKER_INJECTION_SCRIPT)
        try:
            await page.evaluate("() => { if (typeof window.__VERIQON_START_PICKER__ === 'function') window.__VERIQON_START_PICKER__(); }")
        except Exception:
            pass
        try:
            await page.bring_to_front()
        except Exception:
            pass
        return {"status": "picking", "active": True}

    async def get_picker_status(self, project_id: str) -> Dict[str, Any]:
        session = self._find_session(project_id)
        if not session or session["page"].is_closed():
            return {"status": "idle", "active": False, "element": None}
        page: Page = session["page"]
        session["last_active"] = time.time()
        try:
            res = await page.evaluate("""() => {
                return {
                    status: window.__VERIQON_PICKER_STATUS__ || 'idle',
                    active: !!window.__VERIQON_PICKER_ACTIVE__,
                    element: window.__VERIQON_PICKER_RESULT__ || null,
                };
            }""")
            return res
        except Exception as e:
            return {"status": "idle", "active": False, "element": None, "error": str(e)}

    async def cancel_picker(self, project_id: str) -> Dict[str, Any]:
        session = self._find_session(project_id)
        if session and not session["page"].is_closed():
            try:
                await session["page"].evaluate("() => { if (window.__VERIQON_REMOVE_PICKER__) window.__VERIQON_REMOVE_PICKER__(); }")
            except Exception:
                pass
            session["picker_active"] = False
            session["selected_element"] = None
        return {"status": "idle", "active": False}

    async def capture_current_page(
        self,
        project_id: str,
        project_name: str,
        base_url: str,
        username: str = "",
        secret: str = "",
        browser_type: str = "chromium",
    ) -> Dict[str, Any]:
        session = self._find_session(project_id)
        if not session or session["page"].is_closed():
            logger.info(f"No active browser session for '{project_id}'; auto-launching browser in visible mode.")
            await self.start_browser(
                project_id=project_id,
                project_name=project_name,
                base_url=base_url,
                username=username,
                secret=secret,
                with_login=True,
                visible=True,
                browser_type=browser_type,
            )
            session = self._find_session(project_id)
            if not session or session["page"].is_closed():
                raise RuntimeError("Failed to auto-launch browser session for capture.")

        page: Page = session["page"]
        session["last_active"] = time.time()

        try:
            scan_res = await page.evaluate(DOM_SCANNER_SCRIPT)
        except Exception as e:
            logger.warning(f"Error evaluating DOM scanner on main frame: {e}")
            scan_res = {}

        if isinstance(scan_res, dict):
            raw_elements = scan_res.get("elements", [])
            has_open_dialog = scan_res.get("has_open_dialog", False)
            active_dialog_title = scan_res.get("active_dialog_title", "")
        else:
            raw_elements = scan_res or []
            has_open_dialog = False
            active_dialog_title = ""

        # Scan child frames (e.g. APEX modal dialog pages inside iframes)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_title = ""
                try:
                    frame_title = await frame.title()
                except Exception:
                    pass
                f_res = await frame.evaluate(DOM_SCANNER_SCRIPT)
                if isinstance(f_res, dict):
                    f_elems = f_res.get("elements", [])
                    if f_elems:
                        has_open_dialog = True
                else:
                    f_elems = f_res or []

                dlg_title = frame_title or f"Modal Dialog ({frame.name or 'iframe'})"
                for fe in f_elems:
                    fe["in_dialog"] = True
                    fe["dialog_title"] = fe.get("dialog_title") or dlg_title
                    fe["frame_name"] = frame.name
                    fe["frame_url"] = frame.url
                    # Scope locators into the iframe so Playwright can click them reliably
                    strat = fe.get("locator_strategy")
                    val = fe.get("locator_value")
                    if strat == "id":
                        fe["locator_strategy"] = "css"
                        fe["locator_value"] = f"iframe >> #{val}"
                    elif strat == "css":
                        fe["locator_value"] = f"iframe >> {val}"
                    elif strat == "text":
                        fe["locator_strategy"] = "css"
                        fe["locator_value"] = f'iframe >> text="{val}"'
                    raw_elements.append(fe)
            except Exception as e:
                logger.warning(f"Error scanning child frame: {e}")

        page_title = ""
        try:
            page_title = await page.title()
        except Exception:
            page_title = ""

        return {
            "project_id": project_id,
            "project_name": project_name,
            "session_id": session.get("session_id", ""),
            "page_url": page.url,
            "page_title": page_title,
            "elements": raw_elements,
            "has_open_dialog": has_open_dialog,
            "active_dialog_title": active_dialog_title,
            "session_active": True,
        }

    async def close_session(self, project_id: str):
        session = self.sessions.pop(project_id, None)
        if session:
            try:
                await session["page"].close()
            except Exception:
                pass


# Global singleton engine
_inspector_engine = InspectorEngine()


# ---------------------------------------------------------------------------
# API Schemas
# ---------------------------------------------------------------------------

class ElementRect(BaseModel):
    x: int
    y: int
    width: int
    height: int
    top: int
    left: int
    right: int
    bottom: int


class InspectElementItem(BaseModel):
    id: str
    friendly_name: str
    category: str
    tag_name: str
    role: Optional[str] = None
    text: str = ""
    label: str = ""
    placeholder: str = ""
    element_id: str = ""
    name_attr: str = ""
    type_attr: str = ""
    locator_strategy: str
    locator_value: str
    suggested_action: str
    in_dialog: bool = False
    dialog_title: str = ""
    frame_name: Optional[str] = None
    frame_url: Optional[str] = None
    rect: ElementRect


class InspectRequest(BaseModel):
    path: Optional[str] = ""
    with_login: bool = True
    expand_navigation: bool = True
    force_refresh: bool = False
    preserve_state: bool = True
    viewport_width: int = 1440
    viewport_height: int = 900


class InspectResponse(BaseModel):
    project_id: str
    project_name: str
    session_id: str = ""
    page_url: str
    page_title: str
    screenshot: str
    viewport: Dict[str, int]
    elements: List[InspectElementItem]
    categories_count: Dict[str, int]
    authenticated: bool = False
    has_open_dialog: bool = False
    active_dialog_title: str = ""
    session_active: bool = True


class InteractRequest(BaseModel):
    action: str
    target: Optional[str] = None
    locator_type: Optional[str] = "smart"
    value: Optional[str] = None


class ReplayStepsRequest(BaseModel):
    steps: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.post("/{project_id}/inspect", response_model=InspectResponse)
def inspect_application_page(
    project_id: str,
    payload: InspectRequest = InspectRequest(),
    db: Session = Depends(get_db),
):
    """
    Renders the target application page, extracts all visible interactive elements,
    and returns a fast visual snapshot for the frontend element picker while reusing
    the persistent browser session.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    base_url = normalize_app_url((project.get("base_url") or "").rstrip("/"))
    if not base_url:
        raise HTTPException(status_code=400, detail="Application does not have a configured base URL.")

    raw_path = (payload.path or "").strip()
    if raw_path.startswith(("http://", "https://")):
        target_url = normalize_app_url(raw_path)
    elif raw_path.startswith("/"):
        target_url = normalize_app_url(f"{base_url}{raw_path}")
    elif raw_path:
        target_url = normalize_app_url(f"{base_url}/{raw_path}")
    else:
        target_url = base_url

    username = ""
    secret = ""
    try:
        creds_list = credentials_service.list_credentials(db, project["id"])
        if creds_list:
            dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
            username = dec.get("username", "")
            secret = dec.get("secret", "")
    except Exception as e:
        logger.warning(f"Could not retrieve credentials: {e}")

    viewport = {"width": payload.viewport_width, "height": payload.viewport_height}

    try:
        data = _inspector_engine.run_task(
            _inspector_engine.inspect,
            project_id=project_id,
            project_name=project.get("name", project_id),
            base_url=base_url,
            target_url=target_url,
            viewport=viewport,
            username=username,
            secret=secret,
            with_login=payload.with_login,
            expand_navigation=payload.expand_navigation,
            force_refresh=payload.force_refresh,
            preserve_state=payload.preserve_state,
        )
        return InspectResponse(**data)
    except Exception as exc:
        logger.error(f"Error in inspector for '{project_id}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unable to inspect application page: {str(exc)}")


@router.post("/{project_id}/interact", response_model=InspectResponse)
def interact_with_inspector(
    project_id: str,
    payload: InteractRequest,
    db: Session = Depends(get_db),
):
    """
    Executes a high-speed action within the active inspector session.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    base_url = (project.get("base_url") or "").rstrip("/")

    username = ""
    secret = ""
    try:
        creds_list = credentials_service.list_credentials(db, project["id"])
        if creds_list:
            dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
            username = dec.get("username", "")
            secret = dec.get("secret", "")
    except Exception:
        pass

    try:
        data = _inspector_engine.run_task(
            _inspector_engine.interact,
            project_id=project_id,
            project_name=project.get("name", project_id),
            base_url=base_url,
            action=payload.action,
            target=payload.target,
            locator_type=payload.locator_type,
            value=payload.value,
            username=username,
            secret=secret,
        )
        return InspectResponse(**data)
    except Exception as exc:
        logger.error(f"Interaction error in inspector: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Interaction error: {str(exc)}")


@router.post("/{project_id}/replay-steps", response_model=InspectResponse)
def replay_workflow_steps(
    project_id: str,
    payload: ReplayStepsRequest,
    db: Session = Depends(get_db),
):
    """
    Replays the specified preceding steps in the persistent inspector browser session,
    enabling element selection inside dynamically opened dialogs, modals, and tables.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    base_url = (project.get("base_url") or "").rstrip("/")

    username = ""
    secret = ""
    try:
        creds_list = credentials_service.list_credentials(db, project["id"])
        if creds_list:
            dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
            username = dec.get("username", "")
            secret = dec.get("secret", "")
    except Exception:
        pass

    try:
        data = _inspector_engine.run_task(
            _inspector_engine.replay_steps,
            project_id=project_id,
            project_name=project.get("name", project_id),
            base_url=base_url,
            steps=payload.steps,
            username=username,
            secret=secret,
        )
        return InspectResponse(**data)
    except Exception as exc:
        logger.error(f"Error replaying steps in inspector: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Replay error: {str(exc)}")


@router.get("/{project_id}/status")
def get_inspector_session_status(project_id: str):
    """Returns the current status of the persistent inspector browser session."""
    try:
        return _inspector_engine.run_task(_inspector_engine.get_status, project_id)
    except Exception as exc:
        return {"active": False, "project_id": project_id, "error": str(exc)}


@router.post("/{project_id}/close")
def close_inspector_session(project_id: str):
    """Closes an active inspection session."""
    try:
        _inspector_engine.run_task(_inspector_engine.close_session, project_id)
    except Exception:
        pass
    return {"status": "closed", "project_id": project_id}


# ---------------------------------------------------------------------------
# Element Discovery: scan + persist to app_elements
# ---------------------------------------------------------------------------

class StartBrowserRequest(BaseModel):
    visible: bool = True
    with_login: bool = True
    browser: Optional[str] = "chromium"
    url: Optional[str] = None


class NavigateRequest(BaseModel):
    url: str
    save_as_default: bool = False
    browser: Optional[str] = None


class SaveSelectedElementRequest(BaseModel):
    friendly_name: str
    description: Optional[str] = ""
    category: str = "other"
    tag_name: str = "div"
    role: Optional[str] = None
    label: Optional[str] = None
    placeholder: Optional[str] = None
    locator_strategy: str
    locator_value: str
    in_dialog: bool = False
    dialog_title: Optional[str] = None
    page_url: str
    page_name: Optional[str] = None


class DiscoverRequest(BaseModel):
    force_refresh: bool = False
    viewport_width: int = 1440
    viewport_height: int = 900


@router.post("/{project_id}/start-browser")
def start_browser_session(
    project_id: str,
    payload: StartBrowserRequest = StartBrowserRequest(),
    db: Session = Depends(get_db),
):
    """
    Launches a real interactive browser window (or headless session) for the application.
    Supports Chromium, Chrome, Firefox, and WebKit engines with custom URL overrides.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    default_base = (project.get("base_url") or "").rstrip("/")
    target_url = (payload.url.strip() if payload.url and payload.url.strip() else default_base)
    target_url = normalize_app_url(target_url)
    if not target_url:
        raise HTTPException(status_code=400, detail="Application does not have a configured base URL.")

    target_browser = (payload.browser or project.get("browser") or "chromium").lower()

    username = ""
    secret = ""
    try:
        creds_list = credentials_service.list_credentials(db, project["id"])
        if creds_list:
            dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
            username = dec.get("username", "")
            secret = dec.get("secret", "")
    except Exception as exc:
        logger.warning(f"Could not retrieve credentials for start-browser: {exc}")

    try:
        return _inspector_engine.run_task(
            _inspector_engine.start_browser,
            project_id=project_id,
            project_name=project.get("name", project_id),
            base_url=target_url,
            username=username,
            secret=secret,
            with_login=payload.with_login,
            visible=payload.visible,
            browser_type=target_browser,
        )
    except Exception as exc:
        logger.error(f"Error starting browser for '{project_id}': {exc}", exc_info=True)
        err_msg = str(exc) or type(exc).__name__
        raise HTTPException(status_code=500, detail=f"Unable to start browser: {err_msg}")


@router.post("/{project_id}/navigate")
def navigate_browser_to_url(
    project_id: str,
    payload: NavigateRequest,
    db: Session = Depends(get_db),
):
    """
    Navigates the active browser session to a new URL, or opens the browser at the new URL if not currently running.
    Optionally persists the new URL as the application's base URL in the database.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    clean_url = payload.url.strip()
    if not clean_url:
        raise HTTPException(status_code=400, detail="Target URL cannot be empty.")

    clean_url = normalize_app_url(clean_url)
    session = _inspector_engine.sessions.get(project_id)

    if not session or session["page"].is_closed():
        # Browser is not open yet; start it directly at this new URL
        target_browser = (payload.browser or project.get("browser") or "chromium").lower()
        res = _inspector_engine.run_task(
            _inspector_engine.start_browser,
            project_id=project_id,
            project_name=project.get("name", project_id),
            base_url=clean_url,
            visible=True,
            browser_type=target_browser,
        )
    else:
        try:
            res = _inspector_engine.run_task(
                _inspector_engine.navigate_browser,
                project_id=project_id,
                new_url=clean_url,
            )
        except Exception as exc:
            logger.warning(f"Navigation warning: {exc}")
            res = _inspector_engine.run_task(_inspector_engine.get_browser_status, project_id)

    if payload.save_as_default:
        db.execute(
            text("UPDATE projects SET base_url = :url, updated_at = NOW() WHERE external_id = :pid"),
            {"url": clean_url, "pid": project_id},
        )
        db.commit()

    return res


@router.get("/{project_id}/browser-status")
def get_browser_session_status(project_id: str):
    """
    Returns live observable status of the browser session: current title, redacted URL,
    clean URL, picker state, and connectivity.
    """
    try:
        return _inspector_engine.run_task(_inspector_engine.get_browser_status, project_id)
    except Exception as exc:
        return {
            "active": False,
            "visible": False,
            "project_id": project_id,
            "current_url": "",
            "clean_url": "",
            "display_url": "",
            "page_title": "",
            "page_name": "",
            "picker_active": False,
            "authenticated": False,
            "browser_type": "chromium",
            "is_error_page": False,
            "error": str(exc),
        }


@router.post("/{project_id}/start-picker")
def start_element_picker(project_id: str):
    """
    Enters element selection mode in the active browser. Injects hover highlight
    and safe click interception overlay so target application actions are not triggered.
    """
    try:
        return _inspector_engine.run_task(_inspector_engine.start_picker, project_id)
    except Exception as exc:
        logger.error(f"Failed to start picker: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{project_id}/picker-status")
def get_element_picker_status(project_id: str):
    """
    Polls the element picker state. Returns 'picking' while waiting, or 'selected'
    with candidate metadata when an element is clicked.
    """
    try:
        return _inspector_engine.run_task(_inspector_engine.get_picker_status, project_id)
    except Exception as exc:
        return {"status": "idle", "active": False, "element": None, "error": str(exc)}


@router.post("/{project_id}/cancel-picker")
def cancel_element_picker(project_id: str):
    """
    Cancels element selection mode and cleans up injected overlays and listeners.
    """
    try:
        return _inspector_engine.run_task(_inspector_engine.cancel_picker, project_id)
    except Exception as exc:
        return {"status": "idle", "active": False, "error": str(exc)}


def save_selected_element_internal(
    project_id: str,
    payload_dict: Dict[str, Any],
    db: Session,
) -> Dict[str, Any]:
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    try:
        proj_uuid = uuid.UUID(str(project["id"]))
    except (ValueError, KeyError):
        raise HTTPException(status_code=500, detail="Invalid project ID format.")

    raw_page_url = payload_dict.get("page_url", "")
    page_name_in = payload_dict.get("page_name") or ""
    clean_url, fallback_page_name = clean_page_identity(raw_page_url, page_name_in)
    page_name = page_name_in or fallback_page_name
    now = datetime.utcnow()

    category = payload_dict.get("category", "other")
    tag_name = payload_dict.get("tag_name", "")

    # Never persist password field values
    if category == "input" and "password" in (tag_name or "").lower():
        raise HTTPException(status_code=400, detail="Password elements cannot be saved.")

    locator_strategy = payload_dict.get("locator_strategy", "")
    locator_value = payload_dict.get("locator_value", "")
    friendly_name = payload_dict.get("friendly_name") or "Element"

    existing = (
        db.query(AppElement)
        .filter(
            AppElement.project_id == proj_uuid,
            AppElement.page_url == clean_url,
            AppElement.locator_strategy == locator_strategy,
            AppElement.locator_value == locator_value,
        )
        .first()
    )

    if existing:
        existing.friendly_name = friendly_name
        existing.description = payload_dict.get("description") or ""
        existing.category = category
        existing.tag_name = tag_name
        existing.role = payload_dict.get("role")
        existing.label = payload_dict.get("label")
        existing.placeholder = payload_dict.get("placeholder")
        existing.in_dialog = bool(payload_dict.get("in_dialog", False))
        existing.dialog_title = payload_dict.get("dialog_title")
        existing.page_name = page_name
        existing.last_verified_at = now
        saved_element = existing
    else:
        new_elem = AppElement(
            id=uuid.uuid4(),
            project_id=proj_uuid,
            page_url=clean_url,
            friendly_name=friendly_name,
            description=payload_dict.get("description") or "",
            category=category,
            tag_name=tag_name,
            role=payload_dict.get("role"),
            label=payload_dict.get("label"),
            placeholder=payload_dict.get("placeholder"),
            locator_strategy=locator_strategy,
            locator_value=locator_value,
            in_dialog=bool(payload_dict.get("in_dialog", False)),
            dialog_title=payload_dict.get("dialog_title"),
            page_name=page_name,
            discovered_at=now,
            last_verified_at=now,
        )
        db.add(new_elem)
        saved_element = new_elem

    try:
        db.commit()
        db.refresh(saved_element)
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to persist selected element: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database save failed: {str(exc)}")

    # Mark picker inactive in session safely without deadlocking the worker loop
    session = _inspector_engine._find_session(project_id)
    if session:
        session["picker_active"] = False

    return {
        "id": str(saved_element.id),
        "project_id": str(saved_element.project_id),
        "page_url": saved_element.page_url,
        "page_name": saved_element.page_name,
        "friendly_name": saved_element.friendly_name,
        "description": saved_element.description or "",
        "category": saved_element.category,
        "tag_name": saved_element.tag_name,
        "role": saved_element.role,
        "label": saved_element.label,
        "placeholder": saved_element.placeholder,
        "locator_strategy": saved_element.locator_strategy,
        "locator_value": saved_element.locator_value,
        "in_dialog": saved_element.in_dialog,
        "dialog_title": saved_element.dialog_title,
        "discovered_at": saved_element.discovered_at.isoformat() if saved_element.discovered_at else None,
    }


@router.post("/{project_id}/save-selected-element")
def save_selected_element(
    project_id: str,
    payload: SaveSelectedElementRequest,
    db: Session = Depends(get_db),
):
    """
    Saves an individually picked element to the app_elements catalog after user confirmation.
    Cleans up any active browser overlay.
    """
    return save_selected_element_internal(project_id, payload.model_dump(), db)


@router.post("/{project_id}/capture-page")
def capture_active_page(
    project_id: str,
    db: Session = Depends(get_db),
):
    """
    Scans the currently rendered page in the active browser session (or starts one)
    and upserts all discovered elements to app_elements table.
    """
    project = db_service.resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Application '{project_id}' not found.")

    base_url = normalize_app_url((project.get("base_url") or "").rstrip("/"))
    if not base_url:
        raise HTTPException(status_code=400, detail="Application does not have a configured base URL.")

    username = ""
    secret = ""
    try:
        creds_list = credentials_service.list_credentials(db, project["id"])
        if creds_list:
            dec = credentials_service.get_decrypted_credential(db, uuid.UUID(creds_list[0]["id"]))
            username = dec.get("username", "")
            secret = dec.get("secret", "")
    except Exception as exc:
        logger.warning(f"Could not retrieve credentials for capture: {exc}")

    try:
        target_browser = (project.get("browser") or "chromium").lower()
        data = _inspector_engine.run_task(
            _inspector_engine.capture_current_page,
            project_id=project_id,
            project_name=project.get("name", project_id),
            base_url=base_url,
            username=username,
            secret=secret,
            browser_type=target_browser,
        )
    except Exception as exc:
        logger.error(f"Error capturing page for '{project_id}': {exc}", exc_info=True)
        err_msg = str(exc) or type(exc).__name__
        raise HTTPException(status_code=500, detail=f"Page capture failed: {err_msg}")

    raw_elements: List[Dict[str, Any]] = data.get("elements", [])
    raw_page_url: str = data.get("page_url", base_url)
    page_title: str = data.get("page_title", "")
    page_url, page_name = clean_page_identity(raw_page_url, page_title)

    if raw_page_url.startswith("chrome-error://") or raw_page_url == "about:blank":
        raise HTTPException(
            status_code=400,
            detail="The browser is currently on an unreachable error page. Please enter a valid URL in the navigation bar to visit and capture your application.",
        )

    try:
        proj_uuid = uuid.UUID(str(project["id"]))
    except (ValueError, KeyError):
        raise HTTPException(status_code=500, detail="Invalid project ID format.")

    inserted_count = 0
    updated_count = 0
    now = datetime.utcnow()

    for el in raw_elements:
        if (el.get("type_attr") or "").lower() == "password":
            continue

        locator_strategy = el.get("locator_strategy", "")
        locator_value = el.get("locator_value", "")
        if not locator_strategy or not locator_value:
            continue

        friendly_name = el.get("friendly_name") or el.get("label") or el.get("text") or locator_value
        description = el.get("description") or ""
        category = el.get("category", "other")
        tag_name = el.get("tag_name", "")
        role = el.get("role") or None
        label = el.get("label") or None
        placeholder = el.get("placeholder") or None
        in_dialog = bool(el.get("in_dialog", False))
        dialog_title = el.get("dialog_title") or None

        existing = (
            db.query(AppElement)
            .filter(
                AppElement.project_id == proj_uuid,
                AppElement.page_url == page_url,
                AppElement.locator_strategy == locator_strategy,
                AppElement.locator_value == locator_value,
            )
            .first()
        )

        if existing:
            existing.friendly_name = friendly_name
            existing.description = description
            existing.category = category
            existing.role = role
            existing.label = label
            existing.placeholder = placeholder
            existing.in_dialog = in_dialog
            existing.dialog_title = dialog_title
            existing.page_name = page_name
            existing.last_verified_at = now
            updated_count += 1
        else:
            new_elem = AppElement(
                id=uuid.uuid4(),
                project_id=proj_uuid,
                page_url=page_url,
                friendly_name=friendly_name,
                description=description,
                category=category,
                tag_name=tag_name,
                role=role,
                label=label,
                placeholder=placeholder,
                locator_strategy=locator_strategy,
                locator_value=locator_value,
                in_dialog=in_dialog,
                dialog_title=dialog_title,
                page_name=page_name,
                discovered_at=now,
                last_verified_at=now,
            )
            db.add(new_elem)
            inserted_count += 1

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"DB commit failed during page capture: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to persist elements: {str(exc)}")

    stored = (
        db.query(AppElement)
        .filter(AppElement.project_id == proj_uuid, AppElement.page_url == page_url)
        .all()
    )

    elements_list = [
        {
            "id": str(e.id),
            "project_id": str(e.project_id),
            "page_url": e.page_url,
            "page_name": e.page_name or page_name,
            "friendly_name": e.friendly_name,
            "description": e.description or "",
            "category": e.category,
            "tag_name": e.tag_name,
            "role": e.role,
            "label": e.label,
            "placeholder": e.placeholder,
            "locator_strategy": e.locator_strategy,
            "locator_value": e.locator_value,
            "in_dialog": e.in_dialog,
            "dialog_title": e.dialog_title,
            "discovered_at": e.discovered_at.isoformat() if e.discovered_at else None,
        }
        for e in stored
    ]

    return {
        "project_id": project_id,
        "page_url": page_url,
        "page_name": page_name,
        "total_scanned": len(raw_elements),
        "inserted": inserted_count,
        "updated": updated_count,
        "elements": elements_list,
    }


@router.post("/{project_id}/discover")
def discover_and_persist_elements(
    project_id: str,
    payload: DiscoverRequest = DiscoverRequest(),
    db: Session = Depends(get_db),
):
    """
    Runs element discovery for the active page and persists all discovered elements.
    Delegates to capture_active_page.
    """
    return capture_active_page(project_id, db)
