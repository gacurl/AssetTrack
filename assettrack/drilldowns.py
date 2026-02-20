from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from assettrack.assets import get_asset_table_columns


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


def list_holders_in_custody(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            h.id AS holder_id,
            h.name AS holder_name,
            COUNT(*) AS asset_count
        FROM assets a
        JOIN holders h
          ON h.id = a.current_holder_id
        WHERE a.location_type = 'IN_CUSTODY'
          AND a.current_holder_id IS NOT NULL
        GROUP BY h.id, h.name
        ORDER BY asset_count DESC, h.name ASC, h.id ASC;
        """
    ).fetchall()

    return [
        {
            "holder_id": int(row["holder_id"]),
            "holder_name": str(row["holder_name"]),
            "asset_count": int(row["asset_count"] or 0),
        }
        for row in rows
    ]


def get_holder_custody_detail(
    conn: sqlite3.Connection,
    holder_id: int,
    *,
    now_utc: datetime | None = None,
) -> dict | None:
    holder_row = conn.execute(
        """
        SELECT id, name
        FROM holders
        WHERE id = ?;
        """,
        (holder_id,),
    ).fetchone()
    if holder_row is None:
        return None

    asset_columns = get_asset_table_columns(conn)
    equipment_expr = "a.equipment_type" if "equipment_type" in asset_columns else "NULL"
    manufacturer_expr = "a.manufacturer" if "manufacturer" in asset_columns else "NULL"
    model_expr = "a.model" if "model" in asset_columns else "NULL"

    asset_rows = conn.execute(
        f"""
        SELECT
            a.asset_tag,
            {equipment_expr} AS equipment_type,
            {manufacturer_expr} AS manufacturer,
            {model_expr} AS model
        FROM assets a
        WHERE a.location_type = 'IN_CUSTODY'
          AND a.current_holder_id = ?
        ORDER BY a.asset_tag ASC, a.id ASC;
        """,
        (holder_id,),
    ).fetchall()

    assets = [
        {
            "asset_tag": str(row["asset_tag"]),
            "equipment_type": row["equipment_type"],
            "manufacturer": row["manufacturer"],
            "model": row["model"],
            "days_out": None,
            "last_issued_date": None,
        }
        for row in asset_rows
    ]

    if not assets:
        return {
            "holder_id": int(holder_row["id"]),
            "holder_name": str(holder_row["name"]),
            "assets": [],
        }

    current_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    asset_tags = [asset["asset_tag"] for asset in assets]
    placeholders = ", ".join("?" for _ in asset_tags)
    event_rows = conn.execute(
        f"""
        SELECT id, asset_tag, event_date
        FROM asset_events
        WHERE event_type = 'STOCK_OUT'
          AND asset_tag IN ({placeholders})
        ORDER BY asset_tag ASC, id ASC;
        """,
        tuple(asset_tags),
    ).fetchall()

    latest_stock_out: dict[str, dict] = {}
    for row in event_rows:
        asset_tag = str(row["asset_tag"] or "")
        parsed = _parse_utc_timestamp(row["event_date"])
        if parsed is None:
            continue

        event_id = int(row["id"])
        previous = latest_stock_out.get(asset_tag)
        if previous is None or parsed > previous["ts"] or (parsed == previous["ts"] and event_id > previous["id"]):
            latest_stock_out[asset_tag] = {
                "ts": parsed,
                "id": event_id,
                "event_date": str(row["event_date"]),
            }

    for asset in assets:
        stock_out = latest_stock_out.get(asset["asset_tag"])
        if stock_out is None:
            continue
        days_out = int((current_utc - stock_out["ts"]).total_seconds() // 86400)
        asset["days_out"] = max(0, days_out)
        asset["last_issued_date"] = stock_out["event_date"]

    return {
        "holder_id": int(holder_row["id"]),
        "holder_name": str(holder_row["name"]),
        "assets": assets,
    }


def list_case_summaries(conn: sqlite3.Connection) -> list[dict]:
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
        ORDER BY occupied_slots DESC, s.case_name ASC;
        """
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        total_slots = int(row["total_slots"] or 0)
        occupied_slots = int(row["occupied_slots"] or 0)
        empty_slots = max(0, total_slots - occupied_slots)
        utilization_percent = int((occupied_slots * 100.0 / total_slots) + 0.5) if total_slots > 0 else 0
        results.append(
            {
                "case_name": str(row["case_name"]),
                "total_slots": total_slots,
                "occupied_slots": occupied_slots,
                "empty_slots": empty_slots,
                "utilization_percent": utilization_percent,
            }
        )
    return results


def get_case_slot_detail(conn: sqlite3.Connection, case_name: str) -> dict | None:
    exists_row = conn.execute(
        """
        SELECT 1
        FROM slots
        WHERE case_name = ?
        LIMIT 1;
        """,
        (case_name,),
    ).fetchone()
    if exists_row is None:
        return None

    slot_rows = conn.execute(
        """
        SELECT
            s.id AS slot_id,
            s.slot_position,
            a.asset_tag
        FROM slots s
        LEFT JOIN (
            SELECT so.slot_id, so.asset_id
            FROM slot_occupancy so
            JOIN (
                SELECT slot_id, MIN(id) AS min_occupancy_id
                FROM slot_occupancy
                GROUP BY slot_id
            ) pick
              ON pick.min_occupancy_id = so.id
        ) chosen
          ON chosen.slot_id = s.id
        LEFT JOIN assets a
          ON a.id = chosen.asset_id
        WHERE s.case_name = ?
        ORDER BY s.slot_position ASC, s.id ASC;
        """,
        (case_name,),
    ).fetchall()

    return {
        "case_name": case_name,
        "slots": [
            {
                "slot_id": int(row["slot_id"]),
                "slot_position": int(row["slot_position"]),
                "asset_tag": row["asset_tag"],
            }
            for row in slot_rows
        ],
    }
