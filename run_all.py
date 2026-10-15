"""
Single entry point for running the Timesheet test suite.

Usage:
    python run_all.py                # run all tests
    python run_all.py tests/test_login.py    # run one file
    python run_all.py -k login       # run tests matching 'login'
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def banner(text: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{text}\n{line}")


def main():
    args = sys.argv[1:]
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    banner(f"Timesheet Test Run — {run_id}")
    print(f"Working dir : {ROOT}")

    cmd = [sys.executable, "-m", "pytest", *args]
    print(f"Command     : {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=ROOT)

    banner(f"Run finished — exit code {result.returncode}")
    print(f"HTML  : {ROOT / 'reports' / 'html' / 'report.html'}")
    print(f"JSON  : {ROOT / 'reports' / 'json'}")
    print(f"CSV   : {ROOT / 'reports' / 'csv'}")
    print(f"LOG   : {ROOT / 'reports' / 'logs'}")
    print(f"VIDEO : {ROOT / 'videos'}")
    print(f"SHOTS : {ROOT / 'screenshots'}")
    print(f"HIST  : {ROOT / 'history' / 'runs.jsonl'}")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()