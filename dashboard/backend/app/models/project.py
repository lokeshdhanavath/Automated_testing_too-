"""Project SQLAlchemy model for relationship mappings."""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Project(Base):
    """Registered application project in Veriqon."""
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    project_type = Column(String(50), default="Web application")
    base_url = Column(String(2048), nullable=False)
    test_directory = Column(String(240), default="tests")
    default_environment = Column(String(50), default="QA")
    browser = Column(String(50), default="chromium")
    headless = Column(Boolean, default=True)
    capture_screenshots = Column(Boolean, default=True)
    capture_video = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    elements = relationship(
        "AppElement",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

