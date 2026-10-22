# Veriqon Automated Testing Platform for Oracle APEX

Automated end-to-end testing suite and web dashboard for Oracle APEX Timesheet application.

---

## Architecture Overview

- **Backend**: FastAPI (`dashboard/backend/app`) providing REST APIs for:
  - Pytest test discovery and execution (`/api/test-cases`, `/api/runs`)
  - Test script viewing, creation, and editing (`/api/scripts`)
  - CSV scenario upload, validation, and test execution (`/api/csv-scenarios`)
  - Project configuration and environment management (`/api/projects`)
- **Frontend**: React 19 + TypeScript + Vite (`dashboard/frontend`) providing a UI:
  - Projects Workspace
  - Test Suites Catalog & Runner
  - CSV Scenarios Importer & Runner
  - Execution History, Logs & Artifacts (HTML reports, videos, screenshots)
- **Test Automation Engine**: Playwright + Pytest (`tests/`, `pages/`, `utils/`)
  - Page Object Model (`LoginPage`, `TimesheetPage`)
  - Session reuse for fast APEX authenticated testing
  - Multi-format test reporting (HTML, JUnit XML, JSON, CSV, Videos, Screenshots)

---

## Quick Start

### 1. Launch the Full Application (Backend + Frontend)
Double-click `run_dashboard.bat` or run:
```bash
python run_dashboard.py
```
- **Frontend UI**: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- **Backend API**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API Docs (Swagger)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

### 2. Run Tests via CLI

Run all tests:
```bash
python run_all.py
```

Run a specific test file:
```bash
python run_all.py tests/test_login.py
```

Run tests matching a keyword:
```bash
python run_all.py -k login
```

---

## Configuration

Credentials and base URLs are configured in `.env`:
```ini
APEX_USERNAME=<username>
APEX_PASSWORD=<password>
APEX_BASE_URL=https://oracleapex.com/ords/r/lokesh354/timesheet-application
```
Project settings are persisted in `config/projects.json`.
- **Backend**: FastAPI (`dashboard/backend/app`) providing REST APIs for:
  - Pytest test discovery and execution (`/api/test-cases`, `/api/runs`)
  - Test script viewing, creation, and editing (`/api/scripts`)
  - CSV scenario upload, validation, and test execution (`/api/csv-scenarios`)
  - Project configuration and environment management (`/api/projects`)
- **Frontend**: React 19 + TypeScript + Vite (`dashboard/frontend`) providing a UI:
  - Projects Workspace
  - Test Suites Catalog & Runner
  - CSV Scenarios Importer & Runner
  - Execution History, Logs & Artifacts (HTML reports, videos, screenshots)
- **Test Automation Engine**: Playwright + Pytest (`tests/`, `pages/`, `utils/`)
  - Page Object Model (`LoginPage`, `TimesheetPage`)
  - Session reuse for fast APEX authenticated testing
  - Multi-format test reporting (HTML, JUnit XML, JSON, CSV, Videos, Screenshots)

---

## Quick Start

### 1. Launch the Full Application (Backend + Frontend)
Double-click `run_dashboard.bat` or run:
```bash
python run_dashboard.py
```
- **Frontend UI**: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- **Backend API**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API Docs (Swagger)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

### 2. Run Tests via CLI

Run all tests:
```bash
python run_all.py
```

Run a specific test file:
```bash
python run_all.py tests/test_login.py
```

Run tests matching a keyword:
```bash
python run_all.py -k login
```

---

## Configuration

Credentials and base URLs are configured in `.env`:
```ini
APEX_USERNAME=<username>
APEX_PASSWORD=<password>
APEX_BASE_URL=https://oracleapex.com/ords/r/lokesh354/timesheet-application
```
Project settings are persisted in `config/projects.json`.
