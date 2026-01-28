# assettrack/assets.py
"""
Asset CRUD helpers.

Code-only access to the assets table.
No UI wiring.
No audit/state engine.
No legacy integration.
"""

from __future__ import annotations

from typing import Any, Mapping
import sqlite3

def get_asset_table_columns(db_connection: sqlite3.Connection) -> set[str]:
    """Return column names for the assets table."""
    cursor = db_connection.execute("PRAGMA table_info(assets);")
    rows = cursor.fetchall()
    return {row[1] for row in rows}

def create_asset(
    db_connection: sqlite3.Connection,
    asset_data: Mapping[str, Any],
) -> None:
    """
    Insert a new asset row.
    Requires:
      - asset_tag
    """
    asset_tag = str(asset_data.get("asset_tag", "")).strip()
    if not asset_tag:
        raise ValueError("asset_tag is required")

    table_columns = get_asset_table_columns(db_connection)

    insert_values: dict[str, Any] = {
        key: value
        for key, value in asset_data.items()
        if key in table_columns
    }

    insert_values["asset_tag"] = asset_tag

    if "retired" in table_columns and "retired" not in insert_values:
        insert_values["retired"] = 0

    column_names = list(insert_values.keys())
    placeholders = ", ".join("?" for _ in column_names)

    sql_statement = (
        f"INSERT INTO assets ({', '.join(column_names)}) "
        f"VALUES ({placeholders});"
    )

    sql_values = [insert_values[column] for column in column_names]

    try:
        db_connection.execute(sql_statement, sql_values)
        db_connection.commit()
    except sqlite3.IntegrityError as error:
        raise ValueError(f"create_asset failed: {error}") from error


def get_asset_by_tag(
    db_connection: sqlite3.Connection,
    asset_tag: str,
) -> dict | None:
    normalized_tag = asset_tag.strip()
    if not normalized_tag:
        return None

    cursor = db_connection.execute(
        "SELECT * FROM assets WHERE asset_tag = ?;",
        (normalized_tag,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def update_asset(conn: sqlite3.Connection, asset_tag: str, **fields) -> None:
    """Update one or more fields on an asset."""
    raise NotImplementedError


def retire_asset(conn: sqlite3.Connection, asset_tag: str) -> None:
    """Soft-retire an asset (no hard deletes)."""
    raise NotImplementedError
