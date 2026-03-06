# assettrack/users.py
from __future__ import annotations

from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from assettrack.db import get_connection

ALLOWED_ROLES = {"admin", "operator"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _password_hash(password: str) -> str:
    if not password:
        raise ValueError("password is required")
    password_hash = generate_password_hash(password)
    if not password_hash:
        raise ValueError("password hash generation failed")
    return password_hash


def _validate_new_password(username: str, current_password: str, new_password: str) -> None:
    if len(new_password) < 12:
        raise ValueError("New password must be at least 12 characters.")
    if not any(ch.isalpha() for ch in new_password):
        raise ValueError("New password must include at least one letter.")
    if not any(ch.isdigit() for ch in new_password):
        raise ValueError("New password must include at least one number.")
    if new_password.casefold() == str(username or "").casefold():
        raise ValueError("New password must not equal username.")
    if new_password == current_password:
        raise ValueError("New password must not equal current password.")


def count_users() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM users;").fetchone()
        return int(row["c"])
    finally:
        conn.close()


def _count_active_admins(conn) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE role = 'admin' AND active = 1;
        """
    ).fetchone()
    return int(row["c"])


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


def list_users() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, username, role, active, created_at, updated_at
            FROM users
            ORDER BY username COLLATE NOCASE ASC;
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def guard_last_admin(
    *,
    action: str,
    target_user_id: int,
    target_role: str | None = None,
    target_active: bool | None = None,
) -> None:
    user = get_user_by_id(target_user_id)
    if user is None:
        raise ValueError("User not found.")

    current_role = str(user.get("role") or "").strip().lower()
    current_active = int(user.get("active") or 0) == 1

    next_role = current_role
    if target_role is not None:
        next_role = str(target_role or "").strip().lower()
        if next_role not in ALLOWED_ROLES:
            raise ValueError("Role must be admin or operator.")

    next_active = current_active if target_active is None else bool(target_active)

    if not (current_role == "admin" and current_active):
        return

    if next_role == "admin" and next_active:
        return

    conn = get_connection()
    try:
        active_admins = _count_active_admins(conn)
    finally:
        conn.close()

    if active_admins <= 1:
        raise ValueError(f"Cannot {action}: at least one active admin is required.")


def create_user(username: str, password: str, role: str, active: bool = True) -> dict:
    normalized_username = (username or "").strip()
    normalized_role = (role or "").strip().lower()
    if not normalized_username:
        raise ValueError("username is required")
    if normalized_role not in ALLOWED_ROLES:
        raise ValueError("role must be admin or operator")

    now_iso = _now_iso()
    password_hash = _password_hash(password)
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


def set_user_active(user_id: int, active: bool) -> dict:
    normalized_user_id = int(user_id)
    guard_last_admin(action="deactivate the last active admin", target_user_id=normalized_user_id, target_active=active)

    now_iso = _now_iso()
    active_int = 1 if bool(active) else 0
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE users
            SET active = ?, updated_at = ?
            WHERE id = ?;
            """,
            (active_int, now_iso, normalized_user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("User not found.")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?;", (normalized_user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def set_user_role(user_id: int, role: str) -> dict:
    normalized_user_id = int(user_id)
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in ALLOWED_ROLES:
        raise ValueError("Role must be admin or operator.")

    guard_last_admin(
        action="demote the last active admin",
        target_user_id=normalized_user_id,
        target_role=normalized_role,
    )

    now_iso = _now_iso()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE users
            SET role = ?, updated_at = ?
            WHERE id = ?;
            """,
            (normalized_role, now_iso, normalized_user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("User not found.")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?;", (normalized_user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def reset_user_password(user_id: int, new_password: str) -> dict:
    normalized_user_id = int(user_id)
    password_hash = _password_hash(new_password)
    now_iso = _now_iso()

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = ?
            WHERE id = ?;
            """,
            (password_hash, now_iso, normalized_user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("User not found.")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?;", (normalized_user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def change_own_password(user_id: int, current_password: str, new_password: str) -> dict:
    user = get_user_by_id(user_id)
    if user is None:
        raise ValueError("User not found.")

    if not verify_password(user, current_password):
        raise ValueError("Current password is incorrect.")

    _validate_new_password(str(user.get("username") or ""), current_password, new_password)
    password_hash = _password_hash(new_password)
    now_iso = _now_iso()

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = ?
            WHERE id = ?;
            """,
            (password_hash, now_iso, int(user["id"])),
        )
        if cursor.rowcount != 1:
            raise ValueError("User not found.")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?;", (int(user["id"]),)).fetchone()
        return dict(row)
    finally:
        conn.close()


def verify_password(user: dict | None, password: str) -> bool:
    if not user or not password:
        return False
    password_hash = str(user.get("password_hash") or "")
    if not password_hash:
        return False
    try:
        return check_password_hash(password_hash, password)
    except ValueError:
        return False
