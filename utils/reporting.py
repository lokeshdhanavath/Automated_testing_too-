"""
Helpers for writing JSON/CSV reports and appending to history.
Called from a pytest hook in tests/conftest.py.
"""
import csv
import json
import platform
import sys
from datetime import datetime
from pathlib import Path

from utils import config


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_reports(test_results: list, run_id: str = None):
    """
    test_results: list of dicts with keys:
        name, status, duration, error, screenshot, video, state_changing
    """
    run_id = run_id or _new_run_id()
    timestamp = datetime.now().isoformat(timespec="seconds")

    env_info = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "run_id": run_id,
        "timestamp": timestamp,
    }

    summary = {
        "run_id": run_id,
        "timestamp": timestamp,
        "environment": env_info,
        "total": len(test_results),
        "passed": sum(1 for r in test_results if r["status"] == "passed"),
        "failed": sum(1 for r in test_results if r["status"] == "failed"),
        "skipped": sum(1 for r in test_results if r["status"] == "skipped"),
        "errors": sum(1 for r in test_results if r["status"] == "error"),
        "tests": test_results,
    }

    # ---------- JSON ----------
    json_path = config.JSON_REPORT_DIR / f"run_{run_id}.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # ---------- CSV ----------
    csv_path = config.CSV_REPORT_DIR / f"run_{run_id}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name", "status", "duration", "error",
                "screenshot", "video", "state_changing",
            ],
        )
        writer.writeheader()
        for r in test_results:
            writer.writerow({k: r.get(k, "") for k in writer.fieldnames})

    # ---------- History (append one line per run) ----------
    history_path = config.HISTORY_DIR / "runs.jsonl"
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "run_id": run_id,
            "timestamp": timestamp,
            "total": summary["total"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "skipped": summary["skipped"],
            "errors": summary["errors"],
        }) + "\n")

    print(f"\n[reports] JSON : {json_path}")
    print(f"[reports] CSV  : {csv_path}")
    print(f"[reports] HIST : {history_path}")
    return run_id