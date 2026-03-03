# assettrack/dashboard.py
# file: assettrack/dashboard.py
from __future__ import annotations

from assettrack.audit import ACTIVE_EVENTS_WHERE
from assettrack.event_types import issue_event_type_values

from datetime import datetime, timezone
import sqlite3


def get_custody_days_threshold(raw_value: object, default: int = 30) -> int:
    if raw_value is None:
        return default

    try:
        threshold = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default

    return max(0, threshold)


def _parse_utc_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _inventory_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_assets,
            SUM(CASE WHEN COALESCE(a.location_type, '') <> 'DISPOSED' THEN 1 ELSE 0 END) AS active_assets,
            SUM(CASE WHEN a.location_type = 'DISPOSED' THEN 1 ELSE 0 END) AS disposed_assets,
            SUM(CASE WHEN a.location_type = 'STORAGE' THEN 1 ELSE 0 END) AS in_storage_assets,
            SUM(CASE WHEN a.location_type = 'IN_CUSTODY' THEN 1 ELSE 0 END) AS in_custody_assets,
            SUM(
                CASE
                    WHEN a.location_type = 'STORAGE'
                     AND (
                        a.home_slot_id IS NULL
                        OR NOT EXISTS (
                            SELECT 1
                            FROM slot_occupancy so
                            WHERE so.asset_id = a.id
                        )
                     )
                    THEN 1 ELSE 0
                END
            ) AS unslotted_assets
        FROM assets a;
        """
    ).fetchone()

    return {
        "total_assets": int(row["total_assets"] or 0),
        "active_assets": int(row["active_assets"] or 0),
        "disposed_assets": int(row["disposed_assets"] or 0),
        "in_storage_assets": int(row["in_storage_assets"] or 0),
        "in_custody_assets": int(row["in_custody_assets"] or 0),
        "unslotted_assets": int(row["unslotted_assets"] or 0),
    }


def _slot_summary(conn: sqlite3.Connection) -> dict:
    total_row = conn.execute("SELECT COUNT(*) AS total_slots FROM slots;").fetchone()
    occupied_row = conn.execute(
        """
        SELECT COUNT(DISTINCT slot_id) AS occupied_slots
        FROM slot_occupancy;
        """
    ).fetchone()

    total_slots = int(total_row["total_slots"] or 0)
    occupied_slots = int(occupied_row["occupied_slots"] or 0)
    empty_slots = max(0, total_slots - occupied_slots)
    utilization_percent = int((occupied_slots * 100.0 / total_slots) + 0.5) if total_slots > 0 else 0

    return {
        "total_slots": total_slots,
        "occupied_slots": occupied_slots,
        "empty_slots": empty_slots,
        "utilization_percent": utilization_percent,
    }


def _top_custody_holders(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            a.current_holder_id AS holder_id,
            COALESCE(NULLIF(TRIM(h.name), ''), 'ID ' || a.current_holder_id) AS holder_name,
            COUNT(*) AS asset_count
        FROM assets a
        LEFT JOIN holders h
          ON h.id = a.current_holder_id
        WHERE a.location_type = 'IN_CUSTODY'
          AND a.current_holder_id IS NOT NULL
        GROUP BY a.current_holder_id, COALESCE(NULLIF(TRIM(h.name), ''), 'ID ' || a.current_holder_id)
        ORDER BY asset_count DESC, holder_name ASC, a.current_holder_id ASC
        LIMIT ?;
        """,
        (limit,),
    ).fetchall()

    return [
        {
            "holder_id": int(row["holder_id"]),
            "holder_name": str(row["holder_name"]),
            "asset_count": int(row["asset_count"] or 0),
        }
        for row in rows
    ]


def _custody_summary(conn: sqlite3.Connection) -> dict:
    unique_holders_row = conn.execute(
        """
        SELECT COUNT(DISTINCT current_holder_id) AS unique_holders
        FROM assets
        WHERE location_type = 'IN_CUSTODY'
          AND current_holder_id IS NOT NULL;
        """
    ).fetchone()

    top_holders = _top_custody_holders(conn, limit=1)
    top_holder = top_holders[0] if top_holders else None

    return {
        "unique_holders": int(unique_holders_row["unique_holders"] or 0),
        "top_holder": top_holder,
    }


def _unslotted_assets(conn: sqlite3.Connection, limit: int | None = None) -> list[str]:
    sql = """
        SELECT a.asset_tag
        FROM assets a
        WHERE a.location_type = 'STORAGE'
          AND (
            a.home_slot_id IS NULL
            OR NOT EXISTS (
                SELECT 1
                FROM slot_occupancy so
                WHERE so.asset_id = a.id
            )
          )
        ORDER BY a.asset_tag ASC, a.id ASC
    """
    params: tuple[object, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    sql += ";"

    rows = conn.execute(sql, params).fetchall()
    return [str(row["asset_tag"]) for row in rows]


def _slot_conflict_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS conflict_slot_count
        FROM (
            SELECT so.slot_id
            FROM slot_occupancy so
            GROUP BY so.slot_id
            HAVING COUNT(*) > 1
        ) conflicts;
        """
    ).fetchone()
    return int(row["conflict_slot_count"] or 0)


def _slot_conflicts_preview(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            c.slot_id,
            s.case_name,
            s.slot_position
        FROM (
            SELECT so.slot_id
            FROM slot_occupancy so
            GROUP BY so.slot_id
            HAVING COUNT(*) > 1
        ) c
        LEFT JOIN slots s ON s.id = c.slot_id
        ORDER BY COALESCE(s.case_name, '') ASC, s.slot_position ASC, c.slot_id ASC
        LIMIT ?;
        """,
        (limit,),
    ).fetchall()

    return [
        {
            "slot_id": int(row["slot_id"]),
            "case_name": str(row["case_name"] or ""),
            "slot_position": row["slot_position"],
        }
        for row in rows
    ]


