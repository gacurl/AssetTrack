# assettrack/slots.py
from __future__ import annotations

import sqlite3
from typing import Optional

from assettrack.db import get_connection


def get_slot_by_position(case_name: str, slot_position: int) -> dict | None:
    normalized_case = (case_name or "").strip()
    if not normalized_case:
        return None

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM slots
            WHERE case_name = ? AND slot_position = ?;
            """,
            (normalized_case, slot_position),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_slot_by_asset_tag(asset_tag: str) -> dict | None:
    normalized_tag = (asset_tag or "").strip()
    if not normalized_tag:
        return None

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM slots
            WHERE current_asset_tag = ?;
            """,
            (normalized_tag,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def assign_asset_to_slot(case_name: str, slot_position: int, asset_tag: str) -> None:
    normalized_case = (case_name or "").strip()
    normalized_tag = (asset_tag or "").strip()
    if not normalized_case:
        raise ValueError("case_name is required")
    if not normalized_tag:
        raise ValueError("asset_tag is required")

    conn = get_connection()
    try:
        with conn:
            existing_slot = conn.execute(
                """
                SELECT * FROM slots
                WHERE case_name = ? AND slot_position = ?;
                """,
                (normalized_case, slot_position),
            ).fetchone()

            existing_assignment = conn.execute(
                """
                SELECT * FROM slots
                WHERE current_asset_tag = ?;
                """,
                (normalized_tag,),
            ).fetchone()

            if existing_assignment:
                same_slot = (
                    existing_assignment["case_name"] == normalized_case
                    and existing_assignment["slot_position"] == slot_position
                )
                if not same_slot:
                    raise ValueError(
                        f"Asset {normalized_tag} already assigned to "
                        f"{existing_assignment['case_name']} slot {existing_assignment['slot_position']}"
                    )

            if existing_slot:
                current_tag = existing_slot["current_asset_tag"]
                if current_tag and current_tag != normalized_tag:
                    raise ValueError(
                        f"Slot {normalized_case} {slot_position} already occupied by {current_tag}"
                    )

                if current_tag == normalized_tag:
                    return

                conn.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = ?
                    WHERE case_name = ? AND slot_position = ?;
                    """,
                    (normalized_tag, normalized_case, slot_position),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO slots (case_name, slot_position, current_asset_tag)
                    VALUES (?, ?, ?);
                    """,
                    (normalized_case, slot_position, normalized_tag),
                )
    finally:
        conn.close()


def vacate_slot(case_name: str, slot_position: int, reason: Optional[str] = None) -> None:
    normalized_case = (case_name or "").strip()
    if not normalized_case:
        raise ValueError("case_name is required")

    if reason is not None:
        _ = reason  # reserved for future audit trail

    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE slots
                SET current_asset_tag = NULL
                WHERE case_name = ? AND slot_position = ?;
                """,
                (normalized_case, slot_position),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"No slot found for {normalized_case} {slot_position}")
    finally:
        conn.close()


def list_slots_for_case(case_name: str) -> list[dict]:
    normalized_case = (case_name or "").strip()
    if not normalized_case:
        return []

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM slots
            WHERE case_name = ?
            ORDER BY slot_position ASC;
            """,
            (normalized_case,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
