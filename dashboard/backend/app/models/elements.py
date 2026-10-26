"""SQLAlchemy models for the Veriqon element system.

Two model classes:
- Element       : Manually-registered named locators used by CSV workflow scenarios.
- AppElement    : Discovered UI elements from live page scans (element catalog).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Element(Base):
    """Named element locator manually registered against a project.

    Used by CSV-driven workflow scenarios to reference reusable selectors.
    """
    __tablename__ = "elements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    page_url = Column(String, nullable=True)
    element_kind = Column(String, nullable=True)
    selector_type = Column(String, nullable=False)
    selector_value = Column(Text, nullable=False)
    fallback_type = Column(String, nullable=True)
    fallback_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_element_name_per_project"),
    )


class AppElement(Base):
    """Discovered UI element captured from a live page scan.

    Records are created/updated by the element-discovery endpoint and stored
    in the element catalog. Never stores passwords or session secrets.
    """
    __tablename__ = "app_elements"

    __table_args__ = (
        UniqueConstraint(
            "project_id", "page_url", "locator_strategy", "locator_value",
            name="uq_element_per_page",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    page_url = Column(String, nullable=False, index=True)
    friendly_name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    tag_name = Column(String, nullable=False)
    role = Column(String, nullable=True)
    label = Column(String, nullable=True)
    placeholder = Column(String, nullable=True)
    locator_strategy = Column(String, nullable=False)
    locator_value = Column(String, nullable=False)
    in_dialog = Column(Boolean, default=False)
    dialog_title = Column(String, nullable=True)
    discovered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_verified_at = Column(DateTime, nullable=True)
    rect_json = Column(Text, nullable=True)
    page_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    project = relationship("Project", back_populates="elements")
