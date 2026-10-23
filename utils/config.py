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

# ---------- Credentials & Base URL Retrieval ----------
BASE_URL = (os.getenv("VERIQON_BASE_URL") or "").rstrip("/")
USERNAME = os.getenv("VERIQON_USERNAME") or ""
PASSWORD = os.getenv("VERIQON_PASSWORD") or ""


def _load_db_credentials_fallback() -> tuple[str, str, str]:
    """
    Fallback resolver that retrieves credentials directly from PostgreSQL
    when tests are executed outside the dashboard (e.g. standalone pytest CLI).
    """
    try:
        db_url = os.getenv("DATABASE_URL")
        enc_key = os.getenv("VERIQON_ENCRYPTION_KEY")
        if not db_url or not enc_key:
            return "", "", ""

        from sqlalchemy import create_engine, text
        from cryptography.fernet import Fernet

        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            proj_id = os.getenv("VERIQON_PROJECT_ID")
            if proj_id:
                p_row = conn.execute(
                    text("SELECT id, base_url FROM projects WHERE external_id = :p OR id::text = :p"),
                    {"p": proj_id},
                ).mappings().first()
            else:
                p_row = conn.execute(
                    text("SELECT id, base_url FROM projects WHERE is_active = TRUE ORDER BY is_default DESC, created_at ASC LIMIT 1")
                ).mappings().first()

            if not p_row:
                return "", "", ""

            resolved_base_url = p_row["base_url"] or ""
            c_row = conn.execute(
                text("SELECT username, encrypted_secret FROM app_credentials WHERE project_id = :pid ORDER BY created_at ASC LIMIT 1"),
                {"pid": p_row["id"]},
            ).mappings().first()

            if not c_row:
                return resolved_base_url, "", ""

            f = Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
            plain_pass = (
                f.decrypt(c_row["encrypted_secret"].encode("utf-8")).decode("utf-8")
                if c_row["encrypted_secret"]
                else ""
            )
            return resolved_base_url, c_row["username"] or "", plain_pass
    except Exception:
        return "", "", ""


# If not set in environment (e.g. CLI run), resolve dynamically from the database
if not (BASE_URL and USERNAME and PASSWORD):
    _db_url, _db_user, _db_pass = _load_db_credentials_fallback()
    if not BASE_URL:
        BASE_URL = _db_url.rstrip("/")
    if not USERNAME:
        USERNAME = _db_user
    if not PASSWORD:
        PASSWORD = _db_pass

# Determine LOGIN_URL: only append /login for apex-timesheet if needed.
# For generic web apps (like Oracle HCM Cloud), the entry point is BASE_URL itself.
if PROJECT_ID == "apex-timesheet":
    LOGIN_URL = f"{BASE_URL}/login" if BASE_URL and not BASE_URL.endswith("/login") else (BASE_URL or "")
else:
    LOGIN_URL = BASE_URL or ""

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
