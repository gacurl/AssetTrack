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

    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection):
    """
    Create core tables if they do not already exist.
    No state logic, no audit tables — schema only.
    """
    cursor = conn.cursor()

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
        payload TEXT
    );
    """
    )

    if not _column_exists(conn, "asset_events", "holder_id"):
        cursor.execute(
        """
        ALTER TABLE asset_events
        ADD COLUMN holder_id INTEGER NULL;
        """
        )

    cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_asset_events_holder_id
        ON asset_events(holder_id);
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
