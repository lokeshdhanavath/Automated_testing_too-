"""Element registry schemas."""
import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
SelectorType = Literal["css","xpath","role","label","text","placeholder","id","name","testid"]
class ElementCreate(BaseModel):
    """Creation payload."""
    name: str = Field(min_length=1,max_length=120)
    description: str | None = None
    page_url: str | None = None
    element_kind: str | None = None
    selector_type: SelectorType
    selector_value: str = Field(min_length=1)
    fallback_type: str | None = None
    fallback_value: str | None = None
    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,119}",value):
            raise ValueError("Name must start with a letter; use letters, digits, underscore, or hyphen.")
        return value
class ElementUpdate(BaseModel):
    """Optional element updates."""
    description: str | None = None
    selector_type: SelectorType | None = None
    selector_value: str | None = Field(default=None,min_length=1)
    fallback_type: str | None = None
    fallback_value: str | None = None
class ElementRead(BaseModel):
    """Element response."""
    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    page_url: str | None = None
    element_kind: str | None = None
    selector_type: str
    selector_value: str
    fallback_type: str | None = None
    fallback_value: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}
