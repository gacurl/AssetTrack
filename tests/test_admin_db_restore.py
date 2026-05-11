from __future__ import annotations

import json
import sqlite3
from io import BytesIO
from pathlib import Path

import pytest

import assettrack.db as db
import assettrack.restore as restore_module
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.ADMIN_ROUTE_ATTEMPTS.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _insert_asset(conn: sqlite3.Connection, asset_tag: str) -> None:
    conn.execute(
        """
        INSERT INTO assets (
            asset_tag,
            serial_number,
            equipment_type,
            manufacturer,
            model,
            custody_state,
            accountability_status,
            condition,
            created_date,
            updated_date,
            location_type,
            building,
            room,
            building_room
        )
        VALUES (?, ?, 'laptop', 'Dell', 'Latitude', 'in_stock', 'accountable', 'serviceable', ?, ?, 'STORAGE', 'HQ', '100', 'HQ/100');
        """,
        (
            asset_tag,
            f"SN-{asset_tag}",
            "2026-05-11",
            "2026-05-11T00:00:00Z",
        ),
    )


def _insert_event(conn: sqlite3.Connection, asset_tag: str, actor: str) -> None:
    conn.execute(
        """
        INSERT INTO asset_events (
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            payload
        )
        VALUES (?, 'ISSUE', '2026-05-11T00:00:00Z', ?, NULL, NULL);
        """,
        (asset_tag, actor),
    )


def _insert_admin_user(conn: sqlite3.Connection, user_id: int, username: str) -> None:
    conn.execute(
        """
        INSERT INTO users (id, username, password_hash, role, active, created_at, updated_at)
        VALUES (?, ?, 'hash', 'admin', 1, '2026-05-11T00:00:00Z', '2026-05-11T00:00:00Z');
        """,
        (user_id, username),
    )


def _build_valid_restore_db(path: Path, *, asset_tag: str, admin_user_id: int = 1) -> Path:
    db.initialize_schema(path)
    conn = sqlite3.connect(path)
    try:
        _insert_admin_user(conn, admin_user_id, "restored-admin")
        _insert_asset(conn, asset_tag)
        _insert_event(conn, asset_tag, "restore-source")
        conn.commit()
    finally:
        conn.close()
    return path


def _asset_tags(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT asset_tag FROM assets ORDER BY asset_tag ASC;").fetchall()
        return [str(row[0]) for row in rows]
    finally:
        conn.close()


def _event_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0])
    finally:
        conn.close()


