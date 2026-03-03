# assettrack/users.py
from __future__ import annotations

from datetime import datetime, timezone

import bcrypt

from assettrack.db import get_connection

ALLOWED_ROLES = {"admin", "operator"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bcrypt_hash(password: str) -> str:
    if not password:
        raise ValueError("password is required")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    password_hash = password_hash.decode("utf-8")
    if not password_hash.startswith("$2"):
        raise ValueError("bcrypt hash generation failed")
    return password_hash


def count_users() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM users;").fetchone()
        return int(row["c"])
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    normalized = (username or "").strip()
    if not normalized:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? LIMIT 1;",
            (normalized,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    try:
        normalized_id = int(user_id)
    except (TypeError, ValueError):
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? LIMIT 1;",
            (normalized_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_user(username: str, password: str, role: str, active: bool = True) -> dict:
    normalized_username = (username or "").strip()
    normalized_role = (role or "").strip().lower()
    if not normalized_username:
        raise ValueError("username is required")
    if normalized_role not in ALLOWED_ROLES:
        raise ValueError("role must be admin or operator")

    now_iso = _now_iso()
    password_hash = _bcrypt_hash(password)
    active_int = 1 if bool(active) else 0
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, role, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (normalized_username, password_hash, normalized_role, active_int, now_iso, now_iso),
        )
        conn.commit()
        created_id = int(cursor.lastrowid)
        row = conn.execute("SELECT * FROM users WHERE id = ?;", (created_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def verify_password(user: dict | None, password: str) -> bool:
    if not user or not password:
        return False
    password_hash = str(user.get("password_hash") or "")
    if not password_hash.startswith("$2"):
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
