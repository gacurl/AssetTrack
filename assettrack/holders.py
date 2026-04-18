# file: assettrack/holders.py
from __future__ import annotations

import re
from datetime import datetime, timezone

from assettrack.db import DEFAULT_AD_HOC_ORGANIZATION, get_connection
from assettrack.reference_data import get_organization

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str | None) -> str | None:
    normalized = str(email or "").strip().lower()
    if not normalized:
        return None
    if len(normalized) > 254 or not EMAIL_PATTERN.match(normalized):
        raise ValueError("email is invalid")
    return normalized


def _ensure_unique_holder_email(
    conn,
    normalized_email: str | None,
    *,
    current_holder_id: int | None = None,
) -> None:
    if not normalized_email:
        return

    row = conn.execute(
        """
        SELECT id
        FROM holders
        WHERE LOWER(TRIM(COALESCE(email, ''))) = ?
        LIMIT 1;
        """,
        (normalized_email,),
    ).fetchone()
    if row is None:
        return

    existing_holder_id = int(row["id"])
    if current_holder_id is not None and existing_holder_id == int(current_holder_id):
        return

    raise ValueError("email already exists")


def search_holders(query: str, limit: int = 20, *, active_only: bool = False) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []

    if limit <= 0:
        raise ValueError("limit must be > 0")

    pattern = f"%{q}%"

    conn = get_connection()
    try:
        where_clauses = ["(name LIKE ? OR identifier LIKE ? OR organization LIKE ?)"]
        params: list[object] = [pattern, pattern, pattern]
        if active_only:
            where_clauses.append("COALESCE(is_active, 1) = 1")
        cursor = conn.execute(
            f"""
            SELECT * FROM holders
            WHERE {' AND '.join(where_clauses)}
            ORDER BY name ASC, id ASC
            LIMIT ?;
            """,
            (*params, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_holders(*, active_only: bool = False) -> list[dict]:
    conn = get_connection()
    try:
        where_sql = "WHERE COALESCE(h.is_active, 1) = 1" if active_only else ""
        rows = conn.execute(
            f"""
            SELECT
                h.id,
                h.holder_type,
                h.name,
                h.organization,
                h.is_active,
                h.identifier,
                h.email,
                h.contact_info,
                COUNT(a.id) AS asset_count
            FROM holders h
            LEFT JOIN assets a
              ON a.current_holder_id = h.id
            {where_sql}
            GROUP BY h.id, h.holder_type, h.name, h.organization, h.is_active, h.identifier, h.email, h.contact_info
            ORDER BY h.name COLLATE NOCASE ASC, h.id ASC;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_holder(holder_id: int) -> dict | None:
    if holder_id is None:
        return None

    try:
        normalized_id = int(holder_id)
    except (TypeError, ValueError):
        return None

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM holders
            WHERE id = ?;
            """,
            (normalized_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_holder(
    name: str,
    *,
    holder_type: str = "PERSON",
    organization_id: int,
    email: str | None = None,
    identifier: str | None = None,
    contact_info: str | None = None,
) -> dict:
    normalized_name = (name or "").strip()
    if organization_id in {None, ""}:
        raise ValueError("organization is required")
    organization_row = get_organization(int(organization_id))
    if organization_row is None:
        raise ValueError("organization not found")
    normalized_organization_id = int(organization_row["id"])
    normalized_organization = str(organization_row["name"] or "").strip() or None
    if not normalized_organization:
        raise ValueError("organization not found")
    if not normalized_name and normalized_organization == DEFAULT_AD_HOC_ORGANIZATION:
        raise ValueError("name is required")
    normalized_holder_type = "ORGANIZATION" if not normalized_name and normalized_organization else holder_type
    persisted_name = normalized_name or normalized_organization
    normalized_email = _normalize_email(email)

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        _ensure_unique_holder_email(conn, normalized_email)
        cursor = conn.execute(
            """
            INSERT INTO holders (
                holder_type, name, organization, organization_id, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                normalized_holder_type,
                persisted_name,
                normalized_organization,
                normalized_organization_id,
                identifier,
                normalized_email,
                contact_info,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
        created_id = int(cursor.lastrowid)
        row = conn.execute(
            """
            SELECT * FROM holders
            WHERE id = ?;
            """,
            (created_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_holder(
    holder_id: int,
    *,
    name: str,
    organization_id: int,
    email: str | None = None,
) -> dict:
    try:
        normalized_id = int(holder_id)
    except (TypeError, ValueError) as e:
        raise ValueError("holder_id is required") from e

    normalized_name = (name or "").strip()
    if organization_id in {None, ""}:
        raise ValueError("organization is required")
    organization_row = get_organization(int(organization_id))
    if organization_row is None:
        raise ValueError("organization not found")
    normalized_organization_id = int(organization_row["id"])
    normalized_organization = str(organization_row["name"] or "").strip() or None
    if not normalized_organization:
        raise ValueError("organization not found")
    if not normalized_name and normalized_organization == DEFAULT_AD_HOC_ORGANIZATION:
        raise ValueError("name is required")
    persisted_name = normalized_name or normalized_organization
    persisted_holder_type = "ORGANIZATION" if not normalized_name and normalized_organization else "PERSON"
    normalized_email = _normalize_email(email)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        _ensure_unique_holder_email(conn, normalized_email, current_holder_id=normalized_id)
        cursor = conn.execute(
            """
            UPDATE holders
            SET holder_type = ?, name = ?, organization = ?, organization_id = ?, email = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                persisted_holder_type,
                persisted_name,
                normalized_organization,
                normalized_organization_id,
                normalized_email,
                now_iso,
                normalized_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("holder not found")
        conn.commit()
        row = conn.execute(
            """
            SELECT * FROM holders
            WHERE id = ?;
            """,
            (normalized_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def set_holder_active(holder_id: int, is_active: bool) -> dict:
    try:
        normalized_id = int(holder_id)
    except (TypeError, ValueError) as e:
        raise ValueError("holder_id is required") from e

    now_iso = datetime.now(timezone.utc).isoformat()
    normalized_active = 1 if bool(is_active) else 0

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE holders
            SET is_active = ?, updated_at = ?
            WHERE id = ?;
            """,
            (normalized_active, now_iso, normalized_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("holder not found")
        conn.commit()
        row = conn.execute(
            """
            SELECT * FROM holders
            WHERE id = ?;
            """,
            (normalized_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()
