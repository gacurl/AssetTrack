import json
import sqlite3
from typing import Optional


def record_event(
    conn: sqlite3.Connection,
    asset_tag: str,
    event_type: str,
    event_date: str,
    actor: Optional[str] = None,
    notes: Optional[str] = None,
    payload: Optional[dict] = None,
):
    """
    Append an audit event for an asset.
    This function is append-only and does not enforce business rules.
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
            payload
        )
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            json.dumps(payload) if payload is not None else None,
        ),
    )

    conn.commit()
