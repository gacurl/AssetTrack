from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Issue Holder', 'Issue Org', 'IH-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_issue_requires_holder_selection_before_queue_access(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-prereq", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 302
    location = response.headers.get("Location") or ""
    assert location.endswith("/holders?return_to=/issue")


def test_selecting_holder_returns_user_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-return", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id

    issue_redirect = client_with_temp_db.get("/issue")
    assert issue_redirect.status_code == 302
    assert (issue_redirect.headers.get("Location") or "").endswith("/holders?return_to=/issue")

    select_response = client_with_temp_db.post(
        "/holders/select",
        data={"holder_id": "1", "return_to": "/issue"},
    )
    assert select_response.status_code == 302
    assert (select_response.headers.get("Location") or "").endswith("/issue")

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Issue Assets" in issue_page.data
    assert b"Open Issue Assets Preview / Confirm" in issue_page.data


def test_issue_with_selected_holder_still_loads_normally(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-selected", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b"Select a holder before issuing assets." not in response.data
    assert b"Issue Assets" in response.data


def test_issue_page_displays_selected_holder_context(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-holder-display", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b"Issuing Assets To" in response.data
    assert b"Holder:</strong> Issue Holder" in response.data
    assert b"Organization:</strong> Issue Org" in response.data
