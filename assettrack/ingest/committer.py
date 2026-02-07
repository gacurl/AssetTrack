# assettrack/ingest/committer.py

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from assettrack.assets import create_asset, retire_asset, update_asset
from assettrack.audit import record_event
from assettrack.db import get_connection

# Atomic batch commit layer.
# This module is the ONLY place where batch ingest rows are turned into DB writes.
# All writes happen inside a single sqlite transaction (all-or-nothing).

ALLOWED_EVENT_TYPES = {"SCAN", "ISSUE", "RETURN", "UPDATE", "RETIRE"}

class BatchCommitError(Exception):
    """Base exception for atomic batch commit failures."""


class BatchPreconditionError(BatchCommitError):
    """Raised when validated data cannot be safely committed."""


@dataclass(frozen=True)
class CommitResult:
    committed_count: int


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Compatibility shim: if get_connection() supports db_path, pass it.
    Otherwise fall back to get_connection() with no args.
    """
    if db_path is None:
        return get_connection()

    try:
        return get_connection(db_path=db_path)  # type: ignore[arg-type]
    except TypeError:
        # Older signature: get_connection() takes no params.
        return get_connection()


def commit_batch(validated_rows: list[dict[str, Any]], *, db_path: Optional[str] = None) -> CommitResult:
    """
    Commit a validated batch atomically (all-or-nothing).

    Input: validated preview output (rows with row_number + normalized data)
    Output: CommitResult on success. Raises an exception on failure (and nothing commits).
    """
    if not validated_rows:
        raise BatchPreconditionError("No rows provided for batch commit")

    conn = _get_connection(db_path)
    try:
        with conn:  # commits on success, rolls back on exception
            committed = _apply_rows(conn, validated_rows)
        return CommitResult(committed_count=committed)
    except sqlite3.Error as e:
        raise BatchCommitError(f"SQLite error during batch commit: {e}") from e
    finally:
        conn.close()


def _apply_rows(conn: sqlite3.Connection, validated_rows: list[dict[str, Any]]) -> int:
    """
    Apply all rows to the DB (called inside a single transaction).

    This function MUST NOT commit. The caller owns the transaction boundary.
    """
    committed_count = 0

    for row in validated_rows:
        # row_number comes from CSV preview; used only for human-readable errors
        row_number = row.get("row_number", "?")

        # Support either {"row_number": n, "data": {...}} OR flat dict rows
        data = row.get("data", row)

        try:
            _apply_one_event(conn, data)
            committed_count += 1
        except BatchCommitError:
            raise
        except Exception as e:
            raise BatchCommitError(f"Row {row_number} failed: {e}") from e

    return committed_count


def _asset_exists(conn: sqlite3.Connection, asset_tag: str) -> bool:
    """
    Lightweight existence check used only for create-vs-update decisions.
    """
    cursor = conn.execute(
        "SELECT 1 FROM assets WHERE asset_tag = ? LIMIT 1",
        (asset_tag,),
    )
    return cursor.fetchone() is not None


def _apply_one_event(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """
    Apply a single ingest event to the DB.

    Rules:
    - If the asset does NOT exist yet: only SCAN can create it, and equipment_type is required.
    - If the asset DOES exist: SCAN/ISSUE/RETURN/UPDATE/RETIRE are allowed.
    - This function MUST NOT commit; the caller owns the transaction boundary.
    """
    asset_tag = str(data.get("asset_tag", "")).strip().upper()
    event_type = str(data.get("event_type", "")).strip().upper()

    if not asset_tag or not event_type:
        raise BatchCommitError("Missing asset_tag or event_type")

    if event_type not in ALLOWED_EVENT_TYPES:
        raise BatchCommitError(f"Invalid event_type: {event_type}")

    exists = _asset_exists(conn, asset_tag)

    # If the asset doesn't exist yet, only SCAN can create it.
    if not exists and event_type != "SCAN":
        raise BatchCommitError(f"Asset {asset_tag} does not exist (cannot apply {event_type})")

    # If SCAN is creating a new asset, equipment_type is required.
    if not exists and event_type == "SCAN":
        equipment_type = str(data.get("equipment_type", "")).strip()
        if not equipment_type:
            raise BatchCommitError(
                f"Asset {asset_tag} does not exist; equipment_type is required to create it"
            )

    event_date = _normalize_iso8601_timestamp(str(data.get("timestamp", "")))
    actor = str(data.get("operator_id", "")).strip() or None
    notes = str(data.get("notes", "")).strip() or None

    # SCAN creates the asset if it's new; otherwise treat as an update of location-ish fields.
    if event_type == "SCAN" and not exists:
        create_asset(conn, asset_data=data)
    else:
        update_asset(
            conn,
            asset_tag,
            issued_to_name=data.get("issued_to_name"),
            operator_id=data.get("operator_id"),
            case_number=data.get("case_number"),
            slot_number=data.get("slot_number"),
            building_room=data.get("building_room"),
            updated_date=event_date,
        )

    if event_type == "RETIRE":
        retire_asset(conn, asset_tag, updated_date=event_date)

    # Always record the ingest event exactly as received (append-only audit log)
    record_event(
        conn,
        asset_tag=asset_tag,
        event_type=event_type,
        event_date=event_date,
        actor=actor,
        notes=notes,
        payload=dict(data),
    )


def _normalize_iso8601_timestamp(value: str) -> str:
    """
    Normalizes scanner timestamps (accepts trailing 'Z') and validates ISO-8601.
    Returns an ISO-8601 string acceptable to datetime.fromisoformat().
    """
    s = (value or "").strip()
    if not s:
        raise BatchCommitError("Missing timestamp")

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    from datetime import datetime

    datetime.fromisoformat(s)
    return s