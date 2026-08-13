from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from assettrack.audit import ACTIVE_EVENTS_WHERE
from assettrack.event_types import normalize_event_type
from scripts.verify_accountability import verify_accountability


CUSTODY_EVENT_TYPES = {"ISSUE", "RETURN"}


@dataclass(frozen=True)
class HolderSummary:
    holder_id: int | None
    name: str
    organization: str

    @property
    def label(self) -> str:
        if self.name and self.organization and self.organization != self.name:
            return f"{self.name} ({self.organization})"
        if self.name:
            return self.name
        if self.organization:
            return self.organization
        if self.holder_id is not None:
            return f"holder_id {self.holder_id}"
        return ""


@dataclass(frozen=True)
class CustodyEvent:
    id: int
    asset_id: int
    asset_tag: str
    event_type: str
    event_at: datetime
    holder: HolderSummary
    home_slot_id: int | None
    from_building_room: str
    to_building_room: str


@dataclass(frozen=True)
class CustodyInterval:
    issue_event_id: int
    issue_timestamp: datetime
    holder: HolderSummary
    return_event_id: int | None
    return_timestamp: datetime | None
    elapsed: timedelta
    outstanding: bool


@dataclass(frozen=True)
class AssetCustodyReport:
    asset_id: int
    asset_tag: str
    serial_number: str
    equipment_type: str
    current_accountability_state: str
    current_holder: HolderSummary
    current_storage_location: str
    intervals: tuple[CustodyInterval, ...]
    issue_count: int
    total_custody_duration: timedelta
    longest_custody_interval: timedelta
    exceptions: tuple[str, ...]


@dataclass(frozen=True)
class HolderCustodyReport:
    holder: HolderSummary
    unique_asset_tags: tuple[str, ...]
    issue_transaction_count: int
    total_custody_time: timedelta
    longest_custody_interval: timedelta
    currently_outstanding_count: int
    outstanding_asset_tags: tuple[str, ...]


@dataclass(frozen=True)
class CustodyAccountabilityReport:
    generated_at: datetime
    assets: tuple[AssetCustodyReport, ...]
    holders: tuple[HolderCustodyReport, ...]
    active_assets: int
    checked_in: int
    checked_out: int
    unresolved: int


def _text(value: object) -> str:
    return str(value or "").strip()


def _parse_timestamp(value: object) -> datetime | None:
    raw = _text(value)
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


