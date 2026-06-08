from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.intake.scan import Scan
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, identifier, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Issue Holder', 'IH-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (101, 'CASE-1', 1, 'DDC4CY002645');
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            location_type, current_holder_id, home_slot_id
        )
        VALUES (
            501, 'DDC4CY002645', 'SN-1', 'laptop', 'Dell', 'Latitude',
            'STORAGE', NULL, 101
        );
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            location_type, current_holder_id, home_slot_id
        )
        VALUES (
            504, 'FOLLOW-UP-TAG', 'SN-4', 'laptop', 'Dell', 'Latitude',
            'STORAGE', NULL, NULL
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


def test_issue_mode_preview_posts_to_issue_commit_and_allows_operator_commit(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-preview-seam", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    intake_app.SCAN_QUEUE.append(Scan.now("DDC4CY002645"))

    preview = client_with_temp_db.get("/preview")
    assert preview.status_code == 200
    assert b'action="/issue/commit"' in preview.data
    assert b"Commit Issue" in preview.data
    assert b"I reviewed this batch and want to issue these assets to the selected holder." in preview.data

    issue_preview = client_with_temp_db.get("/issue/preview")
    assert issue_preview.status_code == 200
    assert b"Issue Preview" in issue_preview.data
    assert b"Ready to Issue" in issue_preview.data
    assert b"Issue to:</strong>" in issue_preview.data
    assert b"Issue Holder" in issue_preview.data
    assert b"1 asset queued" in issue_preview.data
    assert b"Current location:</strong> HQ North / 210" in issue_preview.data
    assert b"Issue result:</strong> <code>IN_CUSTODY</code> at <code>HQ North / 210</code>" in issue_preview.data
    assert b"Technical details" in issue_preview.data
    assert b"Home location:</strong> <code>CASE-1 / 1</code>" in issue_preview.data
    assert b"I reviewed this batch and want to issue these assets to the selected holder." in issue_preview.data
    assert b'name="confirm_responsibility_ack"' in issue_preview.data
    assert b"accepted responsibility for this issue batch" in issue_preview.data
    assert b'id="issue_btn" type="submit" data-timeout-lock-target' in issue_preview.data
    assert b"/issue/commit?json=1" not in issue_preview.data
    assert b"null" not in issue_preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=True,
    )

    assert commit.status_code == 200
    assert b"Issue Receipt" in commit.data
    assert b"Issue Holder" in commit.data
    assert b"Queued:</strong> 0 assets" not in commit.data
    assert len(intake_app.SCAN_QUEUE) == 0

    with client_with_temp_db.session_transaction() as sess:
        assert sess["holder_id"] == 1

    follow_up_scan = client_with_temp_db.post(
        "/",
        data={"scan_text": "FOLLOW-UP-TAG", "return_to": "/issue"},
        follow_redirects=True,
    )
    assert follow_up_scan.status_code == 200
    assert b">Issue<" in follow_up_scan.data
    assert b"Issue Holder" in follow_up_scan.data
    assert b"1 asset queued" in follow_up_scan.data

    conn = db.get_connection()
    try:
        asset = conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE id = 501 LIMIT 1;"
        ).fetchone()
        occupancy = conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = 501 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert asset is not None
    assert str(asset["location_type"]) == "IN_CUSTODY"
    assert int(asset["current_holder_id"]) == 1
    assert occupancy is None


