# assettrack/ingest/committer.py

from __future__ import annotations

import sqlite3
from typing import Any

from assettrack.db import get_connection

ALLOWED_EVENT_TYPES = {"SCAN", "ISSUE", "RETURN", "UPDATE", "RETIRE"}

# Rule: if asset does NOT exist yet, only SCAN is allowed to create it.
CREATE_EVENT_TYPES = {"SCAN"}

# Rule: if asset DOES exist, these are allowed.
UPDATE_EVENT_TYPES = {"SCAN", "ISSUE", "RETURN", "UPDATE", "RETIRE"}

class BatchCommitError(Exception):
    """Base exception for atomic batch commit failures."""
    pass

class BatchPreconditionError(BatchCommitError):
    """Raised when validated data cannot be safely committed."""
    pass

def _apply_rows(conn: sqlite3.Connection, validated_rows: list[dict[str, Any]]) -> None:
    """
    Apply all rows to the DB (called inside a single transaction).

    This function MUST NOT commit. The caller owns the transaction boundary.
    """
    for row in validated_rows:
        row_number = row.get("row_number", "?")

        # Support either {"row_number": n, "data": {...}} OR flat dict rows
        data = row.get("data", row)

        try:
            _apply_one_event(conn, data)
        except BatchCommitError:
            raise
        except Exception as e:
            raise BatchCommitError(f"Row {row_number} failed: {e}") from e

def _asset_exists(conn: sqlite3.Connection, asset_tag: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM assets WHERE asset_tag = ? LIMIT 1",
        (asset_tag,),
    )
    return cursor.fetchone() is not None

def _apply_one_event(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """
    Apply a single ingest event to the DB.

    For Issue 3-4, this should:
      - enforce existence rules (create vs update)
      - update the asset row (or create it)
      - record the audit event
    """
    asset_tag = str(data.get("asset_tag", "")).strip().upper()
    event_type = str(data.get("event_type", "")).strip().upper()

    if not asset_tag or not event_type:
        raise BatchCommitError("Missing asset_tag or event_type")

    if event_type not in ALLOWED_EVENT_TYPES:
        raise BatchCommitError(f"Invalid event_type: {event_type}")

    exists = _asset_exists(conn, asset_tag)
    if event_type in CREATE_EVENT_TYPES and not exists:
        equipment_type = str(data.get("equipment_type", "")).strip()
        if not equipment_type:
            raise BatchCommitError(
                f"Asset {asset_tag} does not exist; equipment_type is required to create it"
            )

    if event_type in CREATE_EVENT_TYPES and exists:
        raise BatchCommitError(f"Asset {asset_tag} already exists (cannot create via {event_type})")

    if event_type in UPDATE_EVENT_TYPES and not exists:
        # enforce create rule here (validator TODO)
        raise BatchCommitError(f"Asset {asset_tag} does not exist (cannot apply {event_type})")

def commit_batch(validated_rows: list[dict]) -> None:
    """
    Commit a validated batch atomically (all-or-nothing).
    
    Input: validated preview output (rows with row_number + normalized data)
    Output: None on success. Raises an exception on failure (and nothing commits).
    """
    if not validated_rows:
        raise BatchPreconditionError("No rows provided for batch commit")
    
    conn = get_connection()
    try:
        with conn:  # commits on success, rolls back on exception
            _apply_rows(conn, validated_rows)
    except sqlite3.Error as e:
        raise BatchCommitError(f"SQLite error during batch commit: {e}") from e
    finally:
        conn.close()

def _normalize_iso8601_timestamp(value: str) -> str:
    s = (value or "").strip()
    if not s:
        raise BatchCommitError("Missing timestamp")

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # Validate
    from datetime import datetime
    datetime.fromisoformat(s)
    return s
