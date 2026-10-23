"""
Pytest configuration and shared fixtures for the Timesheet test suite.

Supports project-aware browser launch (headless, browser selection),
conditional screenshot capture, and Playwright video recording.
"""
import os 
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import pytest
from playwright.sync_api import sync_playwright

from utils import config, reporting
from utils.logger import get_run_logger
from pages.login_page import LoginPage
from pages.timesheet_page import TimesheetPage

# ---------- One run ID for the whole session ----------
RUN_ID = os.getenv("DASHBOARD_RUN_ID") or datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)
LOGGER, LOG_PATH = get_run_logger(RUN_ID)

# ---------- Collected results across the session ----------
RESULTS = []


# =====================================================================
# Playwright + browser (session-scoped)
# =====================================================================

@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance):
    browser_type_name = config.BROWSER_NAME if config.BROWSER_NAME in ("chromium", "firefox", "webkit") else "chromium"
    browser_type = getattr(playwright_instance, browser_type_name)

    launch_args = []
    if browser_type_name == "chromium":
        launch_args.extend([
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])

    launch_kwargs = {
        "headless": config.HEADLESS,
        "args": launch_args,
    }
    if browser_type_name == "chromium":
        try:
            browser = browser_type.launch(**launch_kwargs, channel="chrome")
        except Exception:
            browser = browser_type.launch(**launch_kwargs)
    else:
        browser = browser_type.launch(**launch_kwargs)
    yield browser
    browser.close()


# =====================================================================
# Unauthenticated context (for login tests)
# =====================================================================

@pytest.fixture
def context(browser, request):
    context_kwargs = {
        "viewport": {"width": 1400, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }

    if config.CAPTURE_VIDEO:
        config.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        context_kwargs["record_video_dir"] = str(config.VIDEO_DIR)
        context_kwargs["record_video_size"] = {"width": 1280, "height": 720}

    ctx = browser.new_context(**context_kwargs)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context, request):
    """Fresh page, NOT logged in. Use for login / navigation tests."""
    page = context.new_page()
    page.set_default_timeout(30000)

    start = time.time()
    state_changing = bool(getattr(request.node, "state_changing", False))

    yield page

    duration = round(time.time() - start, 2)
    report = getattr(page, "_test_report", {})

    video_path = ""
    try:
        if page.video:
            video_path = str(page.video.path())
    except Exception:
        video_path = ""

    RESULTS.append({
        "name": request.node.nodeid,
        "status": report.get("status", "passed"),
        "duration": duration,
        "error": report.get("error", ""),
        "screenshot": report.get("screenshot", ""),
        "video": video_path,
        "state_changing": state_changing,
    })


# =====================================================================
# Session-scoped logged-in PAGE (login ONCE, reuse the same page)
# =====================================================================