def test_issue_preview_empty_queue_redirects_to_issue_entry(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-preview-empty", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    issue_preview = client_with_temp_db.get("/issue/preview")

    assert issue_preview.status_code == 302
    assert (issue_preview.headers.get("Location") or "").endswith("/issue")


def test_issue_preview_blocked_items_render_visible_details_and_still_block_commit(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-preview-blocked", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    intake_app.SCAN_QUEUE.append(Scan.now("FOLLOW-UP-TAG"))

    issue_preview = client_with_temp_db.get("/issue/preview")
    html = issue_preview.data.decode("utf-8")

    assert issue_preview.status_code == 200
    assert "Needs Review" in html
    assert "Blocked Items" in html
    assert "<template>" not in html
    assert "<li>Not currently slotted: FOLLOW-UP-TAG</li>" in html
    assert "<li>Asset is not currently slotted</li>" in html

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )

    assert commit.status_code == 302
    assert (commit.headers.get("Location") or "").endswith("/issue/preview")
    assert len(intake_app.SCAN_QUEUE) == 1

    conn = db.get_connection()
    try:
        event_count = conn.execute(
            "SELECT COUNT(*) AS c FROM asset_events WHERE asset_tag = 'FOLLOW-UP-TAG' AND event_type = 'ISSUE';"
        ).fetchone()
        receipt_count = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()

    assert event_count is not None
    assert int(event_count["c"]) == 0
    assert receipt_count is not None
    assert int(receipt_count["c"]) == 0


def test_issue_queue_remove_updates_preview_and_commit_for_remaining_items(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-remove-preview", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES
            (102, 'CASE-1', 2, 'DDC4CY002646'),
            (103, 'CASE-1', 3, 'DDC4CY002647');
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            location_type, current_holder_id, home_slot_id
        )
        VALUES
            (502, 'DDC4CY002646', 'SN-2', 'laptop', 'Dell', 'Latitude', 'STORAGE', NULL, 102),
            (503, 'DDC4CY002647', 'SN-3', 'laptop', 'Dell', 'Latitude', 'STORAGE', NULL, 103);
        """
    )
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES
            (102, 502, '2026-01-01T00:00:00Z'),
            (103, 503, '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    intake_app.SCAN_QUEUE.extend(
        [
            Scan.now("DDC4CY002645"),
            Scan.now("DDC4CY002646"),
            Scan.now("DDC4CY002647"),
        ]
    )

    remove = client_with_temp_db.post(
        "/",
        data={"action": "remove", "queue_index": "1", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert remove.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["DDC4CY002645", "DDC4CY002647"]
    assert b"Queue (2)" in remove.data
    assert b"Blocked Items" not in remove.data

    issue_preview = client_with_temp_db.get("/issue/preview")
    assert issue_preview.status_code == 200
    assert b"DDC4CY002645" in issue_preview.data
    assert b"DDC4CY002647" in issue_preview.data
    assert b"DDC4CY002646" not in issue_preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=True,
    )

    assert commit.status_code == 200
    assert b"Issue Receipt" in commit.data
    assert len(intake_app.SCAN_QUEUE) == 0

    conn = db.get_connection()
    try:
        issued_rows = conn.execute(
            """
            SELECT asset_tag, location_type, current_holder_id
            FROM assets
            WHERE asset_tag IN ('DDC4CY002645', 'DDC4CY002646', 'DDC4CY002647')
            ORDER BY asset_tag;
            """
        ).fetchall()
        remaining_occupancy = conn.execute(
            """
            SELECT slot_id, asset_id
            FROM slot_occupancy
            WHERE asset_id IN (501, 502, 503)
            ORDER BY asset_id;
            """
        ).fetchall()
    finally:
        conn.close()

    by_tag = {str(row["asset_tag"]): row for row in issued_rows}
    assert str(by_tag["DDC4CY002645"]["location_type"]) == "IN_CUSTODY"
    assert int(by_tag["DDC4CY002645"]["current_holder_id"]) == 1
    assert str(by_tag["DDC4CY002647"]["location_type"]) == "IN_CUSTODY"
    assert int(by_tag["DDC4CY002647"]["current_holder_id"]) == 1
    assert str(by_tag["DDC4CY002646"]["location_type"]) == "STORAGE"
    assert by_tag["DDC4CY002646"]["current_holder_id"] is None
    assert [(int(row["slot_id"]), int(row["asset_id"])) for row in remaining_occupancy] == [(102, 502)]