def _restore_history_entries(path: Path) -> list[dict[str, object]]:
    history_path = restore_module.restore_history_path_for(path)
    if not history_path.exists():
        return []
    return [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_admin_can_restore_valid_database_upload(client_with_temp_db, tmp_path: Path) -> None:
    admin_id = create_test_user(username="admin-restore", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    conn = db.get_connection()
    try:
        _insert_asset(conn, "LIVE-ONLY")
        _insert_event(conn, "LIVE-ONLY", "live-admin")
        conn.commit()
    finally:
        conn.close()

    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-upload.db", asset_tag="RESTORE-ONLY")

    with restore_upload_path.open("rb") as handle:
        response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-upload.db")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Database restore complete." in response.data
    assert _asset_tags(live_db_path) == ["RESTORE-ONLY"]
    assert _event_count(live_db_path) == 1

    rollback_path = restore_module.rollback_artifact_path_for(live_db_path)
    assert rollback_path.exists()
    assert _asset_tags(rollback_path) == ["LIVE-ONLY"]
    assert _event_count(rollback_path) == 1

    recovery_state_path = restore_module.recovery_state_path_for(live_db_path)
    assert recovery_state_path.exists()
    recovery_state = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert recovery_state["active"] is True
    assert recovery_state["rollback_db_path"] == str(rollback_path)
    assert recovery_state["db_path"] == str(live_db_path)
    assert recovery_state["source_filename"] == "restore-upload.db"

    history_entries = _restore_history_entries(live_db_path)
    assert len(history_entries) == 1
    assert history_entries[0]["source_filename"] == "restore-upload.db"
    assert history_entries[0]["rollback_db_path"] == str(rollback_path)
    assert history_entries[0]["result"] == "success"


def test_restore_rejects_non_sqlite_upload_without_replacing_live_db(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-invalid-upload", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    conn = db.get_connection()
    try:
        _insert_asset(conn, "LIVE-KEEP")
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/db/restore",
        data={"db_file": (BytesIO(b"not-a-sqlite-database"), "invalid.db")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Uploaded file is not a valid SQLite database" in response.data
    assert _asset_tags(live_db_path) == ["LIVE-KEEP"]
    assert not restore_module.rollback_artifact_path_for(live_db_path).exists()
    assert not restore_module.recovery_state_path_for(live_db_path).exists()


def test_restore_rejects_sqlite_file_missing_required_tables(client_with_temp_db, tmp_path: Path) -> None:
    admin_id = create_test_user(username="admin-missing-tables", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    conn = db.get_connection()
    try:
        _insert_asset(conn, "LIVE-KEEP")
        conn.commit()
    finally:
        conn.close()

    incomplete_db_path = tmp_path / "missing-tables.db"
    incomplete_conn = sqlite3.connect(incomplete_db_path)
    try:
        incomplete_conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY);")
        incomplete_conn.commit()
    finally:
        incomplete_conn.close()

    with incomplete_db_path.open("rb") as handle:
        response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "missing-tables.db")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 400
    assert b"missing required AssetTrack tables" in response.data
    assert _asset_tags(live_db_path) == ["LIVE-KEEP"]
    assert not restore_module.rollback_artifact_path_for(live_db_path).exists()


def test_restore_fails_closed_when_rollback_copy_cannot_be_created(
    client_with_temp_db,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id = create_test_user(username="admin-rollback-blocked", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    conn = db.get_connection()
    try:
        _insert_asset(conn, "LIVE-ONLY")
        conn.commit()
    finally:
        conn.close()

    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-blocked.db", asset_tag="RESTORE-ONLY")

    def fail_rollback(_db_path: Path, _rollback_path: Path) -> None:
        raise restore_module.RestoreOperationError("Rollback copy could not be created: blocked")

    monkeypatch.setattr(restore_module, "_create_rollback_copy", fail_rollback)

    with restore_upload_path.open("rb") as handle:
        response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-blocked.db")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 500
    assert b"Rollback copy could not be created: blocked" in response.data
    assert _asset_tags(live_db_path) == ["LIVE-ONLY"]
    assert not restore_module.recovery_state_path_for(live_db_path).exists()


def test_restore_fails_closed_when_history_write_cannot_be_completed(
    client_with_temp_db,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id = create_test_user(username="admin-history-blocked", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    conn = db.get_connection()
    try:
        _insert_asset(conn, "LIVE-ONLY")
        _insert_event(conn, "LIVE-ONLY", "live-admin")
        conn.commit()
    finally:
        conn.close()

    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-history-blocked.db", asset_tag="RESTORE-ONLY")

    def fail_history(*, db_path: Path, recovery_state: dict[str, object]) -> None:
        raise restore_module.RestoreOperationError("Restore history could not be written: blocked")

    monkeypatch.setattr(restore_module, "_append_restore_history_entry", fail_history)

    with restore_upload_path.open("rb") as handle:
        response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-history-blocked.db")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 500
    assert b"Restore history could not be written: blocked" in response.data
    assert _asset_tags(live_db_path) == ["LIVE-ONLY"]
    assert _event_count(live_db_path) == 1
    assert not restore_module.recovery_state_path_for(live_db_path).exists()
    assert _restore_history_entries(live_db_path) == []


def test_operator_cannot_access_restore_route(client_with_temp_db, tmp_path: Path) -> None:
    operator_id = create_test_user(username="operator-restore", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    get_response = client_with_temp_db.get("/admin/db/restore")
    assert get_response.status_code == 403

    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-denied.db", asset_tag="RESTORE-ONLY")
    with restore_upload_path.open("rb") as handle:
        post_response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-denied.db")},
            content_type="multipart/form-data",
        )

    assert post_response.status_code == 403


def test_admin_system_surfaces_recovery_metadata_until_acknowledged(client_with_temp_db, tmp_path: Path) -> None:
    admin_id = create_test_user(username="admin-recovery-meta", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-meta.db", asset_tag="RESTORE-ONLY")

    with restore_upload_path.open("rb") as handle:
        restore_response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-meta.db")},
            content_type="multipart/form-data",
        )

    assert restore_response.status_code == 200

    system_response = client_with_temp_db.get("/admin/system")
    assert system_response.status_code == 200
    assert b"Recovery Mode Active" in system_response.data
    assert b'id="recovery-status">Active<' in system_response.data
    assert b'id="recovery-acknowledgment">Required<' in system_response.data
    assert b"restore-meta.db" in system_response.data
    assert b"pre-restore" in system_response.data
    assert b"Acknowledge Recovery and Resume" in system_response.data
    assert b"Restore History" in system_response.data
    assert b'id="restore-history-path"' in system_response.data
    assert b"Success" in system_response.data
    assert b"Required" in system_response.data

    restarted_client = intake_app.app.test_client()
    login_session(restarted_client, admin_id)
    restarted_response = restarted_client.get("/admin/system")
    assert restarted_response.status_code == 200
    assert b"Recovery Mode Active" in restarted_response.data
    assert b'id="recovery-status">Active<' in restarted_response.data

    recovery_state_path = restore_module.recovery_state_path_for(live_db_path)
    assert recovery_state_path.exists()


def test_admin_acknowledgment_clears_recovery_state(client_with_temp_db, tmp_path: Path) -> None:
    admin_id = create_test_user(username="admin-recovery-clear", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH
    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-clear.db", asset_tag="RESTORE-ONLY")
    with restore_upload_path.open("rb") as handle:
        restore_response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-clear.db")},
            content_type="multipart/form-data",
        )
    assert restore_response.status_code == 200

    acknowledge_response = client_with_temp_db.post("/admin/recovery/acknowledge", follow_redirects=True)
    assert acknowledge_response.status_code == 200
    assert b"Recovery mode acknowledged and cleared." in acknowledge_response.data
    assert b'id="recovery-status">Inactive<' in acknowledge_response.data
    assert b'id="recovery-acknowledgment">Cleared<' in acknowledge_response.data
    assert b"Recovery Mode Active" not in acknowledge_response.data
    assert b"Cleared" in acknowledge_response.data
    assert not restore_module.recovery_state_path_for(live_db_path).exists()


def test_operator_cannot_acknowledge_recovery_state(client_with_temp_db, tmp_path: Path) -> None:
    admin_id = create_test_user(username="admin-recovery-seed", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    restore_upload_path = _build_valid_restore_db(tmp_path / "restore-seed.db", asset_tag="RESTORE-ONLY")
    with restore_upload_path.open("rb") as handle:
        restore_response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-seed.db")},
            content_type="multipart/form-data",
        )
    assert restore_response.status_code == 200

    operator_id = create_test_user(username="operator-recovery-ack", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.post("/admin/recovery/acknowledge")
    assert response.status_code == 403


def test_multiple_restores_append_history_entries_and_preserve_latest_recovery_state(
    client_with_temp_db,
    tmp_path: Path,
) -> None:
    admin_id = create_test_user(username="admin-history-multi", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    live_db_path = db.DB_PATH

    first_upload = _build_valid_restore_db(tmp_path / "restore-first.db", asset_tag="RESTORE-FIRST")
    with first_upload.open("rb") as handle:
        first_response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-first.db")},
            content_type="multipart/form-data",
        )
    assert first_response.status_code == 200

    second_upload = _build_valid_restore_db(tmp_path / "restore-second.db", asset_tag="RESTORE-SECOND")
    with second_upload.open("rb") as handle:
        second_response = client_with_temp_db.post(
            "/admin/db/restore",
            data={"db_file": (BytesIO(handle.read()), "restore-second.db")},
            content_type="multipart/form-data",
        )
    assert second_response.status_code == 200

    history_entries = _restore_history_entries(live_db_path)
    assert len(history_entries) == 2
    assert history_entries[0]["source_filename"] == "restore-first.db"
    assert history_entries[1]["source_filename"] == "restore-second.db"

    system_response = client_with_temp_db.get("/admin/system")
    assert system_response.status_code == 200
    assert b"restore-first.db" in system_response.data
    assert b"restore-second.db" in system_response.data
    assert b"Required" in system_response.data

    restarted_client = intake_app.app.test_client()
    login_session(restarted_client, admin_id)
    restarted_response = restarted_client.get("/admin/system")
    assert restarted_response.status_code == 200
    assert b"restore-first.db" in restarted_response.data
    assert b"restore-second.db" in restarted_response.data
