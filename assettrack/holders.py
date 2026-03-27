# file: assettrack/holders.py
from __future__ import annotations

from datetime import datetime, timezone

from assettrack.db import get_connection
from assettrack.reference_data import get_organization


def search_holders(query: str, limit: int = 20) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []

    if limit <= 0:
        raise ValueError("limit must be > 0")

    pattern = f"%{q}%"

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM holders
            WHERE name LIKE ? OR identifier LIKE ? OR organization LIKE ?
            ORDER BY name ASC, id ASC
            LIMIT ?;
            """,
            (pattern, pattern, pattern, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_holders() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                h.id,
                h.holder_type,
                h.name,
                h.organization,
                h.identifier,
                h.contact_info,
                COUNT(a.id) AS asset_count
            FROM holders h
            LEFT JOIN assets a
              ON a.current_holder_id = h.id
            GROUP BY h.id, h.holder_type, h.name, h.organization, h.identifier, h.contact_info
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
    organization: str | None = None,
    organization_id: int | None = None,
    identifier: str | None = None,
    contact_info: str | None = None,
) -> dict:
    normalized_name = (name or "").strip()
    normalized_organization = (organization or "").strip() or None
    normalized_organization_id: int | None = None
    if organization_id not in {None, ""}:
        organization_row = get_organization(int(organization_id))
        if organization_row is None:
            raise ValueError("organization not found")
        normalized_organization_id = int(organization_row["id"])
        normalized_organization = str(organization_row["name"] or "").strip() or None
    if not normalized_name and not normalized_organization:
        raise ValueError("name or organization is required")
    normalized_holder_type = "ORGANIZATION" if not normalized_name and normalized_organization else holder_type
    persisted_name = normalized_name or str(normalized_organization or "").strip()

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO holders (holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                normalized_holder_type,
                persisted_name,
                normalized_organization,
                normalized_organization_id,
                identifier,
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
    organization: str | None = None,
    organization_id: int | None = None,
) -> dict:
    try:
        normalized_id = int(holder_id)
    except (TypeError, ValueError) as e:
        raise ValueError("holder_id is required") from e

    normalized_name = (name or "").strip()
    normalized_organization = (organization or "").strip() or None
    normalized_organization_id: int | None = None
    if organization_id not in {None, ""}:
        organization_row = get_organization(int(organization_id))
        if organization_row is None:
            raise ValueError("organization not found")
        normalized_organization_id = int(organization_row["id"])
        normalized_organization = str(organization_row["name"] or "").strip() or None
    if not normalized_name and not normalized_organization:
        raise ValueError("name or organization is required")
    persisted_name = normalized_name or str(normalized_organization or "").strip()
    persisted_holder_type = "ORGANIZATION" if not normalized_name and normalized_organization else "PERSON"
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE holders
            SET holder_type = ?, name = ?, organization = ?, organization_id = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                persisted_holder_type,
                persisted_name,
                normalized_organization,
                normalized_organization_id,
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
