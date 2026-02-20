# file: assettrack/audit.py

import json
import sqlite3
from typing import Optional


# Canonical filter for "active" (non-superseded) events.
# Any event whose id appears as a supersedes_event_id is no longer active.
ACTIVE_EVENTS_WHERE = """
id NOT IN (
    SELECT supersedes_event_id
    FROM asset_events
    WHERE supersedes_event_id IS NOT NULL
)
"""


def record_event(
    conn: sqlite3.Connection,
    asset_tag: str,
    event_type: str,
    event_date: str,
    actor: Optional[str] = None,
    notes: Optional[str] = None,
    payload: Optional[dict] = None,
    supersedes_event_id: Optional[int] = None,
    correction_reason: Optional[str] = None,
):
    """
    Append an audit event for an asset.

    This function is append-only and does not enforce business rules.

    If supersedes_event_id is provided:
        - correction_reason must also be provided (DB-level CHECK enforces this).
        - The new event formally supersedes a prior event.
    """
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO asset_events (
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            payload,
            supersedes_event_id,
            correction_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            json.dumps(payload) if payload is not None else None,
            supersedes_event_id,
            correction_reason,
        ),
    )