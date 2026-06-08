from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from email.utils import getaddresses

from assettrack.db import get_connection

RECEIPT_CC_SETTING_KEY = "receipt_cc_addresses"
ALLOWED_SETTING_KEYS = {RECEIPT_CC_SETTING_KEY}


def _validate_key(key: str) -> str:
    normalized = str(key or "").strip()
    if normalized not in ALLOWED_SETTING_KEYS:
        raise ValueError("Unsupported app setting key.")
    return normalized


def read_setting(conn: sqlite3.Connection, key: str) -> str | None:
    setting_key = _validate_key(key)
    row = conn.execute(
        """
        SELECT value
        FROM app_settings
        WHERE key = ?;
        """,
        (setting_key,),
    ).fetchone()
    if row is None:
        return None
    return str(row["value"] if isinstance(row, sqlite3.Row) else row[0])


def write_setting(conn: sqlite3.Connection, key: str, value: str) -> str:
    setting_key = _validate_key(key)
    normalized_value = str(value or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO app_settings (key, value, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at;
        """,
        (setting_key, normalized_value, now_iso, now_iso),
    )
    return normalized_value


def clear_setting(conn: sqlite3.Connection, key: str) -> None:
    setting_key = _validate_key(key)
    conn.execute(
        """
        DELETE FROM app_settings
        WHERE key = ?;
        """,
        (setting_key,),
    )


def read_receipt_cc_setting(conn: sqlite3.Connection) -> str | None:
    return read_setting(conn, RECEIPT_CC_SETTING_KEY)


def write_receipt_cc_setting(conn: sqlite3.Connection, value: str) -> str:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        clear_receipt_cc_setting(conn)
        return ""
    return write_setting(conn, RECEIPT_CC_SETTING_KEY, normalized_value)


def clear_receipt_cc_setting(conn: sqlite3.Connection) -> None:
    clear_setting(conn, RECEIPT_CC_SETTING_KEY)


def normalize_receipt_cc_addresses(raw_addresses: str) -> list[str]:
    raw_value = str(raw_addresses or "").strip()
    if not raw_value:
        return []

    normalized: list[str] = []
    invalid: list[str] = []
    for _, email_address in getaddresses([raw_value.replace("\n", ",")]):
        candidate = str(email_address or "").strip().lower()
        if not _is_valid_email_address(candidate):
            invalid.append(candidate or "blank entry")
            continue
        if candidate not in normalized:
            normalized.append(candidate)

    if invalid or not normalized:
        invalid_display = ", ".join(invalid) if invalid else raw_value
        raise ValueError(f"Invalid receipt CC address: {invalid_display}")

    return normalized


def save_receipt_cc_addresses(conn: sqlite3.Connection, raw_addresses: str) -> list[str]:
    addresses = normalize_receipt_cc_addresses(raw_addresses)
    if not addresses:
        clear_receipt_cc_setting(conn)
        return []
    write_receipt_cc_setting(conn, "\n".join(addresses))
    return addresses


def _is_valid_email_address(value: str) -> bool:
    if not value or any(char.isspace() for char in value):
        return False
    if value.count("@") != 1:
        return False
    local_part, domain = value.split("@", 1)
    if not local_part or not domain or "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    return True


def active_receipt_cc_setting() -> str:
    conn = get_connection()
    try:
        configured = read_receipt_cc_setting(conn)
    finally:
        conn.close()

    if configured is not None:
        return configured
    return str(os.getenv("ASSETTRACK_RECEIPT_CC_EMAIL") or "").strip()
