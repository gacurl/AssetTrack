from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import assettrack.db as db


def test_initialize_if_missing_or_empty_bootstraps_missing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is True
    assert db_path.exists()
    assert db_path.stat().st_size > 0
    db.assert_schema_present(db_path)


def test_initialize_if_missing_or_empty_bootstraps_zero_byte_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch()

    assert db_path.stat().st_size == 0

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is True
    assert db_path.stat().st_size > 0
    db.assert_schema_present(db_path)


def test_initialize_if_missing_or_empty_preserves_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    before_size = db_path.stat().st_size

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is False
    assert db_path.stat().st_size == before_size
    db.assert_schema_present(db_path)


def test_bootstrap_db_bootstraps_missing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"

    initialized = db.bootstrap_db(db_path)

    assert initialized is True
    db.assert_schema_present(db_path)


def test_bootstrap_db_applies_holder_is_active_migration_to_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                organization_id INTEGER NULL,
                identifier TEXT NULL,
                email TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE organization_buildings (
                organization_id INTEGER NOT NULL,
                building_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (organization_id, building_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE receipt_queue (
                id INTEGER PRIMARY KEY,
                receipt_key TEXT NOT NULL UNIQUE,
                receipt_type TEXT NOT NULL,
                source_event_ids_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                commit_at TEXT NOT NULL,
                commit_operator_user_id INTEGER NOT NULL,
                holder_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, organization, organization_id, identifier, email, contact_info, created_at, updated_at)
            VALUES (1, 'PERSON', 'Jane Holder', 'Ops Alpha', NULL, NULL, 'jane@example.org', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        conn.commit()
    finally:
        conn.close()

    initialized = db.bootstrap_db(db_path)

    assert initialized is False
    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(holders);").fetchall()}
        holder = conn.execute("SELECT is_active FROM holders WHERE id = 1;").fetchone()
    finally:
        conn.close()

    assert "is_active" in columns
    assert holder is not None
    assert holder[0] == 1


def test_get_connection_bootstraps_missing_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()}
    finally:
        conn.close()

    assert "assets" in tables
    assert "asset_events" in tables
    assert "receipt_queue" in tables
    assert "app_settings" in tables


def test_bootstrap_db_adds_app_settings_table_to_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                organization_id INTEGER NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                identifier TEXT NULL,
                email TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE organization_buildings (
                organization_id INTEGER NOT NULL,
                building_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (organization_id, building_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT,
                holder_id INTEGER NULL,
                supersedes_event_id INTEGER NULL,
                correction_reason TEXT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE receipt_queue (
                id INTEGER PRIMARY KEY,
                receipt_key TEXT NOT NULL UNIQUE,
                receipt_type TEXT NOT NULL,
                source_event_ids_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                commit_at TEXT NOT NULL,
                commit_operator_user_id INTEGER NOT NULL,
                holder_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    initialized = db.bootstrap_db(db_path)

    assert initialized is False
    verify_conn = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in verify_conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';")}
        columns = {row[1] for row in verify_conn.execute("PRAGMA table_info(app_settings);")}
    finally:
        verify_conn.close()

    assert "app_settings" in tables
    assert {"key", "value", "created_at", "updated_at"} <= columns


def test_get_connection_applies_holder_is_active_migration_to_existing_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                organization_id INTEGER NULL,
                identifier TEXT NULL,
                email TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE organization_buildings (
                organization_id INTEGER NOT NULL,
                building_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (organization_id, building_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE receipt_queue (
                id INTEGER PRIMARY KEY,
                receipt_key TEXT NOT NULL UNIQUE,
                receipt_type TEXT NOT NULL,
                source_event_ids_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                commit_at TEXT NOT NULL,
                commit_operator_user_id INTEGER NOT NULL,
                holder_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(holders);").fetchall()}
    finally:
        conn.close()

    assert "is_active" in columns


def test_initialize_schema_adds_holders_organization_column(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(holders);").fetchall()}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()}
    finally:
        conn.close()

    assert "organization" in columns
    assert "organization_id" in columns
    assert "email" in columns
    assert "is_active" in columns
    assert "organizations" in tables
    assert "buildings" in tables
    assert "organization_buildings" in tables
    assert "app_settings" in tables


def test_initialize_schema_creates_buildings_is_active_column(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(buildings);").fetchall()}
    finally:
        conn.close()

    assert "is_active" in columns


def test_initialize_schema_adds_building_is_active_column_to_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO buildings (id, name, created_at, updated_at)
            VALUES (1, 'HQ North', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(buildings);").fetchall()}
        building = conn.execute("SELECT is_active FROM buildings WHERE id = 1;").fetchone()
    finally:
        conn.close()

    assert "is_active" in columns
    assert building is not None
    assert building[0] == 1


def test_initialize_schema_creates_default_ad_hoc_organization(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        ad_hoc = conn.execute(
            "SELECT id, name FROM organizations WHERE name = 'Ad Hoc';"
        ).fetchone()
    finally:
        conn.close()

    assert ad_hoc is not None


def test_initialize_schema_backfills_holder_organization_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                identifier TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
            VALUES (1, 'PERSON', 'Jane Holder', 'Ops Alpha', NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        holder = conn.execute(
            "SELECT organization, organization_id FROM holders WHERE id = 1;"
        ).fetchone()
        organization = conn.execute(
            "SELECT id, name FROM organizations WHERE name = 'Ops Alpha';"
        ).fetchone()
    finally:
        conn.close()

    assert organization is not None
    assert holder is not None
    assert holder[0] == "Ops Alpha"
    assert holder[1] == organization[0]


def test_initialize_schema_creates_ad_hoc_and_backfills_null_holder_organizations(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                identifier TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
            VALUES (1, 'PERSON', 'Jane Holder', NULL, NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        holder = conn.execute(
            "SELECT organization, organization_id FROM holders WHERE id = 1;"
        ).fetchone()
        ad_hoc = conn.execute(
            "SELECT id, name FROM organizations WHERE name = 'Ad Hoc';"
        ).fetchone()
    finally:
        conn.close()

    assert ad_hoc is not None
    assert holder is not None
    assert holder[0] == "Ad Hoc"
    assert holder[1] == ad_hoc[0]


def test_initialize_schema_adds_holder_email_column_to_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                organization_id INTEGER NULL,
                identifier TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(holders);").fetchall()}
    finally:
        conn.close()

    assert "email" in columns


def test_initialize_schema_adds_holder_is_active_column_to_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE holders (
                id INTEGER PRIMARY KEY,
                holder_type TEXT NOT NULL,
                name TEXT NOT NULL,
                organization TEXT NULL,
                organization_id INTEGER NULL,
                identifier TEXT NULL,
                contact_info TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at)
            VALUES (1, 'PERSON', 'Jane Holder', 'Ops Alpha', NULL, NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                actor TEXT,
                notes TEXT,
                payload TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(holders);").fetchall()}
        holder = conn.execute("SELECT is_active FROM holders WHERE id = 1;").fetchone()
    finally:
        conn.close()

    assert "is_active" in columns
    assert holder is not None
    assert holder[0] == 1


def test_initialize_if_missing_or_empty_does_not_mask_invalid_nonempty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db_path.write_bytes(b"not-a-valid-schema")

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is False
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)) as exc_info:
        db.assert_schema_present(db_path)

    if isinstance(exc_info.value, RuntimeError):
        assert "AssetTrack DB schema missing." in str(exc_info.value)
