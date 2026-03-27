from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from assettrack.db import get_connection


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("name is required")
    return normalized


def list_organizations() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM organizations
            ORDER BY name COLLATE NOCASE ASC, id ASC;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_organization(organization_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM organizations
            WHERE id = ?;
            """,
            (int(organization_id),),
        ).fetchone()
        return None if row is None else dict(row)
    finally:
        conn.close()


def create_organization(name: str) -> dict:
    normalized_name = _normalize_name(name)
    now_iso = _utc_now_iso()

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM organizations
            WHERE UPPER(name) = UPPER(?)
            LIMIT 1;
            """,
            (normalized_name,),
        ).fetchone()
        if existing is not None:
            raise ValueError("organization already exists")

        cursor = conn.execute(
            """
            INSERT INTO organizations (name, created_at, updated_at)
            VALUES (?, ?, ?);
            """,
            (normalized_name, now_iso, now_iso),
        )
        conn.commit()
        created_id = int(cursor.lastrowid)
        return dict(
            conn.execute(
                """
                SELECT id, name, created_at, updated_at
                FROM organizations
                WHERE id = ?;
                """,
                (created_id,),
            ).fetchone()
        )
    finally:
        conn.close()


def list_buildings() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM buildings
            ORDER BY name COLLATE NOCASE ASC, id ASC;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_building(building_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM buildings
            WHERE id = ?;
            """,
            (int(building_id),),
        ).fetchone()
        return None if row is None else dict(row)
    finally:
        conn.close()


def create_building(name: str) -> dict:
    normalized_name = _normalize_name(name)
    now_iso = _utc_now_iso()

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM buildings
            WHERE UPPER(name) = UPPER(?)
            LIMIT 1;
            """,
            (normalized_name,),
        ).fetchone()
        if existing is not None:
            raise ValueError("building already exists")

        cursor = conn.execute(
            """
            INSERT INTO buildings (name, created_at, updated_at)
            VALUES (?, ?, ?);
            """,
            (normalized_name, now_iso, now_iso),
        )
        conn.commit()
        created_id = int(cursor.lastrowid)
        return dict(
            conn.execute(
                """
                SELECT id, name, created_at, updated_at
                FROM buildings
                WHERE id = ?;
                """,
                (created_id,),
            ).fetchone()
        )
    finally:
        conn.close()


def list_organization_building_mappings() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                ob.organization_id,
                o.name AS organization_name,
                ob.building_id,
                b.name AS building_name,
                ob.created_at
            FROM organization_buildings ob
            JOIN organizations o
              ON o.id = ob.organization_id
            JOIN buildings b
              ON b.id = ob.building_id
            ORDER BY o.name COLLATE NOCASE ASC, b.name COLLATE NOCASE ASC, ob.organization_id ASC, ob.building_id ASC;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_organization_building_mapping(organization_id: int, building_id: int) -> dict:
    now_iso = _utc_now_iso()

    conn = get_connection()
    try:
        organization = conn.execute(
            "SELECT id, name FROM organizations WHERE id = ?;",
            (int(organization_id),),
        ).fetchone()
        if organization is None:
            raise ValueError("organization not found")

        building = conn.execute(
            "SELECT id, name FROM buildings WHERE id = ?;",
            (int(building_id),),
        ).fetchone()
        if building is None:
            raise ValueError("building not found")

        existing = conn.execute(
            """
            SELECT 1
            FROM organization_buildings
            WHERE organization_id = ? AND building_id = ?
            LIMIT 1;
            """,
            (int(organization_id), int(building_id)),
        ).fetchone()
        if existing is not None:
            raise ValueError("mapping already exists")

        conn.execute(
            """
            INSERT INTO organization_buildings (organization_id, building_id, created_at)
            VALUES (?, ?, ?);
            """,
            (int(organization_id), int(building_id), now_iso),
        )
        conn.commit()
        return {
            "organization_id": int(organization["id"]),
            "organization_name": str(organization["name"]),
            "building_id": int(building["id"]),
            "building_name": str(building["name"]),
            "created_at": now_iso,
        }
    finally:
        conn.close()
