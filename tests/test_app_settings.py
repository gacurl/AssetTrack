from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.settings import (
    active_receipt_cc_setting,
    clear_receipt_cc_setting,
    read_receipt_cc_setting,
    write_receipt_cc_setting,
    write_setting,
)


def test_receipt_cc_setting_persists_across_sqlite_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            saved = write_receipt_cc_setting(conn, "  Ops@example.org\nAudit@example.org  ")
    finally:
        conn.close()

    assert saved == "Ops@example.org\nAudit@example.org"

    reopened = sqlite3.connect(db_path)
    reopened.row_factory = sqlite3.Row
    try:
        assert read_receipt_cc_setting(reopened) == "Ops@example.org\nAudit@example.org"
    finally:
        reopened.close()


def test_clear_receipt_cc_setting_removes_local_value_and_restores_env_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "fallback@example.org")

    conn = db.get_connection()
    try:
        with conn:
            write_receipt_cc_setting(conn, "local@example.org")
        assert active_receipt_cc_setting() == "local@example.org"

        with conn:
            clear_receipt_cc_setting(conn)
    finally:
        conn.close()

    assert active_receipt_cc_setting() == "fallback@example.org"


def test_blank_receipt_cc_setting_clears_local_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    monkeypatch.delenv("ASSETTRACK_RECEIPT_CC_EMAIL", raising=False)

    conn = db.get_connection()
    try:
        with conn:
            write_receipt_cc_setting(conn, "local@example.org")
        assert active_receipt_cc_setting() == "local@example.org"

        with conn:
            saved = write_receipt_cc_setting(conn, "   ")
        assert saved == ""
    finally:
        conn.close()

    assert active_receipt_cc_setting() == ""


def test_settings_reject_unsupported_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with pytest.raises(ValueError, match="Unsupported app setting key"):
            write_setting(conn, "broad_notification_setting", "enabled")
    finally:
        conn.close()
