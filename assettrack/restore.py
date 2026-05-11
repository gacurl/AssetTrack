from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from assettrack.db import EVENT_TABLE_ALIASES

RESTORE_REQUIRED_TABLES = {
    "assets",
    "holders",
    "organizations",
    "buildings",
    "organization_buildings",
    "slots",
    "slot_occupancy",
    "users",
    "receipt_queue",
}


class RestoreError(RuntimeError):
    """Base restore error."""


class RestoreValidationError(RestoreError):
    """Raised when an uploaded database fails validation."""


class RestoreOperationError(RestoreError):
    """Raised when replacement or rollback preservation fails."""


def rollback_artifact_path_for(db_path: Path) -> Path:
    suffix = db_path.suffix or ".db"
    return db_path.with_name(f"{db_path.stem}-pre-restore{suffix}")


def recovery_state_path_for(db_path: Path) -> Path:
    return db_path.with_name(f"{db_path.stem}-recovery-state.json")


def _list_tables(conn: sqlite3.Connection) -> set[str]:
    cursor = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table';
        """
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _validate_integrity(conn: sqlite3.Connection) -> None:
    rows = [str(row[0]) for row in conn.execute("PRAGMA integrity_check;").fetchall()]
    if rows != ["ok"]:
        details = "; ".join(rows) if rows else "unknown integrity_check failure"
        raise RestoreValidationError(f"SQLite integrity check failed: {details}")


def validate_uploaded_database(candidate_path: Path) -> None:
    candidate_path = candidate_path.expanduser().resolve()
    if not candidate_path.exists() or not candidate_path.is_file():
        raise RestoreValidationError("Uploaded database file was not saved correctly.")

    try:
        conn = sqlite3.connect(candidate_path)
    except sqlite3.Error as exc:
        raise RestoreValidationError(f"Uploaded file could not be opened as SQLite: {exc}") from exc

    try:
        _validate_integrity(conn)
        existing_tables = _list_tables(conn)
    except sqlite3.Error as exc:
        raise RestoreValidationError(f"Uploaded file is not a valid SQLite database: {exc}") from exc
    finally:
        conn.close()

    missing_tables = sorted(RESTORE_REQUIRED_TABLES - existing_tables)
    if not any(name in existing_tables for name in EVENT_TABLE_ALIASES):
        missing_tables.append("asset_events")
    if missing_tables:
        raise RestoreValidationError(
            "Uploaded database is missing required AssetTrack tables: " + ", ".join(missing_tables)
        )


def _ensure_live_db_replaceable(db_path: Path) -> None:
    if not db_path.exists() or not db_path.is_file():
        raise RestoreOperationError("Current database file does not exist.")
    if not os.access(db_path, os.W_OK):
        raise RestoreOperationError("Current database file is not writable.")
    if not os.access(db_path.parent, os.W_OK):
        raise RestoreOperationError("Database directory is not writable.")


def _copy_file(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)


def _create_rollback_copy(db_path: Path, rollback_path: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=db_path.parent, prefix=f"{rollback_path.name}.", suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)

    try:
        _copy_file(db_path, temp_path)
        temp_path.replace(rollback_path)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RestoreOperationError(f"Rollback copy could not be created: {exc}") from exc


def _activate_recovery_mode(
    *,
    db_path: Path,
    rollback_path: Path,
    recovery_state_path: Path,
    source_filename: str,
) -> None:
    state = {
        "active": True,
        "recovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "db_path": str(db_path),
        "rollback_db_path": str(rollback_path),
        "source_filename": source_filename,
    }
    with tempfile.NamedTemporaryFile(
        dir=recovery_state_path.parent,
        prefix=f"{recovery_state_path.name}.",
        suffix=".tmp",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")

    try:
        temp_path.replace(recovery_state_path)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RestoreOperationError(f"Recovery mode state could not be written: {exc}") from exc


def _restore_rollback_copy(db_path: Path, rollback_path: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=db_path.parent, prefix=f"{db_path.name}.", suffix=".rollback.tmp", delete=False) as handle:
        temp_path = Path(handle.name)

    try:
        _copy_file(rollback_path, temp_path)
        temp_path.replace(db_path)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RestoreOperationError(f"Rollback restore failed after replacement error: {exc}") from exc


def restore_database(
    *,
    uploaded_db_path: Path,
    live_db_path: Path,
    source_filename: str,
) -> dict[str, str]:
    uploaded_db_path = uploaded_db_path.expanduser().resolve()
    live_db_path = live_db_path.expanduser().resolve()
    rollback_path = rollback_artifact_path_for(live_db_path)
    recovery_state_path = recovery_state_path_for(live_db_path)

    validate_uploaded_database(uploaded_db_path)
    _ensure_live_db_replaceable(live_db_path)
    _create_rollback_copy(live_db_path, rollback_path)

    with tempfile.NamedTemporaryFile(dir=live_db_path.parent, prefix=f"{live_db_path.name}.", suffix=".restore.tmp", delete=False) as handle:
        replacement_temp_path = Path(handle.name)

    try:
        _copy_file(uploaded_db_path, replacement_temp_path)
        validate_uploaded_database(replacement_temp_path)
        replacement_temp_path.replace(live_db_path)
    except Exception as exc:
        replacement_temp_path.unlink(missing_ok=True)
        if isinstance(exc, RestoreError):
            raise
        raise RestoreOperationError(f"Database replacement failed: {exc}") from exc

    try:
        validate_uploaded_database(live_db_path)
        _activate_recovery_mode(
            db_path=live_db_path,
            rollback_path=rollback_path,
            recovery_state_path=recovery_state_path,
            source_filename=source_filename,
        )
    except Exception as exc:
        _restore_rollback_copy(live_db_path, rollback_path)
        if isinstance(exc, RestoreError):
            raise
        raise RestoreOperationError(f"Post-restore validation failed: {exc}") from exc

    return {
        "live_db_path": str(live_db_path),
        "rollback_db_path": str(rollback_path),
        "recovery_state_path": str(recovery_state_path),
    }