@pytest.fixture(scope="session")
def logged_in_page_obj(browser):
    """
    Log in ONCE and keep the same page alive for the whole session.

    APEX binds its session to the ?session=<token> URL parameter.
    We capture that token after login and reuse it in every navigation.
    """
    context_kwargs = {
        "viewport": {"width": 1400, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }

    if config.CAPTURE_VIDEO:
        config.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        context_kwargs["record_video_dir"] = str(config.VIDEO_DIR)
        context_kwargs["record_video_size"] = {"width": 1280, "height": 720}

    ctx = browser.new_context(**context_kwargs)
    page = ctx.new_page()
    page.set_default_timeout(30000)

    print("\n[setup] Logging in once for the session...")
    lp = LoginPage(page)
    lp.open().login()
    print("[setup] Login OK. URL:", page.url)

    # ---------- Capture the APEX session token from the URL ----------
    session_token = ""
    try:
        qs = parse_qs(urlparse(page.url).query)
        session_token = (qs.get("session") or [""])[0]
    except Exception:
        pass

    if not session_token:
        raise RuntimeError(
            f"Could not find 'session' param in URL after login: {page.url}"
        )

    print(f"[setup] Captured APEX session token: {session_token}")

    page._apex_session = session_token  # type: ignore[attr-defined]
    page._ctx = ctx                     # type: ignore[attr-defined]

    yield page

    try:
        video_path = str(page.video.path()) if page.video else ""
    except Exception:
        video_path = ""

    ctx.close()
    if video_path:
        print(f"\n[teardown] Session video: {video_path}")


@pytest.fixture
def timesheet_page_in_session(logged_in_page_obj, request):
    """
    Reuse the logged-in page. Navigate back to My Timesheet at the start of
    each test, always including the APEX session token, then click
    'This Week' to load the current week's grid.
    """
    page = logged_in_page_obj
    session_token = getattr(page, "_apex_session", "")
    if not session_token:
        raise RuntimeError("No APEX session token captured at login.")

    start = time.time()
    state_changing = bool(getattr(request.node, "state_changing", False))

    timesheet_url = (
        f"{config.BASE_URL}/my-timesheet1?session={session_token}"
    )

    # 1) Navigate to the timesheet page
    page.goto(timesheet_url, wait_until="load", timeout=60000)
    if "/login" in page.url:
        raise RuntimeError(
            f"Session lost — APEX redirected to login. URL: {page.url}"
        )

    # 2) ALWAYS click "This Week" to load the current week's grid
    try:
        page.locator("#p4-current").click(no_wait_after=True)
        page.wait_for_timeout(2500)
    except Exception as e:
        raise RuntimeError(f"Could not click 'This Week' button: {e}")

    tp = TimesheetPage(page)
    tp.wait_until_loaded()

    yield tp

    duration = round(time.time() - start, 2)
    report = getattr(page, "_test_report", {})

    video_path = ""
    try:
        if page.video:
            video_path = str(page.video.path())
    except Exception:
        video_path = ""

    RESULTS.append({
        "name": request.node.nodeid,
        "status": report.get("status", "passed"),
        "duration": duration,
        "error": report.get("error", ""),
        "screenshot": report.get("screenshot", ""),
        "video": video_path,
        "state_changing": state_changing,
    })

    page._test_report = {}


# =====================================================================
# Page objects (for login tests)
# =====================================================================

@pytest.fixture
def login_page(page):
    return LoginPage(page)


@pytest.fixture
def timesheet_page(page):
    return TimesheetPage(page)


# =====================================================================
# Hooks
# =====================================================================

def pytest_collection_modifyitems(config, items):
    for item in items:
        if "state_changing" in item.keywords:
            item.state_changing = True  # type: ignore[attr-defined]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    page = item.funcargs.get("page")
    if page is None:
        tp = item.funcargs.get("timesheet_page_in_session")
        if tp is not None:
            page = tp.page
    if page is None:
        page = item.funcargs.get("logged_in_page_obj")

    if page is None:
        return

    if not hasattr(page, "_test_report"):
        page._test_report = {}

    if report.when == "call":
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in item.name)

        if report.passed:
            page._test_report["status"] = "passed"
            if config.CAPTURE_SCREENSHOTS:
                try:
                    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    shot = config.SCREENSHOT_DIR / f"{safe_name}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    page._test_report["screenshot"] = str(shot)
                except Exception:
                    pass
        elif report.failed:
            page._test_report["status"] = "failed"
            page._test_report["error"] = (
                str(report.longrepr)[:2000] if report.longrepr else ""
            )
            if config.CAPTURE_SCREENSHOTS:
                try:
                    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    shot = config.SCREENSHOT_DIR / f"FAIL_{safe_name}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    page._test_report["screenshot"] = str(shot)
                except Exception:
                    pass
        elif report.skipped:
            page._test_report["status"] = "skipped"


def pytest_sessionstart(session):
    LOGGER.info("=" * 60)
    LOGGER.info("Run ID: %s", RUN_ID)
    LOGGER.info("Starting timesheet test session")
    LOGGER.info("=" * 60)


def pytest_sessionfinish(session, exitstatus):
    if RESULTS:
        reporting.write_reports(RESULTS, run_id=RUN_ID)
        LOGGER.info("Reports written. Run ID: %s", RUN_ID)
        LOGGER.info("Log file: %s", LOG_PATH)
    else:
        LOGGER.info("No test results to write.")
