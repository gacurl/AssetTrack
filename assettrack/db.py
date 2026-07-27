# assettrack/db.py
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_TABLES = {
    "app_settings",
    "assets",
    "holders",
    "organizations",
    "buildings",
    "organization_buildings",
    "receipt_queue",
}
EVENT_TABLE_ALIASES = ("events", "asset_events")
DEFAULT_AD_HOC_ORGANIZATION = "Ad Hoc"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = ?
        LIMIT 1;
        """,
        (table_name,),
    )
    return cursor.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table_name});")
    rows = cursor.fetchall()
    return any(row[1] == column_name for row in rows)


def _rebuild_asset_events_for_corrections(conn: sqlite3.Connection) -> None:
    """
    SQLite-safe migration for Issue 12-1.

    Rebuilds asset_events so FK + CHECK constraints are actually enforced.

    Steps:
      1) Create asset_events_new with the latest columns + constraints
      2) Copy existing rows
      3) Drop old asset_events
      4) Rename asset_events_new -> asset_events
      5) Recreate indexes
    """
    # SQLite only enforces foreign keys when enabled.
    conn.execute("PRAGMA foreign_keys = ON;")

    has_holder_id = _column_exists(conn, "asset_events", "holder_id")

    conn.execute(
        """
        CREATE TABLE asset_events_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Link (FK-like, kept lightweight/offline-friendly)
            asset_tag TEXT NOT NULL,

            -- Event details
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            actor TEXT,
            notes TEXT,
            payload TEXT,

            -- Existing optional field (added via ALTER in older schema)
            holder_id INTEGER NULL,

            -- Amend-only correction model
            supersedes_event_id INTEGER NULL,
            correction_reason TEXT NULL,

            -- Enforce: if supersedes_event_id is set, correction_reason must be non-empty
            CHECK (
                supersedes_event_id IS NULL
                OR length(trim(correction_reason)) > 0
            ),

            -- Enforce: supersedes_event_id must reference an existing event id
            --
            -- NOTE: during rebuild, reference the new table name so SQLite accepts the FK.
            -- After rename, it behaves as asset_events(id).
            FOREIGN KEY (supersedes_event_id) REFERENCES asset_events_new(id)
        );
        """
    )

    if has_holder_id:
        conn.execute(
            """
            INSERT INTO asset_events_new (
                id, asset_tag, event_type, event_date, actor, notes, payload, holder_id
            )
            SELECT
                id, asset_tag, event_type, event_date, actor, notes, payload, holder_id
            FROM asset_events;
            """
        )
    else:
        conn.execute(
            """
            INSERT INTO asset_events_new (
                id, asset_tag, event_type, event_date, actor, notes, payload, holder_id
            )
            SELECT
                id, asset_tag, event_type, event_date, actor, notes, payload, NULL
            FROM asset_events;
            """
        )

    conn.execute("DROP TABLE asset_events;")
    conn.execute("ALTER TABLE asset_events_new RENAME TO asset_events;")

    # Recreate indexes
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_asset_events_holder_id
            ON asset_events(holder_id);
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_events_supersede_once
            ON asset_events(supersedes_event_id)
            WHERE supersedes_event_id IS NOT NULL;
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_asset_events_supersedes
            ON asset_events(supersedes_event_id);
        """
    )


# Database location:
# - Defaults to local development path (data/assettrack.db)
# - Can be overridden via ASSETTRACK_DB_PATH for Docker/WSL persistence
DB_PATH = Path(os.environ.get("ASSETTRACK_DB_PATH", "data/assettrack.db"))


