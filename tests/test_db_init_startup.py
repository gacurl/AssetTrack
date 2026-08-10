from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.cases import CASE_SIZE_OPTIONS


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
    assert "case_metadata" in tables
    assert "receipt_queue" in tables
    assert "app_settings" in tables


def test_bootstrap_db_adds_case_metadata_without_touching_existing_records(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE case_metadata;")
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (1, 'CASE-KEEP', 1, NULL);
            """
        )
        conn.execute(
            """
            INSERT INTO assets (asset_tag, equipment_type)
            VALUES ('KEEP-100', 'switch');
            """
        )
        conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload)
            VALUES ('KEEP-100', 'created', '2026-01-01T00:00:00Z', 'system', NULL, '{}');
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
        counts = {
            "slots": verify_conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0],
            "assets": verify_conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0],
            "asset_events": verify_conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0],
            "case_metadata": verify_conn.execute("SELECT COUNT(*) FROM case_metadata;").fetchone()[0],
        }
        case_size = verify_conn.execute("SELECT case_size FROM case_metadata WHERE case_name = 'CASE-KEEP';").fetchone()
    finally:
        verify_conn.close()

    assert "case_metadata" in tables
    assert counts == {"slots": 1, "assets": 1, "asset_events": 1, "case_metadata": 0}
    assert case_size is None


LAPTOP_CASE_SIZE_OPTIONS = (
    "10 Slot Laptop Case",
    "18 Slot Laptop Case",
    "30 Slot Laptop Case",
)


def _legacy_case_metadata_sql() -> str:
    legacy_options = tuple(option for option in CASE_SIZE_OPTIONS if option not in LAPTOP_CASE_SIZE_OPTIONS)
    values_sql = ",\n                    ".join("'" + option.replace("'", "''") + "'" for option in ("", *legacy_options))
    return f"""
        CREATE TABLE case_metadata (
            case_name TEXT PRIMARY KEY,
            case_size TEXT NOT NULL DEFAULT '',
            CHECK (
                case_size IN (
                    {values_sql}
                )
            )
        );
        """


def test_initialize_schema_case_metadata_accepts_laptop_case_sizes_and_rejects_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        for index, option in enumerate(LAPTOP_CASE_SIZE_OPTIONS, start=1):
            conn.execute(
                "INSERT INTO case_metadata (case_name, case_size) VALUES (?, ?);",
                (f"LAPTOP-{index}", option),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO case_metadata (case_name, case_size) VALUES ('BAD-CASE', 'Unsupported Laptop Case');"
            )
        rows = conn.execute(
            "SELECT case_name, case_size FROM case_metadata ORDER BY case_name ASC;"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("LAPTOP-1", "10 Slot Laptop Case"),
        ("LAPTOP-2", "18 Slot Laptop Case"),
        ("LAPTOP-3", "30 Slot Laptop Case"),
    ]


def test_bootstrap_db_migrates_case_metadata_case_size_constraint_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE case_metadata;")
        conn.execute(_legacy_case_metadata_sql())
        conn.execute("CREATE INDEX idx_case_metadata_case_size_test ON case_metadata(case_size);")
        conn.execute(
            "INSERT INTO case_metadata (case_name, case_size) VALUES ('CASE-KEEP-1', 'Small Wheel'), ('CASE-KEEP-2', '16 Rack Unit Wheel');"
        )
        conn.execute("INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (401, 'CASE-KEEP-1', 1, NULL);")
        conn.execute("INSERT INTO assets (asset_tag, equipment_type) VALUES ('KEEP-401', 'laptop');")
        conn.execute(
            "INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload) VALUES ('KEEP-401', 'created', '2026-01-01T00:00:00Z', 'system', NULL, '{\"case\":\"CASE-KEEP-1\"}');"
        )
        conn.commit()
    finally:
        conn.close()

    assert db.bootstrap_db(db_path) is False
    assert db.bootstrap_db(db_path) is False

    verify_conn = sqlite3.connect(db_path)
    try:
        metadata_rows = verify_conn.execute(
            "SELECT case_name, case_size FROM case_metadata ORDER BY case_name ASC;"
        ).fetchall()
        schema_sql = verify_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'case_metadata';"
        ).fetchone()[0]
        index_row = verify_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_case_metadata_case_size_test';"
        ).fetchone()
        counts = {
            "slots": verify_conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0],
            "assets": verify_conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0],
            "asset_events": verify_conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0],
        }
        event_payload = verify_conn.execute("SELECT payload FROM asset_events WHERE asset_tag = 'KEEP-401';").fetchone()[0]
        verify_conn.execute(
            "INSERT INTO case_metadata (case_name, case_size) VALUES ('CASE-LAPTOP', '18 Slot Laptop Case');"
        )
        with pytest.raises(sqlite3.IntegrityError):
            verify_conn.execute(
                "INSERT INTO case_metadata (case_name, case_size) VALUES ('CASE-BAD', 'Unsupported Laptop Case');"
            )
    finally:
        verify_conn.close()

    assert metadata_rows == [("CASE-KEEP-1", "Small Wheel"), ("CASE-KEEP-2", "16 Rack Unit Wheel")]
    for option in LAPTOP_CASE_SIZE_OPTIONS:
        assert option in schema_sql
    assert index_row is not None
    assert counts == {"slots": 1, "assets": 1, "asset_events": 1}
    assert event_payload == '{"case":"CASE-KEEP-1"}'

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


def test_initialize_schema_backfills_exact_slot_occupancy_on_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO assets (
                id, asset_tag, equipment_type, custody_state, accountability_status,
                condition, created_date, location_type, home_slot_id
            )
            VALUES (1, 'AT-100', 'laptop', 'in_stock', 'accountable', 'serviceable', '2026-01-01', 'STORAGE', 10);
            """
        )
        conn.execute("INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (10, 'CASE-A', 1, 'AT-100');")
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        occupancy = conn.execute("SELECT slot_id, asset_id FROM slot_occupancy;").fetchall()
    finally:
        conn.close()

    assert occupancy == [(10, 1)]


def test_initialize_schema_preserves_legacy_compact_slot_marker_backfill(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO assets (
                id, asset_tag, equipment_type, custody_state, accountability_status,
                condition, created_date, location_type, home_slot_id
            )
            VALUES (1, 'AT-200', 'laptop', 'in_stock', 'accountable', 'serviceable', '2026-01-01', 'STORAGE', 20);
            """
        )
        conn.execute("INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (20, 'CASE-B', 1, 'AT200');")
        conn.commit()
    finally:
        conn.close()

    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        occupancy = conn.execute("SELECT slot_id, asset_id FROM slot_occupancy;").fetchall()
    finally:
        conn.close()

    assert occupancy == [(20, 1)]
