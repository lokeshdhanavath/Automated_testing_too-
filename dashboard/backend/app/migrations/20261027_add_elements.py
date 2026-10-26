"""
Migration: Add app_elements table for Veriqon element discovery catalog.
Executed by run_migrations.py via .up(conn).
"""
from sqlalchemy import text


def up(conn):
    """Create app_elements table and indexes if they do not already exist."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS app_elements (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            page_url        TEXT NOT NULL,
            friendly_name   TEXT NOT NULL,
            category        TEXT NOT NULL,
            tag_name        TEXT NOT NULL,
            role            TEXT,
            label           TEXT,
            placeholder     TEXT,
            locator_strategy TEXT NOT NULL,
            locator_value   TEXT NOT NULL,
            in_dialog       BOOLEAN NOT NULL DEFAULT FALSE,
            dialog_title    TEXT,
            discovered_at   TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            last_verified_at TIMESTAMP WITHOUT TIME ZONE,
            rect_json       TEXT,
            page_name       TEXT,
            description     TEXT,
            CONSTRAINT uq_element_per_page
                UNIQUE (project_id, page_url, locator_strategy, locator_value)
        );
    """))

    conn.execute(text("""
        ALTER TABLE app_elements ADD COLUMN IF NOT EXISTS page_name TEXT;
        ALTER TABLE app_elements ADD COLUMN IF NOT EXISTS description TEXT;
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_app_elements_project_id
            ON app_elements (project_id);
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_app_elements_page_url
            ON app_elements (page_url);
    """))

    print("  [20261027_add_elements] app_elements table ready.")


def down(conn):
    """Drop app_elements table."""
    conn.execute(text("DROP TABLE IF EXISTS app_elements CASCADE;"))
    print("  [20261027_add_elements] app_elements table dropped.")
