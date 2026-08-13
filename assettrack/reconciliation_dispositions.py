from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationDisposition:
    id: int
    created_at: str
    actor_user_id: int
    actor_username: str
    discrepancy_key: str
    discrepancy_category: str
    normalized_asset_key: str
    discrepancy_snapshot_json: str
    disposition_note: str
    is_reviewed: bool


def insert_reconciliation_disposition_event(
    conn: sqlite3.Connection,
    *,
    created_at: str,
    actor_user_id: int,
    actor_username: str,
    discrepancy_key: str,
    discrepancy_category: str,
    normalized_asset_key: str,
    discrepancy_snapshot_json: str,
    disposition_note: str,
    is_reviewed: bool,
) -> int:
    json.loads(discrepancy_snapshot_json)
    row = conn.execute(
        """
        INSERT INTO inventory_reconciliation_disposition_events (
            created_at,
            actor_user_id,
            actor_username,
            discrepancy_key,
            discrepancy_category,
            normalized_asset_key,
            discrepancy_snapshot_json,
            disposition_note,
            is_reviewed
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            created_at,
            int(actor_user_id),
            str(actor_username or "").strip(),
            str(discrepancy_key or "").strip(),
            str(discrepancy_category or "").strip(),
            str(normalized_asset_key or "").strip() or None,
            discrepancy_snapshot_json,
            str(disposition_note or "").strip(),
            1 if is_reviewed else 0,
        ),
    )
    return int(row.lastrowid)


def latest_reconciliation_dispositions(
    conn: sqlite3.Connection,
    discrepancy_keys: list[str] | tuple[str, ...],
) -> dict[str, ReconciliationDisposition]:
    keys = [str(key or "").strip() for key in discrepancy_keys if str(key or "").strip()]
    if not keys:
        return {}
    placeholders = ",".join("?" for _key in keys)
    rows = conn.execute(
        f"""
        SELECT
            id,
            created_at,
            actor_user_id,
            actor_username,
            discrepancy_key,
            discrepancy_category,
            normalized_asset_key,
            discrepancy_snapshot_json,
            disposition_note,
            is_reviewed
        FROM inventory_reconciliation_disposition_events
        WHERE discrepancy_key IN ({placeholders})
        ORDER BY id DESC;
        """,
        keys,
    ).fetchall()
    latest: dict[str, ReconciliationDisposition] = {}
    for row in rows:
        key = str(row["discrepancy_key"] or "")
        if key in latest:
            continue
        latest[key] = ReconciliationDisposition(
            id=int(row["id"]),
            created_at=str(row["created_at"] or ""),
            actor_user_id=int(row["actor_user_id"]),
            actor_username=str(row["actor_username"] or ""),
            discrepancy_key=key,
            discrepancy_category=str(row["discrepancy_category"] or ""),
            normalized_asset_key=str(row["normalized_asset_key"] or ""),
            discrepancy_snapshot_json=str(row["discrepancy_snapshot_json"] or ""),
            disposition_note=str(row["disposition_note"] or ""),
            is_reviewed=int(row["is_reviewed"] or 0) == 1,
        )
    return latest
