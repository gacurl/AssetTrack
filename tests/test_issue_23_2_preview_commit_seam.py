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
    assert b"Issued to:</strong> <code>Not assigned</code>" in issue_preview.data
    assert b"Home location:</strong> <code>Not assigned</code>" in issue_preview.data
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
