"""Element Registry API – manually-named locators AND discovered elements (AppElement).

Routes:
  GET  /api/projects/{project_id}/elements          – list discovered elements
  GET  /api/projects/{project_id}/elements?page_url=<url>  – filter by page
  DELETE /api/projects/{project_id}/elements/{element_id}  – remove one record
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import db_service
from app.database import get_db
from app.models.elements import AppElement

router = APIRouter(
    prefix="/api/projects/{project_id}/elements",
    tags=["Element Registry"],
)


def _resolve_project(db: Session, project_id: str) -> dict[str, Any]:
    """Resolve project by UUID or external_id."""
    return db_service.resolve_project(db, project_id)


def _element_to_dict(el: AppElement) -> dict:
    return {
        "id": str(el.id),
        "project_id": str(el.project_id),
        "page_url": el.page_url,
        "page_name": getattr(el, "page_name", None) or "Page",
        "friendly_name": el.friendly_name,
        "description": getattr(el, "description", None) or "",
        "category": el.category,
        "tag_name": el.tag_name,
        "role": el.role,
        "label": el.label,
        "placeholder": el.placeholder,
        "locator_strategy": el.locator_strategy,
        "locator_value": el.locator_value,
        "in_dialog": el.in_dialog,
        "dialog_title": el.dialog_title,
        "discovered_at": el.discovered_at.isoformat() if el.discovered_at else None,
        "last_verified_at": el.last_verified_at.isoformat() if el.last_verified_at else None,
    }


@router.get("/pages", summary="List captured pages for a project with element counts")
def list_captured_pages(
    project_id: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    """List distinct captured pages for a project with human-readable names and counts."""
    project = _resolve_project(db, project_id)
    pid = UUID(str(project["id"]))

    from sqlalchemy import func
    rows = (
        db.query(
            AppElement.page_url,
            func.coalesce(func.max(AppElement.page_name), 'Page').label('page_name'),
            func.count(AppElement.id).label('element_count'),
            func.max(AppElement.discovered_at).label('last_captured_at'),
        )
        .filter(AppElement.project_id == pid)
        .group_by(AppElement.page_url)
        .order_by(func.max(AppElement.discovered_at).desc())
        .all()
    )

    return [
        {
            "page_url": r.page_url,
            "page_name": r.page_name or "Page",
            "element_count": r.element_count,
            "last_captured_at": r.last_captured_at.isoformat() if r.last_captured_at else None,
        }
        for r in rows
    ]


@router.get("", summary="List discovered elements for a project")
def list_elements(
    project_id: str,
    page_url: Optional[str] = None,
    search: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return all discovered elements for a project, with optional filters."""
    project = _resolve_project(db, project_id)
    pid = UUID(str(project["id"]))

    q = db.query(AppElement).filter(AppElement.project_id == pid)

    if page_url and isinstance(page_url, str):
        q = q.filter(AppElement.page_url == page_url)
    if category and isinstance(category, str):
        q = q.filter(AppElement.category == category.lower())
    if search and isinstance(search, str):
        q = q.filter(AppElement.friendly_name.ilike(f"%{search}%"))

    elements = q.order_by(AppElement.category, AppElement.friendly_name).all()
    return [_element_to_dict(e) for e in elements]


@router.get("/{element_id}", summary="Get a single discovered element")
def get_element(
    project_id: str,
    element_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    project = _resolve_project(db, project_id)
    pid = UUID(str(project["id"]))

    el = db.query(AppElement).filter(
        AppElement.id == element_id,
        AppElement.project_id == pid,
    ).first()

    if not el:
        raise HTTPException(status_code=404, detail="Element not found.")

    return _element_to_dict(el)


@router.delete("/{element_id}", status_code=204, summary="Delete a discovered element")
def delete_element(
    project_id: str,
    element_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    project = _resolve_project(db, project_id)
    pid = UUID(str(project["id"]))

    el = db.query(AppElement).filter(
        AppElement.id == element_id,
        AppElement.project_id == pid,
    ).first()

    if not el:
        raise HTTPException(status_code=404, detail="Element not found.")

    db.delete(el)
    db.commit()


# Alias router for /api/elements/{project_id} compatibility
elements_alias_router = APIRouter(
    prefix="/api/elements",
    tags=["Element Registry"],
)

@elements_alias_router.get("/{project_id}", summary="List elements for a project (compat alias)")
def list_elements_compat(
    project_id: str,
    page_url: Optional[str] = None,
    search: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_elements(project_id=project_id, page_url=page_url, search=search, category=category, db=db)


@elements_alias_router.get("/{project_id}/pages", summary="List captured pages (compat alias)")
def list_captured_pages_compat(
    project_id: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_captured_pages(project_id=project_id, db=db)

