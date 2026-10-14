import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ---------- Credentials (never printed) ----------
USERNAME = os.getenv("APEX_USERNAME")
PASSWORD = os.getenv("APEX_PASSWORD")
BASE_URL = os.getenv("APEX_BASE_URL", "").rstrip("/")

if not (USERNAME and PASSWORD and BASE_URL):
    raise RuntimeError(
        "Missing APEX_USERNAME / APEX_PASSWORD / APEX_BASE_URL in .env"
    )

LOGIN_URL = f"{BASE_URL}/login"

# ---------- Output directories ----------
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