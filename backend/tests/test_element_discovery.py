"""
Integration tests for Veriqon Element Discovery & Catalog Persistence API.
Phase 1.1: Page-wise element capture, natural friendly names, page-list API.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from app.database import SessionLocal
from app.inspector_api import discover_and_persist_elements, DiscoverRequest, clean_page_identity
from app.elements_api import list_elements, list_captured_pages
from app.models.elements import AppElement
from fastapi import HTTPException


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_clean_page_identity():
    """Verify volatile session tokens are stripped and page names are derived cleanly."""
    url = "https://oracleapex.com/ords/r/lokesh354/timesheet-application/my-timesheet?session=113289293271296"
    title = "Timesheet Application - My Timesheet"
    clean_url, page_name = clean_page_identity(url, title)
    assert "session=" not in clean_url
    assert clean_url.endswith("/my-timesheet")
    assert page_name == "My Timesheet"


def test_discover_invalid_project(db):
    """Discovery on a non-existent project raises 404 HTTPException."""
    with pytest.raises(HTTPException) as excinfo:
        discover_and_persist_elements(
            project_id="non-existent-proj-xyz",
            payload=DiscoverRequest(),
            db=db,
        )
    assert excinfo.value.status_code == 404


def test_get_elements_valid_project(db):
    """list_elements returns list for valid project."""
    res = list_elements(project_id="apex-timesheet", db=db)
    assert isinstance(res, list)


def test_page_wise_discovery_and_catalog(db):
    """
    Runs page-wise element discovery on apex-timesheet:
    - Verifies real elements are returned with human-readable names and descriptions
    - Verifies page identity is canonical (no volatile session parameters)
    - Verifies elements are persisted to PostgreSQL with page_name
    - Verifies list_captured_pages returns the captured page and element count
    - Verifies running discovery again does not duplicate records (upsert behavior)
    - Verifies dummy elements (e.g. apexCBMDummySelection) are excluded
    """
    # 1. First discovery scan
    data1 = discover_and_persist_elements(
        project_id="apex-timesheet",
        payload=DiscoverRequest(force_refresh=False),
        db=db,
    )
    assert data1["project_id"] == "apex-timesheet"
    assert data1["total_scanned"] > 0
    assert len(data1["elements"]) > 0
    page_url = data1["page_url"]
    page_name = data1.get("page_name")

    # Canonical page URL check: volatile params stripped
    assert "session=" not in page_url

    # Verify elements have friendly names and descriptions
    for elem in data1["elements"]:
        name = elem["friendly_name"]
        assert not name.startswith("apexCBMDummySelection"), "Internal dummy IDs must not be element names"
        assert not name.startswith("Button: \""), "Names should be natural without raw prefix quotes"
        assert elem.get("description"), "Each element should have a natural description"
        assert (elem.get("category") or "").lower() != "password"
        assert "password" not in (elem.get("type_attr") or "").lower()

    # Query DB directly to check count
    count1 = db.query(AppElement).filter_by(page_url=page_url).count()
    assert count1 == len(data1["elements"])
    assert count1 > 0

    # 2. Verify list_captured_pages API
    pages = list_captured_pages(project_id="apex-timesheet", db=db)
    assert len(pages) > 0
    matched_page = next((p for p in pages if p["page_url"] == page_url), None)
    assert matched_page is not None
    assert matched_page["element_count"] == count1
    assert matched_page["page_name"] is not None

    # 3. Rescan the exact same page
    data2 = discover_and_persist_elements(
        project_id="apex-timesheet",
        payload=DiscoverRequest(force_refresh=False),
        db=db,
    )
    assert data2["inserted"] == 0, "Repeated discovery must not insert duplicate rows"
    assert data2["updated"] > 0, "Repeated discovery must update existing rows"

    # Verify row count in database has not doubled
    count2 = db.query(AppElement).filter_by(page_url=page_url).count()
    assert count2 == count1, f"Expected {count1} records, but got {count2} (duplicates created!)"

    # 4. Test list_elements retrieval with page_url filter
    all_elements = list_elements(project_id="apex-timesheet", page_url=page_url, db=db)
    assert len(all_elements) == count1
    assert all(e["page_url"] == page_url for e in all_elements)


def test_browser_status_and_save_selected_element(db):
    """
    Verifies:
    1. Browser status endpoint returns structured observable state.
    2. save_selected_element saves an individually selected element without duplicates.
    3. Password inputs are rejected from being saved.
    """
    from app.inspector_api import (
        get_browser_session_status,
        save_selected_element,
        SaveSelectedElementRequest,
    )

    # Status check
    st = get_browser_session_status("apex-timesheet")
    assert "active" in st
    assert "visible" in st
    assert "display_url" in st

    # Save a single picked element
    saved = save_selected_element(
        project_id="apex-timesheet",
        payload=SaveSelectedElementRequest(
            friendly_name="Custom Picked Button",
            description="Button selected via visual element picker",
            category="button",
            tag_name="button",
            role="button",
            locator_strategy="css",
            locator_value="button.custom-picked-btn",
            page_url="https://oracleapex.com/ords/r/lokesh354/timesheet-application/my-timesheet",
            page_name="My Timesheet",
        ),
        db=db,
    )
    assert saved["friendly_name"] == "Custom Picked Button"
    assert saved["locator_value"] == "button.custom-picked-btn"

    # Resaving same element updates it instead of duplicating
    saved2 = save_selected_element(
        project_id="apex-timesheet",
        payload=SaveSelectedElementRequest(
            friendly_name="Custom Picked Button (Updated)",
            description="Updated description",
            category="button",
            tag_name="button",
            role="button",
            locator_strategy="css",
            locator_value="button.custom-picked-btn",
            page_url="https://oracleapex.com/ords/r/lokesh354/timesheet-application/my-timesheet",
            page_name="My Timesheet",
        ),
        db=db,
    )
    assert saved2["id"] == saved["id"]
    assert saved2["friendly_name"] == "Custom Picked Button (Updated)"

    # Password input saving rejection
    with pytest.raises(HTTPException) as exc:
        save_selected_element(
            project_id="apex-timesheet",
            payload=SaveSelectedElementRequest(
                friendly_name="Password Box",
                category="input",
                tag_name="input[type=password]",
                locator_strategy="css",
                locator_value="#password",
                page_url="https://oracleapex.com/ords/r/lokesh354/timesheet-application/login",
            ),
            db=db,
        )
    assert exc.value.status_code == 400
