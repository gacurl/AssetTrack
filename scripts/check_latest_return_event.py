"""Inspect the latest RETURN audit event from the AssetTrack SQLite database.

This script is read-only. It connects to the production-style container path,
prints the latest RETURN event payload in a readable format, and reports
whether a responsibility acknowledgment is present.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


DB_PATH = Path("/app/data/assettrack.db")


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 1

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print(f"Could not open database read-only: {exc}")
        return 1

    conn.row_factory = sqlite3.Row

    try:
        table_row = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'asset_events'
            LIMIT 1;
            """
        ).fetchone()
        if table_row is None:
            print("Table not found: asset_events")
            return 1

        row = conn.execute(
            """
            SELECT id, asset_tag, event_type, event_date, actor, holder_id, payload
            FROM asset_events
            WHERE event_type = 'RETURN'
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        if row is None:
            print("No RETURN event found.")
            return 0

        raw_payload = row["payload"]
        try:
            payload = json.loads(raw_payload) if raw_payload else None
        except json.JSONDecodeError as exc:
            print(f"RETURN event {row['id']} has invalid JSON payload: {exc}")
            return 1

        print("Latest RETURN event")
        print(f"  id: {row['id']}")
        print(f"  asset_tag: {row['asset_tag']}")
        print(f"  event_date: {row['event_date']}")
        print(f"  actor: {row['actor']}")
        print(f"  holder_id: {row['holder_id']}")
        print("  payload:")
        print(json.dumps(payload, indent=2, sort_keys=True))

        has_ack = isinstance(payload, dict) and "responsibility_ack" in payload
        print(f"responsibility_ack present: {'YES' if has_ack else 'NO'}")
        return 0 if has_ack else 2
    except sqlite3.Error as exc:
        print(f"SQLite error: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
