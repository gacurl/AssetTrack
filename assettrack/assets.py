# assettrack/assets.py
from __future__ import annotations
from typing import Any, Mapping
from assettrack.audit import record_event

import sqlite3
"""
Asset CRUD helpers.

Code-only access to the assets table.
No UI wiring.
No audit/state engine.
No legacy integration.
"""

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
    
    record_event(
        db_connection,
        asset_tag=asset_tag,
        event_type="created",
        event_date=str(asset_data.get("created_date") or ""),
        actor="system",
        payload=dict(asset_data),
    )

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


def update_asset(
    db_connection: sqlite3.Connection,
    asset_tag: str,
    **fields: Any,
) -> None:
    normalized_tag = asset_tag.strip()
    if not normalized_tag:
        raise ValueError("asset_tag is required")

    table_columns = get_asset_table_columns(db_connection)

    protected_columns = {"id", "asset_tag", "created_date"}
    allowed_columns = table_columns - protected_columns

    update_values: dict[str, Any] = {
        key: value
        for key, value in fields.items()
        if key in allowed_columns
    }

    if not update_values:
        raise ValueError("No updatable fields provided")

    if "updated_date" in table_columns and "updated_date" not in update_values:
        update_values["updated_date"] = fields.get("updated_date") or None

    set_clauses = [f"{column} = ?" for column in update_values.keys()]
    sql_statement = (
        f"UPDATE assets SET {', '.join(set_clauses)} "
        f"WHERE asset_tag = ?;"
    )
    sql_values = list(update_values.values()) + [normalized_tag]

    cursor = db_connection.execute(sql_statement, sql_values)
    db_connection.commit()

    if cursor.rowcount == 0:
        raise ValueError(f"No asset found for asset_tag={normalized_tag}")
    
    record_event(
        db_connection,
        asset_tag=normalized_tag,
        event_type="updated",
        event_date=str(update_values.get("updated_date") or ""),
        actor="system",
        payload=dict(update_values),
    )

def retire_asset(
    db_connection: sqlite3.Connection,
    asset_tag: str,
    updated_date: str | None = None,
) -> None:
    normalized_tag = asset_tag.strip()
    if not normalized_tag:
        raise ValueError("asset_tag is required")

    table_columns = get_asset_table_columns(db_connection)

    set_clauses = ["accountability_status = ?"]
    sql_values: list[Any] = ["retired"]

    if "updated_date" in table_columns:
        set_clauses.append("updated_date = ?")
        sql_values.append(updated_date)

    sql_statement = (
        f"UPDATE assets SET {', '.join(set_clauses)} "
        f"WHERE asset_tag = ?;"
    )
    sql_values.append(normalized_tag)

    cursor = db_connection.execute(sql_statement, sql_values)
    db_connection.commit()

    if cursor.rowcount == 0:
        raise ValueError(f"No asset found for asset_tag={normalized_tag}")
    
    record_event(
        db_connection,
        asset_tag=normalized_tag,
        event_type="retired",
        event_date=str(updated_date or ""),
        actor="system",
    )

