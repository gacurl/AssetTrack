from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.intake.scan import Scan
from tests.auth_test_utils import create_test_user


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

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    intake_app.SCAN_QUEUE.append(Scan.now("DDC4CY002645"))

    preview = client_with_temp_db.get("/preview")
    assert preview.status_code == 200
    assert b'action="/issue/commit"' in preview.data
    assert b"Commit Issue" in preview.data

    issue_preview = client_with_temp_db.get("/issue/preview")
    assert issue_preview.status_code == 200
    assert b"Confirm Issue" in issue_preview.data
    assert b"Ready to Issue" in issue_preview.data
    assert b"Commit Issue is the next step." in issue_preview.data
    assert b"Issued to:</strong>" in issue_preview.data
    assert b"Issue Holder" in issue_preview.data
    assert b"Queued:</strong> 1 asset" in issue_preview.data
    assert b"Current location:</strong> <code>HQ North / 210</code>" in issue_preview.data
    assert b"Issued to:</strong> <code>Not assigned</code>" in issue_preview.data
    assert b"Home location:</strong> <code>CASE-1 / 1</code>" in issue_preview.data
    assert b"null" not in issue_preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on"},
        follow_redirects=True,
    )

    assert commit.status_code == 200
    assert b"Issued 1 assets." in commit.data
    assert b"Issuing Assets" in commit.data
    assert b"Issued to:</strong>" in commit.data
    assert b"Issue Holder" in commit.data
    assert b"Status:</strong> Issued 1 asset successfully." in commit.data
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
    assert b"Issuing Assets" in follow_up_scan.data
    assert b"Issued to:</strong>" in follow_up_scan.data
    assert b"Issue Holder" in follow_up_scan.data
    assert b"Queued:</strong> 1 asset" in follow_up_scan.data

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


def test_issue_queue_remove_updates_preview_and_commit_for_remaining_items(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-remove-preview", password="op-pass", role="operator")

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
        sess["user_id"] = operator_id
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
    assert b"Queued assets:</strong> 2" in remove.data

    issue_preview = client_with_temp_db.get("/issue/preview")
    assert issue_preview.status_code == 200
    assert b"DDC4CY002645" in issue_preview.data
    assert b"DDC4CY002647" in issue_preview.data
    assert b"DDC4CY002646" not in issue_preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on"},
        follow_redirects=True,
    )

    assert commit.status_code == 200
    assert b"Issued 2 assets." in commit.data
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
