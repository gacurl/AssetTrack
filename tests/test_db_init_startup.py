from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import assettrack.db as db


def test_initialize_if_missing_or_empty_bootstraps_missing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is True
    assert db_path.exists()
    assert db_path.stat().st_size > 0
    db.assert_schema_present(db_path)


def test_initialize_if_missing_or_empty_bootstraps_zero_byte_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch()

    assert db_path.stat().st_size == 0

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is True
    assert db_path.stat().st_size > 0
    db.assert_schema_present(db_path)


def test_initialize_if_missing_or_empty_preserves_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    before_size = db_path.stat().st_size

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is False
    assert db_path.stat().st_size == before_size
    db.assert_schema_present(db_path)


def test_initialize_schema_adds_holders_organization_column(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(holders);").fetchall()}
    finally:
        conn.close()

    assert "organization" in columns


def test_initialize_if_missing_or_empty_does_not_mask_invalid_nonempty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db_path.write_bytes(b"not-a-valid-schema")

    initialized = db.initialize_if_missing_or_empty(db_path)

    assert initialized is False
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)) as exc_info:
        db.assert_schema_present(db_path)

    if isinstance(exc_info.value, RuntimeError):
        assert "AssetTrack DB schema missing." in str(exc_info.value)
