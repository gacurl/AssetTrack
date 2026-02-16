# file: assettrack/db.py
import sqlite3
from pathlib import Path

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
