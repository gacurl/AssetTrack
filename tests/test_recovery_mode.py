from __future__ import annotations

import json
from pathlib import Path

import pytest

import assettrack.auth as auth
import assettrack.db as db
import assettrack.restore as restore_module
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.SCAN_QUEUE.clear()
    intake_app.ADMIN_ROUTE_ATTEMPTS.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _write_recovery_state(db_path: Path, *, source_filename: str = "restore-upload.db") -> None:
    state_path = restore_module.recovery_state_path_for(db_path)
    state_path.write_text(
        json.dumps(
            {
                "active": True,
                "recovered_at": "2026-05-11T12:00:00Z",
                "db_path": str(db_path),
                "rollback_db_path": str(restore_module.rollback_artifact_path_for(db_path)),
                "source_filename": source_filename,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _insert_holder() -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO organizations (id, name, created_at, updated_at)
            VALUES (9, 'Operations', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        conn.execute(
            """
            INSERT INTO holders (
                id, holder_type, name, organization, organization_id, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (
                1, 'PERSON', 'Issue Holder', 'Operations', 9, 'IH-1', 'issue@example.org', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_issue_asset() -> None:
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (10, 'CASE-10', 1, NULL);")
        conn.execute(
            """
            INSERT INTO assets (
                id, asset_tag, serial_number, equipment_type, manufacturer, model, model_code, notes,
                location_type, current_holder_id, home_slot_id, building_room
            )
            VALUES (
                100, 'ISSUE-100', 'SN-ISSUE-100', 'Laptop', 'Dell', 'Latitude', 'LAT-14', 'Original issue note',
                'STORAGE', NULL, 10, 'Storage/A1'
            );
            """
        )
        conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (10, 100, '2026-01-01T00:00:00Z');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _login_issue_operator(client, *, username: str = "issue-operator") -> int:
    operator_id = create_test_user(username=username, password="op-pass", role="operator")
    current_time = auth.now_seconds()
    with client.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["last_seen"] = current_time
        sess["session_started_at"] = current_time
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"
    return operator_id


def _create_issue_receipt(client) -> int:
    _insert_holder()
    _insert_issue_asset()
    _login_issue_operator(client)
    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))

    response = client.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT id FROM receipt_queue ORDER BY id DESC LIMIT 1;").fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row["id"])


def test_receipt_detail_shows_recovery_block_message_for_resend_action(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot["delivery"] = {
            "state": "failed",
            "sent_at": None,
            "last_attempt_at": "2026-03-29T12:00:00+00:00",
            "last_error": "smtp offline",
        }
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = NULL, last_attempt_at = ?, last_error = ?
            WHERE id = ?;
            """,
            (json.dumps(snapshot, sort_keys=True), "2026-03-29T12:00:00+00:00", "smtp offline", receipt_id),
        )
        conn.commit()
    finally:
        conn.close()

    _write_recovery_state(db.DB_PATH, source_filename="restore-block.db")

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Recovery mode blocks retry send" in response.data
    assert b"Receipt resend and retry actions are paused until an admin acknowledges recovery mode." in response.data
    assert b"Blocked during recovery mode" in response.data


def test_receipt_send_is_blocked_during_recovery_mode(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    _write_recovery_state(db.DB_PATH)

    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert response.status_code == 409
    assert response.json == {
        "ok": False,
        "error": "Receipt resend is blocked during recovery mode. Admin acknowledgment is required before email delivery resumes.",
    }
    assert send_calls == []


def test_admin_receipt_resend_is_blocked_during_recovery_mode(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    admin_id = create_test_user(username="admin-resend-block", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    _write_recovery_state(db.DB_PATH)

    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/resend?json=1")

    assert response.status_code == 409
    assert response.json == {
        "ok": False,
        "error": "Receipt resend is blocked during recovery mode. Admin acknowledgment is required before email delivery resumes.",
    }
    assert send_calls == []


def test_admin_banner_is_visible_only_to_admins_during_recovery_mode(client_with_temp_db) -> None:
    _write_recovery_state(db.DB_PATH, source_filename="restore-banner.db")

    admin_id = create_test_user(username="admin-banner", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    admin_response = client_with_temp_db.get("/dashboard")
    assert admin_response.status_code == 200
    assert b"Recovery Mode Active" in admin_response.data
    assert b"restore-banner.db" in admin_response.data

    operator_id = create_test_user(username="operator-banner", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    operator_response = client_with_temp_db.get("/dashboard")
    assert operator_response.status_code == 200
    assert b"Recovery Mode Active" not in operator_response.data