def initialize_schema(db_path: Path) -> None:
    """
    Create the approved AssetTrack schema at the given path.
    Safe to run repeatedly against an existing valid database.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # SQLite only enforces foreign keys when enabled.
        conn.execute("PRAGMA foreign_keys = ON;")
        _create_schema(conn)
    finally:
        conn.close()


def initialize_if_missing_or_empty(db_path: Path) -> bool:
    """
    Initialize schema only for first-run DB paths.
    Returns True when schema bootstrap was performed.
    """
    if db_path.exists() and db_path.stat().st_size > 0:
        return False

    initialize_schema(db_path)
    return True


def bootstrap_db(db_path: Path) -> bool:
    """
    Ensure the approved schema is present before any query path runs.
    Returns True when first-run bootstrap was performed.
    """
    initialized = initialize_if_missing_or_empty(db_path)
    if not initialized:
        initialize_schema(db_path)
    assert_schema_present(db_path)
    return initialized


def assert_schema_present(db_path: Path) -> None:
    """
    Validate that a DB file contains the required AssetTrack tables.
    Raises RuntimeError when schema is missing/incomplete.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table';
            """
        )
        existing_tables = {str(row[0]) for row in cursor.fetchall()}
    finally:
        conn.close()

    missing_tables = sorted(REQUIRED_TABLES - existing_tables)
    if not any(name in existing_tables for name in EVENT_TABLE_ALIASES):
        missing_tables.append("events")

    if missing_tables:
        missing_display = ", ".join(missing_tables)
        raise RuntimeError(
            "AssetTrack DB schema missing.\n"
            f"DB: {db_path}\n"
            f"Missing tables: {missing_display}\n"
            "Restore a valid database or initialize the approved schema."
        )


def get_connection():
    """
    Returns a SQLite connection to the AssetTrack database.
    Ensures the database and schema exist.
    """
    bootstrap_db(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # SQLite only enforces foreign keys when enabled.
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _backfill_slot_occupancy(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO slot_occupancy (slot_id, asset_id, assigned_at)
        SELECT s.id, a.id, '1970-01-01T00:00:00Z'
        FROM slots s
        JOIN assets a
          ON a.asset_tag = s.current_asset_tag
        WHERE s.current_asset_tag IS NOT NULL
          AND TRIM(s.current_asset_tag) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM slot_occupancy so
              WHERE so.slot_id = s.id
          );
        """
    )

    unresolved_slots = conn.execute(
        """
        SELECT s.id, s.current_asset_tag
        FROM slots s
        WHERE s.current_asset_tag IS NOT NULL
          AND TRIM(s.current_asset_tag) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM slot_occupancy so
              WHERE so.slot_id = s.id
          );
        """
    ).fetchall()
    if not unresolved_slots:
        return

    compact_asset_ids = {
        str(row["asset_tag"] or "").strip().upper().replace("-", ""): int(row["id"])
        for row in conn.execute("SELECT id, asset_tag FROM assets;").fetchall()
    }
    backfill_rows = []
    for slot in unresolved_slots:
        compact_tag = str(slot["current_asset_tag"] or "").strip().upper()
        asset_id = compact_asset_ids.get(compact_tag)
        if asset_id is not None:
            backfill_rows.append((int(slot["id"]), asset_id, "1970-01-01T00:00:00Z"))
    if backfill_rows:
        conn.executemany(
            """
            INSERT OR IGNORE INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, ?);
            """,
            backfill_rows,
        )


