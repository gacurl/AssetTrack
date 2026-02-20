# assettrack/db.py
import sqlite3
from pathlib import Path


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


# Canonical DB location (local-only, gitignored)
DB_PATH = Path("data/assettrack.db")


def get_connection():
    """
    Returns a SQLite connection to the AssetTrack database.
    Ensures the database and schema exist.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # SQLite only enforces foreign keys when enabled.
    conn.execute("PRAGMA foreign_keys = ON;")

    _create_schema(conn)
    return conn


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
            identifier TEXT NULL,
            contact_info TEXT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
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

    if _table_exists(conn, "assets"):
        cursor.execute(
            """
            INSERT OR IGNORE INTO slot_occupancy (slot_id, asset_id, assigned_at)
            SELECT s.id, a.id, '1970-01-01T00:00:00Z'
            FROM slots s
            JOIN assets a
              ON UPPER(a.asset_tag) = UPPER(s.current_asset_tag)
              OR REPLACE(UPPER(a.asset_tag), '-', '') = UPPER(s.current_asset_tag)
            WHERE s.current_asset_tag IS NOT NULL
              AND TRIM(s.current_asset_tag) <> '';
            """
        )

    conn.commit()
