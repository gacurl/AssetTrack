from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


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
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 302
    location = response.headers.get("Location") or ""
    assert location.endswith("/holders?return_to=/issue")


def test_selecting_holder_returns_user_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-return", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

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


def test_holders_issue_navigation_targets_issue_entry_and_preserves_selected_holder(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-holders-issue-nav", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    holders_page = client_with_temp_db.get("/holders")
    assert holders_page.status_code == 200
    assert b'href="/issue"' in holders_page.data
    assert b'href="/issue/preview"' not in holders_page.data

    select_response = client_with_temp_db.post(
        "/holders/select",
        data={"holder_id": "1"},
    )
    assert select_response.status_code == 302
    assert (select_response.headers.get("Location") or "").endswith("/holders")

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Issuing Assets" in issue_page.data
    assert b"Selected holder" in issue_page.data
    assert b"Issue Holder" in issue_page.data
    assert b"Issue Org" in issue_page.data
    assert b"Enable issue mode before using Issue Assets." not in issue_page.data


def test_holders_issue_selection_page_uses_issue_specific_action_label(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-issue-action-label", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/holders?return_to=/issue")

    assert response.status_code == 200
    assert b"Select for Issue" in response.data
    assert b'class="holder-select-button"' in response.data
    assert b'href="/holders/1?return_to=/issue"' in response.data


def test_holders_issue_selection_page_links_selected_holder_with_return_to(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-selected-holder-link", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1

    response = client_with_temp_db.get("/holders?return_to=/issue")

    assert response.status_code == 200
    assert b'class="selected-holder-link"' in response.data
    assert b'href="/holders/1?return_to=/issue"' in response.data


def test_holder_select_accepts_return_to_from_action_url_for_issue_flow(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-return-query", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.post(
        "/holders/select?return_to=/issue",
        data={"holder_id": "1"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue")


def test_issue_preview_without_issue_mode_redirects_to_issue_entry(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-issue-preview-redirect", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = False

    response = client_with_temp_db.get("/issue/preview")

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue")


def test_issue_with_selected_holder_still_loads_normally(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-selected", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b"Select a holder before issuing assets." not in response.data
    assert b"Issue Assets" in response.data


def test_issue_page_displays_selected_holder_context(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-holder-display", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b"Issuing Assets" in response.data
    assert b"Issue Holder" in response.data
    assert b"Issue Org" in response.data
    assert b"0 assets queued" in response.data


def test_issue_page_displays_selected_group_holder_context(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-group-holder", password="op-pass", role="operator")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
        VALUES (2, 'ORGANIZATION', 'Maintenance Team', 'Maintenance Team', NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 2

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b"Issuing Assets" in response.data
    assert b"Maintenance Team" in response.data
    assert b"Maintenance Team (Maintenance Team)" not in response.data