def _create_schema(conn: sqlite3.Connection):
    """
    Create core tables if they do not already exist.
    No state logic, no audit tables — schema only.
    """
    cursor = conn.cursor()

    # Base table creation (new installs get the latest schema)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Link (FK-like, kept lightweight/offline-friendly)
            asset_tag TEXT NOT NULL,

            -- Event details
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            actor TEXT,
            notes TEXT,
            payload TEXT,

            -- Existing optional field (added via ALTER in older schema)
            holder_id INTEGER NULL,

            -- Amend-only correction model
            supersedes_event_id INTEGER NULL,
            correction_reason TEXT NULL,

            CHECK (
                supersedes_event_id IS NULL
                OR length(trim(correction_reason)) > 0
            ),

            FOREIGN KEY (supersedes_event_id) REFERENCES asset_events(id)
        );
        """
    )

    # Backward-compat support: older DBs may not have holder_id.
    if not _column_exists(conn, "asset_events", "holder_id"):
        cursor.execute(
            """
            ALTER TABLE asset_events
            ADD COLUMN holder_id INTEGER NULL;
            """
        )

    # Issue 12-1: if supersedes_event_id isn't present, rebuild the table so FK + CHECK are enforced.
    if not _column_exists(conn, "asset_events", "supersedes_event_id"):
        _rebuild_asset_events_for_corrections(conn)

    # Ensure indexes exist (safe to run repeatedly)
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_asset_events_holder_id
            ON asset_events(holder_id);
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_events_supersede_once
            ON asset_events(supersedes_event_id)
            WHERE supersedes_event_id IS NOT NULL;
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_asset_events_supersedes
            ON asset_events(supersedes_event_id);
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_tag TEXT NOT NULL UNIQUE,
            serial_number TEXT NULL,
            equipment_type TEXT NULL,
            manufacturer TEXT NULL,
            model TEXT NULL,
            model_code TEXT NULL,
            custody_state TEXT NULL,
            issued_to_name TEXT NULL,
            issued_to_role TEXT NULL,
            accountability_status TEXT NULL,
            condition TEXT NULL,
            location_site TEXT NULL,
            building_room TEXT NULL,
            case_number TEXT NULL,
            slot_number TEXT NULL,
            created_date TEXT NULL,
            updated_date TEXT NULL,
            location_type TEXT NULL,
            current_holder_id INTEGER NULL,
            home_slot_id INTEGER NULL REFERENCES slots(id),
            notes TEXT NULL,
            building TEXT NULL,
            room TEXT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS buildings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_buildings (
            organization_id INTEGER NOT NULL REFERENCES organizations(id),
            building_id INTEGER NOT NULL REFERENCES buildings(id),
            created_at TEXT NOT NULL,
            PRIMARY KEY (organization_id, building_id)
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY,
            case_name TEXT NOT NULL,
            slot_position INTEGER NOT NULL,
            current_asset_tag TEXT NULL,
            UNIQUE(case_name, slot_position)
        );
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_slots_current_asset_tag
            ON slots(current_asset_tag);
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS slot_occupancy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id INTEGER NOT NULL REFERENCES slots(id),
            asset_id INTEGER NOT NULL REFERENCES assets(id),
            assigned_at TEXT NOT NULL,
            UNIQUE(slot_id),
            UNIQUE(asset_id)
        );
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_slot_occupancy_slot_id
            ON slot_occupancy(slot_id);
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_slot_occupancy_asset_id
            ON slot_occupancy(asset_id);
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS holders (
            id INTEGER PRIMARY KEY,
            holder_type TEXT NOT NULL,
            name TEXT NOT NULL,
            organization TEXT NULL,
            organization_id INTEGER NULL REFERENCES organizations(id),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            identifier TEXT NULL,
            email TEXT NULL,
            contact_info TEXT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'operator')),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS receipt_queue (
            id INTEGER PRIMARY KEY,
            receipt_key TEXT NOT NULL UNIQUE,
            receipt_type TEXT NOT NULL CHECK(receipt_type IN ('ISSUE', 'RETURN')),
            source_event_ids_json TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            commit_at TEXT NOT NULL,
            commit_operator_user_id INTEGER NOT NULL,
            holder_id INTEGER NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sent_at TEXT NULL,
            last_attempt_at TEXT NULL,
            last_error TEXT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(key IN ('receipt_cc_addresses'))
        );
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_receipt_queue_commit_at
            ON receipt_queue(commit_at);
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_receipt_queue_holder_id
            ON receipt_queue(holder_id);
        """
    )

    if _table_exists(conn, "users") and not _column_exists(conn, "users", "active"):
        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN active INTEGER NOT NULL DEFAULT 1;
            """
        )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_holders_name
            ON holders(name);
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_holders_identifier
            ON holders(identifier);
        """
    )
    # Issue 23-5: startup migration for nullable holder organization metadata.
    if _table_exists(conn, "holders") and not _column_exists(conn, "holders", "organization"):
        cursor.execute(
            """
            ALTER TABLE holders
            ADD COLUMN organization TEXT NULL;
            """
        )
    if _table_exists(conn, "holders") and not _column_exists(conn, "holders", "organization_id"):
        cursor.execute(
            """
            ALTER TABLE holders
            ADD COLUMN organization_id INTEGER NULL REFERENCES organizations(id);
            """
        )
    if _table_exists(conn, "holders") and not _column_exists(conn, "holders", "email"):
        cursor.execute(
            """
            ALTER TABLE holders
            ADD COLUMN email TEXT NULL;
            """
        )
    if _table_exists(conn, "holders") and not _column_exists(conn, "holders", "is_active"):
        cursor.execute(
            """
            ALTER TABLE holders
            ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;
            """
        )
    if _table_exists(conn, "buildings") and not _column_exists(conn, "buildings", "is_active"):
        cursor.execute(
            """
            ALTER TABLE buildings
            ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1));
            """
        )

    if _table_exists(conn, "assets"):
        if not _column_exists(conn, "assets", "location_type"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN location_type TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "current_holder_id"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN current_holder_id INTEGER NULL;
                """
            )
        if not _column_exists(conn, "assets", "home_slot_id"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN home_slot_id INTEGER NULL REFERENCES slots(id);
                """
            )
        if not _column_exists(conn, "assets", "serial_number"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN serial_number TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "manufacturer"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN manufacturer TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "model"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN model TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "model_code"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN model_code TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "notes"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN notes TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "building"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN building TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "room"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN room TEXT NULL;
                """
            )
        if not _column_exists(conn, "assets", "building_room"):
            cursor.execute(
                """
                ALTER TABLE assets
                ADD COLUMN building_room TEXT NULL;
                """
            )

    if _table_exists(conn, "holders") and _table_exists(conn, "organizations"):
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT OR IGNORE INTO organizations (name, created_at, updated_at)
            VALUES (?, ?, ?);
            """,
            (DEFAULT_AD_HOC_ORGANIZATION, now_iso, now_iso),
        )
        cursor.execute(
            """
            INSERT OR IGNORE INTO organizations (name, created_at, updated_at)
            SELECT DISTINCT TRIM(organization), ?, ?
            FROM holders
            WHERE TRIM(COALESCE(organization, '')) <> '';
            """,
            (now_iso, now_iso),
        )
        cursor.execute(
            """
            UPDATE holders
            SET organization_id = (
                SELECT o.id
                FROM organizations o
                WHERE UPPER(o.name) = UPPER(holders.organization)
                LIMIT 1
            )
            WHERE organization_id IS NULL
              AND TRIM(COALESCE(organization, '')) <> '';
            """
        )
        cursor.execute(
            """
            UPDATE holders
            SET organization_id = (
                SELECT o.id
                FROM organizations o
                WHERE UPPER(o.name) = UPPER(?)
                LIMIT 1
            )
            WHERE organization_id IS NULL;
            """,
            (DEFAULT_AD_HOC_ORGANIZATION,),
        )
        cursor.execute(
            """
            UPDATE holders
            SET organization = (
                SELECT o.name
                FROM organizations o
                WHERE o.id = holders.organization_id
                LIMIT 1
            )
            WHERE organization_id IS NOT NULL;
            """
        )

    if _table_exists(conn, "assets"):
        _backfill_slot_occupancy(conn)

    conn.commit()


def _run_init_cli() -> int:
    conn = get_connection()
    conn.close()
    print(f"AssetTrack schema initialized at {DB_PATH}")
    return 0


def _run_reset_cli() -> int:
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH}")
        return 0

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        with conn:
            if _table_exists(conn, "slot_occupancy"):
                conn.execute("DELETE FROM slot_occupancy;")
            if _table_exists(conn, "asset_events"):
                conn.execute("DELETE FROM asset_events;")
            if _table_exists(conn, "assets"):
                conn.execute("DELETE FROM assets;")
            if _table_exists(conn, "slots"):
                conn.execute("DELETE FROM slots;")
        conn.execute("VACUUM;")
    finally:
        conn.close()

    print("AssetTrack operational tables cleared")
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "init":
        raise SystemExit(_run_init_cli())
    if command == "reset":
        raise SystemExit(_run_reset_cli())

    print("Usage: python -m assettrack.db init|reset")
    raise SystemExit(1)
