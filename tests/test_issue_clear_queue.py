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
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_operator_clear_queue_from_issue_returns_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-clear", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.append(Scan.now("UNKNOWN-TAG"))

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/issue"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue#queue-section")
    assert len(intake_app.SCAN_QUEUE) == 0

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Queued assets:</strong> 0" in issue_page.data


def test_operator_can_remove_one_queue_item_by_index_without_affecting_duplicates(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-remove-one", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.extend(
        [
            Scan.now("DUP-TAG"),
            Scan.now("DUP-TAG"),
            Scan.now("KEEP-TAG"),
        ]
    )

    response = client_with_temp_db.post(
        "/",
        data={"action": "remove", "queue_index": "1", "return_to": "/issue"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue#queue-section")
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["DUP-TAG", "KEEP-TAG"]

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Queue (2)" in issue_page.data


def test_operator_can_clear_queue_from_issue_preview_and_return_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-clear-preview", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.extend([Scan.now("TAG-1"), Scan.now("TAG-2")])

    preview_page = client_with_temp_db.get("/issue/preview")
    assert preview_page.status_code == 200
    assert b"Clear Queue" in preview_page.data

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"Issuing Assets" in response.data
    assert b"Queue (0)" in response.data
    assert b"Queued assets:</strong> 0" in response.data


def test_issue_preview_discard_preserves_selected_holder_and_allows_rescan(client_with_temp_db) -> None:
    operator_id = create_test_user(username="admin-discard-issue", password="op-pass", role="admin")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO assets (id, asset_tag, location_type)
        VALUES (1, 'TAG-RESCAN', 'STORAGE');
        """
    )
    conn.commit()
    conn.close()

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.extend([Scan.now("TAG-1"), Scan.now("TAG-2")])

    response = client_with_temp_db.post(
        "/preview/discard",
        data={"return_to": "/issue"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"Issuing Assets" in response.data
    assert b"Issued to:</strong>" in response.data
    assert b"Issue Holder" in response.data
    assert b"Queue (0)" in response.data
    assert b"Queued assets:</strong> 0" in response.data

    with client_with_temp_db.session_transaction() as sess:
        assert sess.get("holder_id") == 1

    rescan = client_with_temp_db.post(
        "/",
        data={"scan_text": "TAG-RESCAN", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert rescan.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["TAGRESCAN"]
    assert b"Queue (1)" in rescan.data
    assert b"Issued to:</strong>" in rescan.data
    assert b"Issue Holder" in rescan.data


def test_issue_preview_discard_preserves_holder_through_rescan_preview_and_commit(
    client_with_temp_db,
) -> None:
    operator_id = create_test_user(username="admin-discard-commit", password="op-pass", role="admin")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (101, 'CASE-1', 1, 'VALID-ISSUE-TAG');
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            location_type, current_holder_id, home_slot_id
        )
        VALUES (
            101, 'VALID-ISSUE-TAG', 'SN-101', 'laptop', 'Dell', 'Latitude',
            'STORAGE', NULL, 101
        );
        """
    )
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (101, 101, '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.extend([Scan.now("TAG-1"), Scan.now("TAG-2")])

    discard = client_with_temp_db.post(
        "/preview/discard",
        data={"return_to": "/issue"},
        follow_redirects=True,
    )

    assert discard.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"Issue Holder" in discard.data

    rescan = client_with_temp_db.post(
        "/",
        data={"scan_text": "VALID-ISSUE-TAG", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert rescan.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["VALIDISSUETAG"]
    assert b"Issue Holder" in rescan.data

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"Ready to Issue" in preview.data
    assert b"Issue Holder" in preview.data
    assert b"VALID-ISSUE-TAG" in preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on"},
        follow_redirects=True,
    )

    assert commit.status_code == 200
    assert b"Issued 1 assets." in commit.data
    assert b"Issue Holder" in commit.data
    assert len(intake_app.SCAN_QUEUE) == 0

    with client_with_temp_db.session_transaction() as sess:
        assert sess.get("holder_id") == 1

    conn = db.get_connection()
    try:
        asset_row = conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE id = 101 LIMIT 1;"
        ).fetchone()
        occupancy = conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = 101 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert asset_row is not None
    assert str(asset_row["location_type"]) == "IN_CUSTODY"
    assert int(asset_row["current_holder_id"]) == 1
    assert occupancy is None


def test_non_issue_preview_discard_still_clears_holder_selection(client_with_temp_db) -> None:
    operator_id = create_test_user(username="admin-discard-general", password="op-pass", role="admin")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["equipment_type"] = "tablet"

    intake_app.SCAN_QUEUE.append(Scan.now("TAG-1"))

    response = client_with_temp_db.post(
        "/preview/discard",
        data={"return_to": "/add-assets"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/add-assets")
    assert len(intake_app.SCAN_QUEUE) == 0

    with client_with_temp_db.session_transaction() as sess:
        assert "holder_id" not in sess
        assert sess.get("equipment_type") == "laptop"


def test_issue_scan_normalizes_asset_tag_to_uppercase_and_blocks_case_variant_duplicate(
    client_with_temp_db,
) -> None:
    operator_id = create_test_user(username="operator-uppercase-issue", password="op-pass", role="operator")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO assets (id, asset_tag, location_type)
        VALUES (1, 'AB-123', 'STORAGE');
        """
    )
    conn.commit()
    conn.close()

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    first = client_with_temp_db.post(
        "/",
        data={"scan_text": "ab-123", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert first.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["AB123"]
    assert b"AB123" in first.data
    assert b"ab-123" not in first.data

    second = client_with_temp_db.post(
        "/",
        data={"scan_text": "AB123", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert second.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["AB123"]
    assert b"Asset AB123 is already queued." in second.data

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"AB-123" in preview.data
    assert b"ab-123" not in preview.data
