"""
Credentials service for Veriqon.
Handles authenticated symmetric encryption (Fernet) and decryption of sensitive secrets.
Secrets are never logged, returned plaintext in APIs, or committed to disk unencrypted.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def _get_fernet() -> Fernet:
    key = os.environ.get("VERIQON_ENCRYPTION_KEY")
    if not key:
        # Fallback or error if missing
        raise RuntimeError(
            "VERIQON_ENCRYPTION_KEY is missing from environment. "
            "Please ensure it is defined in .env."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(secret: str) -> str:
    """Encrypt a secret string into an authenticated Fernet token."""
    if not secret:
        return ""
    f = _get_fernet()
    return f.encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted_token: str) -> str:
    """Decrypt a Fernet token back into plaintext."""
    if not encrypted_token:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to decrypt credentials. The encryption key may have changed."
        ) from exc


def mask_secret(secret: str) -> str:
    """Generate a masked representation of a secret string."""
    if not secret:
        return ""
    length = len(secret)
    if length <= 2:
        return "****"
    return secret[0] + ("*" * min(max(length - 2, 4), 10)) + secret[-1]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_credential(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    username: str,
    secret: str,
    environment: str = "QA",
    description: str | None = None,
    credential_type: str = "username_password",
) -> dict[str, Any]:
    """Store an encrypted credential record in PostgreSQL."""
    name = name.strip()
    username = username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Credential name is required.")
    if not username:
        raise HTTPException(status_code=400, detail="Username is required.")
    if not secret:
        raise HTTPException(status_code=400, detail="Password/Secret is required.")

    # Check for existing with same name in project
    existing = db.execute(
        text("SELECT id FROM app_credentials WHERE project_id = :pid AND name = :name"),
        {"pid": project_id, "name": name},
    ).scalar()
    if existing:
        raise HTTPException(status_code=409, detail=f"A credential named '{name}' already exists for this application.")

    encrypted_val = encrypt_secret(secret)
    masked_val = mask_secret(secret)
    now = _now()
    cred_id = uuid.uuid4()

    db.execute(
        text("""
            INSERT INTO app_credentials (
                id, project_id, name, credential_type, username,
                encrypted_secret, masked_secret, description, environment,
                created_at, updated_at
            )
            VALUES (
                :id, :project_id, :name, :credential_type, :username,
                :encrypted_secret, :masked_secret, :description, :environment,
                :created_at, :updated_at
            )
        """),
        {
            "id": cred_id,
            "project_id": project_id,
            "name": name,
            "credential_type": credential_type,
            "username": username,
            "encrypted_secret": encrypted_val,
            "masked_secret": masked_val,
            "description": description,
            "environment": environment,
            "created_at": now,
            "updated_at": now,
        },
    )
    db.commit()

    return {
        "id": str(cred_id),
        "project_id": str(project_id),
        "name": name,
        "credential_type": credential_type,
        "username": username,
        "masked_secret": masked_val,
        "description": description or "",
        "environment": environment,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def list_credentials(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return all credentials for a project with masked secrets (never plaintext)."""
    rows = db.execute(
        text("""
            SELECT id, project_id, name, credential_type, username,
                   masked_secret, description, environment, created_at, updated_at
            FROM app_credentials
            WHERE project_id = :pid
            ORDER BY created_at ASC
        """),
        {"pid": project_id},
    ).mappings().all()

    results = []
    for row in rows:
        item = dict(row)
        item["id"] = str(item["id"])
        item["project_id"] = str(item["project_id"])
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else ""
        item["updated_at"] = item["updated_at"].isoformat() if item["updated_at"] else ""
        results.append(item)
    return results


def update_credential(
    db: Session,
    credential_id: uuid.UUID,
    name: str | None = None,
    username: str | None = None,
    secret: str | None = None,
    environment: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update a credential. Re-encrypts secret only if a new non-empty secret is provided."""
    row = db.execute(
        text("SELECT * FROM app_credentials WHERE id = :id"),
        {"id": credential_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Credential not found.")

    updates = ["updated_at = :now"]
    params: dict[str, Any] = {"id": credential_id, "now": _now()}

    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty.")
        updates.append("name = :name")
        params["name"] = name

    if username is not None:
        username = username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty.")
        updates.append("username = :username")
        params["username"] = username

    if secret is not None and secret.strip():
        encrypted_val = encrypt_secret(secret.strip())
        masked_val = mask_secret(secret.strip())
        updates.append("encrypted_secret = :enc")
        updates.append("masked_secret = :masked")
        params["enc"] = encrypted_val
        params["masked"] = masked_val

    if environment is not None:
        updates.append("environment = :environment")
        params["environment"] = environment

    if description is not None:
        updates.append("description = :description")
        params["description"] = description

    stmt = f"UPDATE app_credentials SET {', '.join(updates)} WHERE id = :id RETURNING id, project_id, name, credential_type, username, masked_secret, description, environment, created_at, updated_at"
    updated_row = db.execute(text(stmt), params).mappings().first()
    db.commit()

    res = dict(updated_row)
    res["id"] = str(res["id"])
    res["project_id"] = str(res["project_id"])
    res["created_at"] = res["created_at"].isoformat() if res["created_at"] else ""
    res["updated_at"] = res["updated_at"].isoformat() if res["updated_at"] else ""
    return res


def delete_credential(db: Session, credential_id: uuid.UUID) -> bool:
    """Delete a credential record."""
    res = db.execute(
        text("DELETE FROM app_credentials WHERE id = :id"),
        {"id": credential_id},
    )
    db.commit()
    return res.rowcount > 0


def get_decrypted_credential(db: Session, credential_id: uuid.UUID) -> dict[str, str]:
    """Internal helper to retrieve decrypted username and password for test execution."""
    row = db.execute(
        text("SELECT username, encrypted_secret FROM app_credentials WHERE id = :id"),
        {"id": credential_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Credential not found.")

    plain_secret = decrypt_secret(row["encrypted_secret"])
    return {
        "username": row["username"],
        "secret": plain_secret,
    }
