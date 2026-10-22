import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root: Automated_testing_too-
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ---------- Project & Run Execution Context ----------
PROJECT_ID = os.getenv("VERIQON_PROJECT_ID")
RUN_ID = os.getenv("DASHBOARD_RUN_ID")

HEADLESS = os.getenv("VERIQON_HEADLESS", "true").lower() in ("true", "1", "yes")
BROWSER_NAME = os.getenv("VERIQON_BROWSER", "chromium").lower()
CAPTURE_SCREENSHOTS = os.getenv("VERIQON_CAPTURE_SCREENSHOTS", "true").lower() in ("true", "1", "yes")
CAPTURE_VIDEO = os.getenv("VERIQON_CAPTURE_VIDEO", "false").lower() in ("true", "1", "yes")

# ---------- Credentials & Base URL ----------
BASE_URL = (os.getenv("VERIQON_BASE_URL") or os.getenv("APEX_BASE_URL") or "").rstrip("/")
USERNAME = os.getenv("VERIQON_USERNAME") or os.getenv("APEX_USERNAME") or ""
PASSWORD = os.getenv("VERIQON_PASSWORD") or os.getenv("APEX_PASSWORD") or ""

LOGIN_URL = f"{BASE_URL}/login" if BASE_URL else ""

# ---------- Output directories (isolated per project & run when running from dashboard) ----------
if PROJECT_ID and RUN_ID:
    ARTIFACTS_RUN_DIR = ROOT / "artifacts" / PROJECT_ID / RUN_ID
    VIDEO_DIR = ARTIFACTS_RUN_DIR / "videos"
    SCREENSHOT_DIR = ARTIFACTS_RUN_DIR / "screenshots"
    REPORTS_DIR = ARTIFACTS_RUN_DIR / "reports"
    HTML_REPORT_DIR = REPORTS_DIR / "html"
    JSON_REPORT_DIR = REPORTS_DIR / "json"
    CSV_REPORT_DIR = REPORTS_DIR / "csv"
else:
    VIDEO_DIR = ROOT / "videos"
    SCREENSHOT_DIR = ROOT / "screenshots"
    REPORTS_DIR = ROOT / "reports"
    HTML_REPORT_DIR = REPORTS_DIR / "html"
    JSON_REPORT_DIR = REPORTS_DIR / "json"
    CSV_REPORT_DIR = REPORTS_DIR / "csv"

HISTORY_DIR = ROOT / "history"

for d in (VIDEO_DIR, SCREENSHOT_DIR, HTML_REPORT_DIR,
          JSON_REPORT_DIR, CSV_REPORT_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)


def mask(value: str) -> str:
    """Return a masked version of a secret for safe logging."""
    if not value:
        return ""
    return value[0] + "*" * (len(value) - 1)
