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
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (101, 'CASE-1', 1, 'ISSUE-100');
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            location_type, current_holder_id, home_slot_id
        )
        VALUES (
            501, 'ISSUE-100', 'SN-1', 'laptop', 'Dell', 'Latitude',
            'STORAGE', NULL, 101
        );
        """
    )
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (101, 501, '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_issue_renders_without_holder_and_enables_issue_mode(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-prereq", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b">Issue<" in response.data
    assert b"Review Before Issue" in response.data
    assert b"Select holder" in response.data
    assert b'href="/holders?return_to=/issue"' in response.data
    assert b"No assets staged." in response.data
    assert b"Required before preview." in response.data

    with client_with_temp_db.session_transaction() as sess:
        assert sess["issue_mode"] is True


def test_valid_issue_asset_can_stage_before_holder_without_custody_side_effects(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-stage-before-holder", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]
    assert b"1 staged asset" in response.data
    assert b"Inspect or remove staged assets" in response.data
    assert b"No holder selected. Select a holder before issuing assets." in response.data
    assert b"Select a holder before choosing the current location." in response.data

    conn = db.get_connection()
    try:
        asset = conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE asset_tag = 'ISSUE-100' LIMIT 1;"
        ).fetchone()
        event_count = conn.execute("SELECT COUNT(*) AS c FROM asset_events WHERE event_type = 'ISSUE';").fetchone()
        receipt_count = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()

    assert asset is not None
    assert str(asset["location_type"]) == "STORAGE"
    assert asset["current_holder_id"] is None
    assert event_count is not None
    assert int(event_count["c"]) == 0
    assert receipt_count is not None
    assert int(receipt_count["c"]) == 0


def test_issue_preview_and_commit_remain_blocked_without_holder(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-stage-blocked-holder", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )

    preview = client_with_temp_db.get("/issue/preview")

    assert preview.status_code == 200
    assert b"Needs Review" in preview.data
    assert b"No holder selected. Select a holder before issuing assets." in preview.data
    assert b"Select a holder before choosing the current location." in preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )

    assert commit.status_code == 302
    assert (commit.headers.get("Location") or "").endswith("/issue/preview")
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]

    conn = db.get_connection()
    try:
        event_count = conn.execute("SELECT COUNT(*) AS c FROM asset_events WHERE event_type = 'ISSUE';").fetchone()
        receipt_count = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()

    assert event_count is not None
    assert int(event_count["c"]) == 0
    assert receipt_count is not None
    assert int(receipt_count["c"]) == 0


def test_selecting_holder_returns_user_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-return", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    stage_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )
    assert stage_response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]

    select_response = client_with_temp_db.post(
        "/holders/select",
        data={"holder_id": "1", "return_to": "/issue"},
    )
    assert select_response.status_code == 302
    assert (select_response.headers.get("Location") or "").endswith("/issue")

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Issue" in issue_page.data
    assert b"Review Before Issue" in issue_page.data
    assert b"Issue Holder" in issue_page.data
    assert b"1 staged asset" in issue_page.data
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]


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
    assert b">Issue<" in issue_page.data
    assert b"Selected holder" in issue_page.data
    assert b"Issue Holder" in issue_page.data
    assert b"Issue Org" in issue_page.data
    assert b"Enable issue mode before using Issue Assets." not in issue_page.data


def test_holders_issue_selection_page_uses_issue_specific_action_label(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-issue-action-label", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/holders?return_to=/issue")

    assert response.status_code == 200
    assert b"Back to Issue" in response.data
    assert b"Back to preview" not in response.data
    assert b"Issue Assets" not in response.data
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


def test_issue_preview_with_empty_queue_redirects_to_issue_entry(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-empty-issue-preview", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

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
    assert b"Issue" in response.data


def test_issue_page_displays_selected_holder_context(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-holder-display", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    assert b"Issue" in response.data
    assert b"Issue Holder" in response.data
    assert b"Issue Org" in response.data
    assert b"Holder" in response.data
    assert b"ID IH-1" in response.data
    assert b"Change holder" in response.data
    assert b'href="/holders?return_to=/issue"' in response.data
    assert b"No assets staged." in response.data


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
    assert b">Issue<" in response.data
    assert b"Maintenance Team" in response.data
    assert b"Maintenance Team (Maintenance Team)" not in response.data
