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
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Identity
            asset_tag TEXT NOT NULL UNIQUE,
            serial_number TEXT,

            -- Description
            equipment_type TEXT NOT NULL,
            manufacturer TEXT,
            model TEXT,
            model_code TEXT,

            -- Custody
            custody_state TEXT NOT NULL,
            issued_to_name TEXT,
            issued_to_role TEXT,

            -- Status
            accountability_status TEXT NOT NULL,
            condition TEXT NOT NULL,

            -- Location (asset-first; case/slot are logistics)
            location_site TEXT,
            building_room TEXT,
            case_number TEXT,
            slot_number TEXT,

            -- Timestamps (date-level is sufficient)
            created_date TEXT NOT NULL,
            updated_date TEXT
        );
        """
    )

    conn.commit()