def _payload_dict(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _holder_from_row(row: sqlite3.Row, *, prefix: str = "") -> HolderSummary:
    holder_id = _optional_int(row[f"{prefix}holder_id"])
    return HolderSummary(
        holder_id=holder_id,
        name=_text(row[f"{prefix}holder_name"]),
        organization=_text(row[f"{prefix}holder_organization"]),
    )


def _storage_location(row: sqlite3.Row) -> str:
    case_name = _text(row["home_case_name"])
    slot_position = row["home_slot_position"]
    if case_name and slot_position is not None:
        return f"{case_name} / Slot {slot_position}"
    return _text(row["building_room"])


def _active_asset_rows(conn: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
    return tuple(
        conn.execute(
            """
            SELECT
                a.id,
                a.asset_tag,
                COALESCE(a.serial_number, '') AS serial_number,
                COALESCE(a.equipment_type, '') AS equipment_type,
                COALESCE(a.location_type, '') AS location_type,
                a.current_holder_id AS holder_id,
                COALESCE(h.name, '') AS holder_name,
                COALESCE(h.organization, '') AS holder_organization,
                COALESCE(a.building_room, '') AS building_room,
                s.case_name AS home_case_name,
                s.slot_position AS home_slot_position
            FROM assets a
            LEFT JOIN holders h
              ON h.id = a.current_holder_id
            LEFT JOIN slots s
              ON s.id = a.home_slot_id
            WHERE COALESCE(a.location_type, '') NOT IN ('DISPOSED', 'RETIRED')
            ORDER BY a.asset_tag COLLATE NOCASE ASC, a.id ASC;
            """
        ).fetchall()
    )


def _event_rows(conn: sqlite3.Connection) -> tuple[CustodyEvent, ...]:
    active_events_where = ACTIVE_EVENTS_WHERE.replace("id NOT IN", "e.id NOT IN", 1)
    rows = conn.execute(
        f"""
        SELECT
            a.id AS asset_id,
            a.asset_tag AS canonical_asset_tag,
            e.id AS event_id,
            e.asset_tag,
            e.event_type,
            e.event_date,
            e.holder_id,
            COALESCE(h.name, '') AS holder_name,
            COALESCE(h.organization, '') AS holder_organization,
            e.payload
        FROM assets a
        JOIN asset_events e
          ON UPPER(e.asset_tag) = UPPER(a.asset_tag)
        LEFT JOIN holders h
          ON h.id = e.holder_id
        WHERE COALESCE(a.location_type, '') NOT IN ('DISPOSED', 'RETIRED')
          AND {active_events_where}
        ORDER BY a.asset_tag COLLATE NOCASE ASC, e.event_date ASC, e.id ASC;
        """
    ).fetchall()

    events: list[CustodyEvent] = []
    for row in rows:
        event_type = normalize_event_type(row["event_type"])
        if event_type not in CUSTODY_EVENT_TYPES:
            continue
        event_at = _parse_timestamp(row["event_date"])
        if event_at is None:
            continue
        payload = _payload_dict(row["payload"])
        events.append(
            CustodyEvent(
                id=int(row["event_id"]),
                asset_id=int(row["asset_id"]),
                asset_tag=_text(row["canonical_asset_tag"]) or _text(row["asset_tag"]),
                event_type=event_type,
                event_at=event_at,
                holder=_holder_from_row(row),
                home_slot_id=_optional_int(payload.get("home_slot_id")),
                from_building_room=_text(payload.get("from_building_room")),
                to_building_room=_text(payload.get("to_building_room")),
            )
        )
    return tuple(events)


def _classifications_by_asset(conn: sqlite3.Connection) -> dict[int, str]:
    result = verify_accountability(conn)
    return {row.asset.id: row.classification for row in result.rows}


def _pair_asset_events(
    events: tuple[CustodyEvent, ...],
    *,
    generated_at: datetime,
) -> tuple[tuple[CustodyInterval, ...], tuple[str, ...]]:
    intervals: list[CustodyInterval] = []
    exceptions: list[str] = []
    open_issue: CustodyEvent | None = None

    for event in events:
        if event.event_type == "ISSUE":
            if open_issue is not None:
                exceptions.append(f"ISSUE event {event.id} occurred before RETURN for ISSUE event {open_issue.id}.")
            open_issue = event
            continue

        if event.event_type == "RETURN":
            if open_issue is None:
                exceptions.append(f"RETURN event {event.id} has no preceding open ISSUE event.")
                continue
            if event.event_at < open_issue.event_at:
                exceptions.append(f"RETURN event {event.id} is earlier than ISSUE event {open_issue.id}.")
                open_issue = None
                continue
            intervals.append(
                CustodyInterval(
                    issue_event_id=open_issue.id,
                    issue_timestamp=open_issue.event_at,
                    holder=open_issue.holder,
                    return_event_id=event.id,
                    return_timestamp=event.event_at,
                    elapsed=event.event_at - open_issue.event_at,
                    outstanding=False,
                )
            )
            open_issue = None

    if open_issue is not None:
        if generated_at < open_issue.event_at:
            exceptions.append(f"Open ISSUE event {open_issue.id} is later than report timestamp.")
        else:
            intervals.append(
                CustodyInterval(
                    issue_event_id=open_issue.id,
                    issue_timestamp=open_issue.event_at,
                    holder=open_issue.holder,
                    return_event_id=None,
                    return_timestamp=None,
                    elapsed=generated_at - open_issue.event_at,
                    outstanding=True,
                )
            )

    return tuple(intervals), tuple(exceptions)


def _holder_key(holder: HolderSummary) -> tuple[int, str, str]:
    return (-1 if holder.holder_id is None else holder.holder_id, holder.name, holder.organization)


def _holder_reports(asset_reports: tuple[AssetCustodyReport, ...]) -> tuple[HolderCustodyReport, ...]:
    grouped: dict[tuple[int, str, str], list[tuple[str, CustodyInterval]]] = {}
    holder_lookup: dict[tuple[int, str, str], HolderSummary] = {}
    for asset in asset_reports:
        for interval in asset.intervals:
            key = _holder_key(interval.holder)
            grouped.setdefault(key, []).append((asset.asset_tag, interval))
            holder_lookup[key] = interval.holder

    reports: list[HolderCustodyReport] = []
    for key in sorted(grouped, key=lambda item: (item[1].upper(), item[2].upper(), item[0])):
        rows = grouped[key]
        durations = [interval.elapsed for _asset_tag, interval in rows]
        outstanding_asset_tags = sorted(
            {asset_tag for asset_tag, interval in rows if interval.outstanding},
            key=str.upper,
        )
        reports.append(
            HolderCustodyReport(
                holder=holder_lookup[key],
                unique_asset_tags=tuple(sorted({asset_tag for asset_tag, _interval in rows}, key=str.upper)),
                issue_transaction_count=len(rows),
                total_custody_time=sum(durations, timedelta()),
                longest_custody_interval=max(durations, default=timedelta()),
                currently_outstanding_count=len(outstanding_asset_tags),
                outstanding_asset_tags=tuple(outstanding_asset_tags),
            )
        )
    return tuple(reports)


def build_custody_accountability_report(
    conn: sqlite3.Connection,
    *,
    generated_at: datetime,
) -> CustodyAccountabilityReport:
    generated = generated_at.astimezone(timezone.utc) if generated_at.tzinfo else generated_at.replace(tzinfo=timezone.utc)
    event_groups: dict[int, list[CustodyEvent]] = {}
    for event in _event_rows(conn):
        event_groups.setdefault(event.asset_id, []).append(event)

    classifications = _classifications_by_asset(conn)
    asset_reports: list[AssetCustodyReport] = []
    for row in _active_asset_rows(conn):
        asset_id = int(row["id"])
        intervals, exceptions = _pair_asset_events(tuple(event_groups.get(asset_id, [])), generated_at=generated)
        durations = [interval.elapsed for interval in intervals]
        classification = classifications.get(asset_id, "unresolved")
        if classification == "unresolved" and "current accountability state is unresolved" not in exceptions:
            exceptions = tuple(exceptions) + ("current accountability state is unresolved",)
        asset_reports.append(
            AssetCustodyReport(
                asset_id=asset_id,
                asset_tag=_text(row["asset_tag"]),
                serial_number=_text(row["serial_number"]),
                equipment_type=_text(row["equipment_type"]),
                current_accountability_state=classification,
                current_holder=_holder_from_row(row),
                current_storage_location=_storage_location(row),
                intervals=intervals,
                issue_count=sum(1 for event in event_groups.get(asset_id, []) if event.event_type == "ISSUE"),
                total_custody_duration=sum(durations, timedelta()),
                longest_custody_interval=max(durations, default=timedelta()),
                exceptions=exceptions,
            )
        )

    checked_in = sum(1 for asset in asset_reports if asset.current_accountability_state == "confirmed_checked_in")
    checked_out = sum(1 for asset in asset_reports if asset.current_accountability_state == "not_checked_in")
    unresolved = sum(1 for asset in asset_reports if asset.current_accountability_state == "unresolved" or asset.exceptions)
    return CustodyAccountabilityReport(
        generated_at=generated,
        assets=tuple(asset_reports),
        holders=_holder_reports(tuple(asset_reports)),
        active_assets=len(asset_reports),
        checked_in=checked_in,
        checked_out=checked_out,
        unresolved=unresolved,
    )
