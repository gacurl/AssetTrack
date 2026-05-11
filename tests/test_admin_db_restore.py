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
