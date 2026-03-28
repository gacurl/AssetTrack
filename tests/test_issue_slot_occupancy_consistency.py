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
        VALUES (101, 'CASE-1', 1, NULL);
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
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (101, 501, '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_issue_preview_and_commit_use_slot_occupancy_when_slot_marker_is_null(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-issue", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    intake_app.SCAN_QUEUE.append(Scan.now("DDC4CY002645"))

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"Not currently slotted: DDC4CY002645" not in preview.data
    assert b"Home location:</strong> <code>CASE-1 / 1</code>" in preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
    )
    assert commit.status_code == 302
    assert (commit.headers.get("Location") or "").endswith("/issue?issued=1")

    conn = db.get_connection()
    try:
        occupancy = conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = 501 LIMIT 1;"
        ).fetchone()
        asset = conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE id = 501 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert occupancy is None
    assert asset is not None
    assert str(asset["location_type"]) == "IN_CUSTODY"
    assert int(asset["current_holder_id"]) == 1


def test_issue_commit_redirect_shows_success_without_holder_warning(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-seam", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    intake_app.SCAN_QUEUE.append(Scan.now("DDC4CY002645"))

    commit_response = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=True,
    )

    assert commit_response.status_code == 200
    assert b"Issued 1 assets." in commit_response.data
    assert b"Select a holder before issuing assets." not in commit_response.data
    assert b"Status:</strong> Issued 1 asset successfully." in commit_response.data
    assert b"Queued:</strong> 0 assets" not in commit_response.data
    assert len(intake_app.SCAN_QUEUE) == 0
