# file: assettrack/holders.py
from __future__ import annotations

from assettrack.db import get_connection


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
            WHERE name LIKE ? OR identifier LIKE ?
            ORDER BY name ASC, id ASC
            LIMIT ?;
            """,
            (pattern, pattern, limit),
        )
        rows = cursor.fetchall()
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