def _in_custody_days_out(conn: sqlite3.Connection, *, now_utc: datetime) -> list[dict]:
    asset_rows = conn.execute(
        """
        SELECT id, asset_tag
        FROM assets
        WHERE location_type = 'IN_CUSTODY'
        ORDER BY asset_tag ASC, id ASC;
        """
    ).fetchall()
    if not asset_rows:
        return []

    asset_tags = [str(row["asset_tag"]) for row in asset_rows]
    placeholders = ", ".join("?" for _ in asset_tags)
    issue_values = issue_event_type_values()
    issue_placeholders = ", ".join("?" for _ in issue_values)
    event_rows = conn.execute(
        f"""
        SELECT asset_tag, event_date, id
        FROM asset_events
        WHERE event_type IN ({issue_placeholders})
        AND {ACTIVE_EVENTS_WHERE}
        AND asset_tag IN ({placeholders})
        ORDER BY asset_tag ASC, id ASC;
        """,
        tuple(issue_values) + tuple(asset_tags),
    ).fetchall()

    latest_issue_by_tag: dict[str, datetime] = {}
    for row in event_rows:
        asset_tag = str(row["asset_tag"] or "")
        parsed = _parse_utc_timestamp(row["event_date"])
        if parsed is None:
            continue
        previous = latest_issue_by_tag.get(asset_tag)
        if previous is None or parsed > previous:
            latest_issue_by_tag[asset_tag] = parsed

    rows_with_days: list[dict] = []
    for row in asset_rows:
        asset_tag = str(row["asset_tag"] or "")
        issue_ts = latest_issue_by_tag.get(asset_tag)
        if issue_ts is None:
            continue

        days_out = int((now_utc - issue_ts).total_seconds() // 86400)
        rows_with_days.append(
            {
                "asset_tag": asset_tag,
                "days_out": max(0, days_out),
            }
        )

    rows_with_days.sort(key=lambda item: (-item["days_out"], item["asset_tag"]))
    return rows_with_days


def _exceptions_summary(
    *,
    unslotted_assets: list[str],
    slot_conflict_count: int,
    in_custody_days_out: list[dict],
    custody_days_threshold: int,
) -> dict:
    in_custody_over_threshold = sum(1 for row in in_custody_days_out if row["days_out"] > custody_days_threshold)
    return {
        "unslotted_assets": len(unslotted_assets),
        "slot_conflicts": slot_conflict_count,
        "in_custody_over_threshold": in_custody_over_threshold,
    }


def _case_utilization_preview(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            s.case_name,
            COUNT(*) AS total_slots,
            COUNT(DISTINCT so.slot_id) AS occupied_slots
        FROM slots s
        LEFT JOIN slot_occupancy so
          ON so.slot_id = s.id
        GROUP BY s.case_name
        ORDER BY occupied_slots DESC, s.case_name ASC
        LIMIT ?;
        """,
        (limit,),
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        total_slots = int(row["total_slots"] or 0)
        occupied_slots = int(row["occupied_slots"] or 0)
        utilization_percent = int((occupied_slots * 100.0 / total_slots) + 0.5) if total_slots > 0 else 0
        results.append(
            {
                "case_name": str(row["case_name"] or ""),
                "total_slots": total_slots,
                "occupied_slots": occupied_slots,
                "utilization_percent": utilization_percent,
            }
        )
    return results


def build_dashboard_data(
    conn: sqlite3.Connection,
    *,
    custody_days_threshold: int,
    now_utc: datetime | None = None,
) -> dict:
    current_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)

    inventory_summary = _inventory_summary(conn)
    slot_summary = _slot_summary(conn)
    custody_summary = _custody_summary(conn)

    unslotted_assets = _unslotted_assets(conn)
    in_custody_days_out = _in_custody_days_out(conn, now_utc=current_utc)
    slot_conflict_count = _slot_conflict_count(conn)

    exceptions_summary = _exceptions_summary(
        unslotted_assets=unslotted_assets,
        slot_conflict_count=slot_conflict_count,
        in_custody_days_out=in_custody_days_out,
        custody_days_threshold=custody_days_threshold,
    )

    return {
        "summary": {
            "inventory": inventory_summary,
            "slots": slot_summary,
            "custody": custody_summary,
            "exceptions": exceptions_summary,
        },
        "snapshots": {
            "top_custody_holders": _top_custody_holders(conn, limit=5),
            "case_utilization": _case_utilization_preview(conn, limit=5),
            "exceptions": {
                "unslotted_assets": _unslotted_assets(conn, limit=10),
                "in_custody_over_threshold": [
                    row for row in in_custody_days_out if row["days_out"] > custody_days_threshold
                ][:10],
                "slot_conflicts": _slot_conflicts_preview(conn, limit=10),
            },
        },
    }
