from __future__ import annotations

import json
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
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Operations', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO buildings (name, created_at, updated_at)
        VALUES
            ('HQ North', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
            ('Warehouse West', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    organization_row = conn.execute(
        "SELECT id FROM organizations WHERE name = 'Operations' LIMIT 1;"
    ).fetchone()
    hq_row = conn.execute(
        "SELECT id FROM buildings WHERE name = 'HQ North' LIMIT 1;"
    ).fetchone()
    assert organization_row is not None
    assert hq_row is not None
    conn.execute(
        """
        INSERT INTO organization_buildings (organization_id, building_id, created_at)
        VALUES (?, ?, '2026-01-01T00:00:00Z');
        """
        ,
        (int(organization_row["id"]), int(hq_row["id"])),
    )
    conn.execute(
        """
        INSERT INTO holders (
            id, holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at
        )
        VALUES (
            1, 'PERSON', 'Issue Holder', 'Operations', ?, 'IH-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """,
        (int(organization_row["id"]),),
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
            building, room, building_room, location_type, current_holder_id, home_slot_id
        )
        VALUES (
            501, 'ISSUE-100', 'SN-1', 'laptop', 'Dell', 'Latitude',
            'Storage', 'A1', 'Storage/A1', 'STORAGE', NULL, 101
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


def _login_issue_operator(client) -> None:
    operator_id = create_test_user(username="operator-issue-location", password="op-pass", role="operator")
    login_session(client, operator_id)
    with client.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True


def test_issue_scan_stages_before_current_location_but_preview_blocks(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    issue_page = client_with_temp_db.get("/issue")

    assert issue_page.status_code == 200
    assert b"Current Location" in issue_page.data
    assert b"Set where these assets are leaving from before preview." in issue_page.data
    assert b"Scan assets into the Issue queue. Select the receiving holder and current location before preview." in issue_page.data
    assert b"Add to Queue" in issue_page.data
    assert b"Scan or enter asset tag" in issue_page.data
    assert b"Add to queue" in issue_page.data
    assert b"Review Before Issue" in issue_page.data
    assert b"Preview Queue" not in issue_page.data
    assert b"#issue-building," in issue_page.data
    assert b"max-width: 520px;" in issue_page.data
    assert b"box-sizing: border-box;" in issue_page.data
    assert b"padding: 0.6rem;" in issue_page.data
    assert b"font-size: 1rem;" in issue_page.data
    assert b'id="scan-input"' in issue_page.data
    assert b"autofocus" not in issue_page.data
    assert b"HQ North" in issue_page.data
    assert b"Warehouse West" not in issue_page.data
    assert b'name="action" value="create_building"' not in issue_page.data
    assert b"name=\"building_name\"" not in issue_page.data
    assert b"Create building" not in issue_page.data

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert scan_response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]
    assert b"Queue (1)" in scan_response.data
    assert b"Choose the current building." in scan_response.data

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"Needs Review" in preview.data
    assert b"Choose the current building." in preview.data


def test_issue_location_dropdown_orders_allowed_buildings_alphabetically(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    conn = db.get_connection()
    try:
        organization_row = conn.execute(
            "SELECT id FROM organizations WHERE name = 'Operations' LIMIT 1;"
        ).fetchone()
        assert organization_row is not None
        organization_id = int(organization_row["id"])
        for name in ["Zulu Yard", "Alpha Annex", "bravo Depot"]:
            conn.execute(
                """
                INSERT INTO buildings (name, created_at, updated_at)
                VALUES (?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
                """,
                (name,),
            )
            building_id = int(conn.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"])
            conn.execute(
                """
                INSERT INTO organization_buildings (organization_id, building_id, created_at)
                VALUES (?, ?, '2026-01-01T00:00:00Z');
                """,
                (organization_id, building_id),
            )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get("/issue")

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert html.index('value="Alpha Annex"') < html.index('value="bravo Depot"')
    assert html.index('value="bravo Depot"') < html.index('value="HQ North"')
    assert html.index('value="HQ North"') < html.index('value="Zulu Yard"')
    assert "Warehouse West" not in html


def test_issue_commit_rejects_building_outside_selected_holder_org(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    with client_with_temp_db.session_transaction() as sess:
        sess["issue_building"] = "Warehouse West"
        sess["issue_room"] = "201"

    intake_app.SCAN_QUEUE.append(intake_app.Scan.now("ISSUE-100"))

    response = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue")

    conn = db.get_connection()
    try:
        asset_row = conn.execute(
            "SELECT location_type, current_holder_id, building_room FROM assets WHERE id = 501 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert asset_row is not None
    assert str(asset_row["location_type"]) == "STORAGE"
    assert asset_row["current_holder_id"] is None
    assert str(asset_row["building_room"]) == "Storage/A1"


def test_issue_reuses_last_valid_current_location_when_active_location_is_empty(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    with client_with_temp_db.session_transaction() as sess:
        sess["last_issue_building"] = "HQ North"
        sess["last_issue_room"] = "210"
        sess.pop("issue_building", None)
        sess.pop("issue_room", None)

    issue_page = client_with_temp_db.get("/issue")

    assert issue_page.status_code == 200
    assert b'value="HQ North" selected' in issue_page.data
    assert b'id="issue-room" type="text" name="room" value="210"' in issue_page.data

    with client_with_temp_db.session_transaction() as sess:
        assert sess["issue_building"] == "HQ North"
        assert sess["issue_room"] == "210"

    scan_redirect = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=False,
    )

    assert scan_redirect.status_code == 302
    assert (scan_redirect.headers.get("Location") or "").endswith("/issue#queue-actions")
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]


def test_issue_does_not_reuse_last_current_location_blocked_for_selected_holder(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    with client_with_temp_db.session_transaction() as sess:
        sess["last_issue_building"] = "Warehouse West"
        sess["last_issue_room"] = "201"
        sess.pop("issue_building", None)
        sess.pop("issue_room", None)

    issue_page = client_with_temp_db.get("/issue")

    assert issue_page.status_code == 200
    assert b'value="Warehouse West" selected' not in issue_page.data
    assert b'id="issue-room" type="text" name="room" value=""' in issue_page.data

    with client_with_temp_db.session_transaction() as sess:
        assert sess["issue_building"] == ""
        assert sess["issue_room"] == ""
        assert sess["last_issue_building"] == "Warehouse West"
        assert sess["last_issue_room"] == "201"

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert scan_response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]
    assert b"Queue (1)" in scan_response.data
    assert b"Choose the current building." in scan_response.data


def test_issue_commit_updates_current_location_and_preserves_home_location_context(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    location_response = client_with_temp_db.post(
        "/issue/location",
        data={"building": "HQ North", "room": "210"},
        follow_redirects=True,
    )
    assert location_response.status_code == 200
    assert b"Current location set to HQ North / 210." in location_response.data
    assert b"flash success" in location_response.data
    with client_with_temp_db.session_transaction() as sess:
        assert sess["last_issue_building"] == "HQ North"
        assert sess["last_issue_room"] == "210"

    scan_redirect = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=False,
    )
    assert scan_redirect.status_code == 302
    assert (scan_redirect.headers.get("Location") or "").endswith("/issue#queue-actions")

    scan_response = client_with_temp_db.get("/issue#queue-actions")
    assert scan_response.status_code == 200
    assert b'id="queue-actions"' in scan_response.data
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"Current location:</strong> HQ North / 210" in preview.data
    assert b"Home location:</strong> <code>CASE-1 / 1</code>" in preview.data
    assert b"Home location:</strong> <code>Not assigned</code>" not in preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )

    assert commit.status_code == 302
    conn = db.get_connection()
    try:
        receipt_row = conn.execute(
            "SELECT id FROM receipt_queue ORDER BY id DESC LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()
    assert receipt_row is not None
    assert (commit.headers.get("Location") or "").endswith(f"/receipts/{int(receipt_row['id'])}")
    assert len(intake_app.SCAN_QUEUE) == 0

    conn = db.get_connection()
    try:
        asset_row = conn.execute(
            """
            SELECT location_type, current_holder_id, home_slot_id, building, room, building_room
            FROM assets
            WHERE id = 501
            LIMIT 1;
            """
        ).fetchone()
        event_row = conn.execute(
            """
            SELECT id, payload, holder_id
            FROM asset_events
            WHERE asset_tag = 'ISSUE-100' AND event_type = 'ISSUE'
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        receipt_row = conn.execute(
            """
            SELECT receipt_type, commit_operator_user_id, holder_id, source_event_ids_json, snapshot_json, sent_at, last_attempt_at, last_error
            FROM receipt_queue
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        occupancy = conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = 501 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert asset_row is not None
    assert str(asset_row["location_type"]) == "IN_CUSTODY"
    assert int(asset_row["current_holder_id"]) == 1
    assert int(asset_row["home_slot_id"]) == 101
    assert str(asset_row["building"]) == "HQ North"
    assert str(asset_row["room"]) == "210"
    assert str(asset_row["building_room"]) == "HQ North/210"
    assert occupancy is None

    assert event_row is not None
    assert int(event_row["holder_id"]) == 1
    payload = json.loads(str(event_row["payload"]))
    assert payload["from_location_type"] == "STORAGE"
    assert payload["to_location_type"] == "IN_CUSTODY"
    assert payload["from_building_room"] == "Storage/A1"
    assert payload["to_building_room"] == "HQ North/210"
    assert int(payload["home_slot_id"]) == 101
    assert payload["responsibility_ack"]["acknowledged"] is True
    assert int(payload["responsibility_ack"]["ack_holder_id"]) == 1
    assert int(payload["responsibility_ack"]["ack_operator_user_id"]) > 0
    assert payload["responsibility_ack"]["ack_at"]
    assert payload["responsibility_ack"]["ack_scope"] == "batch"
    assert receipt_row is not None
    assert str(receipt_row["receipt_type"]) == "ISSUE"
    assert int(receipt_row["commit_operator_user_id"]) > 0
    assert int(receipt_row["holder_id"]) == 1
    assert json.loads(str(receipt_row["source_event_ids_json"])) == [int(event_row["id"])]
    receipt_snapshot = json.loads(str(receipt_row["snapshot_json"]))
    assert receipt_snapshot["receipt_type"] == "ISSUE"
    assert receipt_snapshot["holder_id"] == 1
    assert receipt_snapshot["source_event_ids"] == [int(event_row["id"])]
    assert receipt_snapshot["location_context"]["building"] == "HQ North"
    assert receipt_snapshot["location_context"]["room"] == "210"
    assert receipt_snapshot["location_context"]["building_room"] == "HQ North/210"
    assert receipt_snapshot["acknowledgment"]["ack_scope"] == "batch"
    assert receipt_snapshot["delivery"]["state"] == "pending"
    assert receipt_snapshot["delivery"]["sent_at"] is None
    assert receipt_snapshot["delivery"]["last_attempt_at"] is None
    assert receipt_snapshot["delivery"]["last_error"] is None
    assert len(receipt_snapshot["assets"]) == 1
    assert receipt_snapshot["assets"][0]["asset_tag"] == "ISSUE-100"
    assert receipt_snapshot["assets"][0]["from_location_type"] == "STORAGE"
    assert receipt_snapshot["assets"][0]["to_location_type"] == "IN_CUSTODY"
    assert receipt_row["sent_at"] is None
    assert receipt_row["last_attempt_at"] is None
    assert receipt_row["last_error"] is None


def test_issue_commit_requires_responsibility_acknowledgment(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )
    assert scan_response.status_code == 200

    blocked = client_with_temp_db.post(
        "/issue/commit?json=1",
        data={"confirm_reviewed": "on"},
    )

    assert blocked.status_code == 400
    assert blocked.json["ok"] is False
    assert blocked.json["committed"] == 0
    assert blocked.json["error"] == "Confirm responsibility acknowledgment before issuing assets."

    conn = db.get_connection()
    try:
        event_count = conn.execute(
            "SELECT COUNT(*) AS c FROM asset_events WHERE asset_tag = 'ISSUE-100' AND event_type = 'ISSUE';"
        ).fetchone()
        receipt_count = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()

    assert event_count is not None
    assert int(event_count["c"]) == 0
    assert receipt_count is not None
    assert int(receipt_count["c"]) == 0


def test_issue_commit_json_returns_exact_created_receipt_id(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)
    with client_with_temp_db.session_transaction() as sess:
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )
    assert scan_response.status_code == 200

    commit = client_with_temp_db.post(
        "/issue/commit?json=1",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
    )

    assert commit.status_code == 200
    assert commit.json["ok"] is True
    assert commit.json["committed"] == 1
    assert isinstance(commit.json["receipt_id"], int)

    conn = db.get_connection()
    try:
        receipt_row = conn.execute(
            "SELECT id FROM receipt_queue ORDER BY id DESC LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert receipt_row is not None
    assert int(receipt_row["id"]) == int(commit.json["receipt_id"])


def test_issue_commit_missing_ack_shows_visible_message_on_issue_preview(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    location_response = client_with_temp_db.post(
        "/issue/location",
        data={"building": "HQ North", "room": "210"},
        follow_redirects=True,
    )
    assert location_response.status_code == 200

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )
    assert scan_response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 1

    blocked = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on"},
        follow_redirects=False,
    )

    assert blocked.status_code == 400
    assert b"Issue Preview" in blocked.data
    assert b"Confirm responsibility acknowledgment before issuing assets." in blocked.data
    assert len(intake_app.SCAN_QUEUE) == 1
