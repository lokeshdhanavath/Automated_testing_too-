"""
Migration runner for Veriqon PostgreSQL database.
Executes versioned SQL migrations using the configured SQLAlchemy engine.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import engine
from sqlalchemy import text


def run_migrations():
    migration_file = Path(__file__).parent / "002_generic_scenario_platform.sql"
    if not migration_file.exists():
        raise FileNotFoundError(f"Migration file not found: {migration_file}")

    sql_statements = migration_file.read_text(encoding="utf-8")
    print(f"Applying migration: {migration_file.name} ...")

    with engine.begin() as conn:
        # Split statements by semicolon where appropriate, or execute the block
        conn.execute(text(sql_statements))

    print("Migration applied successfully!")


if __name__ == "__main__":
    run_migrations()

