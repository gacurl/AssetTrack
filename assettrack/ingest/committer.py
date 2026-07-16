# assettrack/ingest/committer.py

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from assettrack.assets import SUPPORTED_EQUIPMENT_TYPE_MESSAGE, create_asset, retire_asset, update_asset, validate_new_equipment_type
from assettrack.audit import record_event
from assettrack.db import bootstrap_db, get_connection

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
    if db_path is None:
        return get_connection()

    path = Path(db_path)
    bootstrap_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


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


def _assign_new_asset_to_home_slot(
    conn: sqlite3.Connection,
    *,
    asset_tag: str,
    event_date: str,
    actor: str | None,
    notes: str | None,
    data: dict[str, Any],
) -> None:
    home_slot_raw = data.get("home_slot_id")
    case_number = str(data.get("case_number", "")).strip().upper()
    slot_number_raw = str(data.get("slot_number", "")).strip()

    slot_row: sqlite3.Row | None = None
    if home_slot_raw not in {None, ""}:
        try:
            home_slot_id = int(str(home_slot_raw).strip())
        except ValueError as e:
            raise BatchCommitError("home_slot_id must be an integer") from e
        slot_row = conn.execute(
            """
            SELECT id, case_name, slot_position, current_asset_tag
            FROM slots
            WHERE id = ?
            LIMIT 1;
            """,
            (home_slot_id,),
        ).fetchone()
        if slot_row is None:
            raise BatchCommitError(f"home_slot_id does not reference an existing slot for {asset_tag}")
    elif case_number or slot_number_raw:
        if not case_number or not slot_number_raw:
            raise BatchCommitError(f"case_number and slot_number must both be present for {asset_tag}")
        try:
            slot_position = int(slot_number_raw)
        except ValueError as e:
            raise BatchCommitError(f"slot_number must be an integer for {asset_tag}") from e
        slot_row = conn.execute(
            """
            SELECT id, case_name, slot_position, current_asset_tag
            FROM slots
            WHERE UPPER(case_name) = UPPER(?)
              AND slot_position = ?
            LIMIT 1;
            """,
            (case_number, slot_position),
        ).fetchone()
        if slot_row is None:
            raise BatchCommitError(f"Selected slot does not exist for {asset_tag}")

    asset_row = conn.execute(
        """
        SELECT id
        FROM assets
        WHERE UPPER(asset_tag) = UPPER(?)
        LIMIT 1;
        """,
        (asset_tag,),
    ).fetchone()
    if asset_row is None:
        raise BatchCommitError(f"Asset {asset_tag} was not created")

    # Normalize new intake-created assets into storage semantics used by issue/return flows.
    asset_columns = {row[1] for row in conn.execute("PRAGMA table_info(assets);").fetchall()}
    update_clauses: list[str] = []
    update_values: list[Any] = []
    if "location_type" in asset_columns:
        update_clauses.append("location_type = ?")
        update_values.append("STORAGE")
    if "current_holder_id" in asset_columns:
        update_clauses.append("current_holder_id = NULL")
    if "home_slot_id" in asset_columns:
        update_clauses.append("home_slot_id = ?")
        update_values.append(None if slot_row is None else int(slot_row["id"]))
    if "updated_date" in asset_columns:
        update_clauses.append("updated_date = ?")
        update_values.append(event_date)
    if update_clauses:
        update_values.append(int(asset_row["id"]))
        conn.execute(
            f"UPDATE assets SET {', '.join(update_clauses)} WHERE id = ?;",
            tuple(update_values),
        )

    if slot_row is None:
        return

    occupied = conn.execute(
        """
        SELECT 1
        FROM slot_occupancy
        WHERE slot_id = ?
        LIMIT 1;
        """,
        (int(slot_row["id"]),),
    ).fetchone()
    if occupied:
        raise BatchCommitError(f"Selected slot is already occupied for {asset_tag}")
    if str(slot_row["current_asset_tag"] or "").strip():
        raise BatchCommitError(f"Selected slot is already occupied for {asset_tag}")

    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (?, ?, ?);
        """,
        (int(slot_row["id"]), int(asset_row["id"]), event_date),
    )
    conn.execute(
        """
        UPDATE slots
        SET current_asset_tag = ?
        WHERE id = ?;
        """,
        (asset_tag, int(slot_row["id"])),
    )

    record_event(
        conn,
        asset_tag=asset_tag,
        event_type="SLOT_ASSIGN",
        event_date=event_date,
        actor=actor,
        notes=notes,
        payload={
            "slot_id": int(slot_row["id"]),
            "case_number": str(slot_row["case_name"] or ""),
            "slot_number": int(slot_row["slot_position"]),
            "equipment_type": str(data.get("equipment_type", "") or "").strip(),
        },
    )


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
        try:
            data["equipment_type"] = validate_new_equipment_type(equipment_type)
        except ValueError as exc:
            raise BatchCommitError(str(exc) or SUPPORTED_EQUIPMENT_TYPE_MESSAGE) from exc

    event_date = _normalize_iso8601_timestamp(str(data.get("timestamp", "")))
    actor = str(data.get("operator_id", "")).strip() or None
    notes = str(data.get("notes", "")).strip() or None

    # SCAN creates the asset if it's new; otherwise treat as an update of location-ish fields.
    if event_type == "SCAN" and not exists:
        create_asset(conn, asset_data=data)
        _assign_new_asset_to_home_slot(
            conn,
            asset_tag=asset_tag,
            event_date=event_date,
            actor=actor,
            notes=notes,
            data=data,
        )
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
