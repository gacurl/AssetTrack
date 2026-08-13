from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assettrack.audit import ACTIVE_EVENTS_WHERE
from assettrack.db import DB_PATH
from assettrack.event_types import normalize_event_type


TERMINAL_LOCATION_TYPES = {"DISPOSED", "RETIRED"}
CUSTODY_EVENT_TYPES = {"ISSUE", "RETURN"}


@dataclass(frozen=True)
class LatestCustodyEvent:
    id: int
    event_type: str
    event_date: str


@dataclass(frozen=True)
class AccountabilityAsset:
    id: int
    asset_tag: str
    serial_number: str
    equipment_type: str
    location_type: str
    current_holder_id: int | None
    holder_name: str
    holder_organization: str
    current_location: str
    home_slot: str
    has_active_event: bool
    latest_custody_event: LatestCustodyEvent | None


@dataclass(frozen=True)
class ClassifiedAsset:
    asset: AccountabilityAsset
    classification: str
    reason: str


@dataclass(frozen=True)
class AccountabilityResult:
    rows: tuple[ClassifiedAsset, ...]

    @property
    def total_active_assets(self) -> int:
        return len(self.rows)

    @property
    def confirmed_checked_in(self) -> tuple[ClassifiedAsset, ...]:
        return tuple(row for row in self.rows if row.classification == "confirmed_checked_in")

    @property
    def not_checked_in(self) -> tuple[ClassifiedAsset, ...]:
        return tuple(row for row in self.rows if row.classification == "not_checked_in")

    @property
    def unresolved(self) -> tuple[ClassifiedAsset, ...]:
        return tuple(row for row in self.rows if row.classification == "unresolved")

    @property
    def passes(self) -> bool:
        return not self.not_checked_in and not self.unresolved


def _text(value: object) -> str:
    return str(value or "").strip()


def _storage_label(case_name: object, slot_position: object, building_room: object) -> str:
    case_text = _text(case_name)
    if case_text and slot_position is not None:
        return f"{case_text} / Slot {slot_position}"
    return _text(building_room)


def _latest_custody_events(conn: sqlite3.Connection) -> dict[int, LatestCustodyEvent]:
    active_events_where = ACTIVE_EVENTS_WHERE.replace("id NOT IN", "e.id NOT IN", 1)
    rows = conn.execute(
        f"""
        SELECT
            a.id AS asset_id,
            e.id AS event_id,
            e.event_type,
            e.event_date
        FROM assets a
        JOIN asset_events e
          ON UPPER(e.asset_tag) = UPPER(a.asset_tag)
        WHERE {active_events_where}
        ORDER BY a.id ASC, e.id DESC;
        """
    ).fetchall()

    latest: dict[int, LatestCustodyEvent] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        if asset_id in latest:
            continue
        event_type = normalize_event_type(row["event_type"])
        if event_type not in CUSTODY_EVENT_TYPES:
            continue
        latest[asset_id] = LatestCustodyEvent(
            id=int(row["event_id"]),
            event_type=event_type,
            event_date=_text(row["event_date"]),
        )
    return latest


def _asset_ids_with_active_events(conn: sqlite3.Connection) -> set[int]:
    active_events_where = ACTIVE_EVENTS_WHERE.replace("id NOT IN", "e.id NOT IN", 1)
    rows = conn.execute(
        f"""
        SELECT DISTINCT a.id AS asset_id
        FROM assets a
        JOIN asset_events e
          ON UPPER(e.asset_tag) = UPPER(a.asset_tag)
        WHERE {active_events_where};
        """
    ).fetchall()
    return {int(row["asset_id"]) for row in rows}


def _active_assets(conn: sqlite3.Connection) -> tuple[AccountabilityAsset, ...]:
    latest_events = _latest_custody_events(conn)
    asset_ids_with_active_events = _asset_ids_with_active_events(conn)
    rows = conn.execute(
        """
        SELECT
            a.id,
            a.asset_tag,
            COALESCE(a.serial_number, '') AS serial_number,
            COALESCE(a.equipment_type, '') AS equipment_type,
            COALESCE(a.location_type, '') AS location_type,
            a.current_holder_id,
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

    assets: list[AccountabilityAsset] = []
    for row in rows:
        asset_id = int(row["id"])
        current_location = _storage_label(row["home_case_name"], row["home_slot_position"], row["building_room"])
        assets.append(
            AccountabilityAsset(
                id=asset_id,
                asset_tag=_text(row["asset_tag"]),
                serial_number=_text(row["serial_number"]),
                equipment_type=_text(row["equipment_type"]),
                location_type=_text(row["location_type"]).upper(),
                current_holder_id=None if row["current_holder_id"] is None else int(row["current_holder_id"]),
                holder_name=_text(row["holder_name"]),
                holder_organization=_text(row["holder_organization"]),
                current_location=current_location,
                home_slot=current_location,
                has_active_event=asset_id in asset_ids_with_active_events,
                latest_custody_event=latest_events.get(asset_id),
            )
        )
    return tuple(assets)


def classify_asset(asset: AccountabilityAsset) -> ClassifiedAsset:
    event_type = "" if asset.latest_custody_event is None else asset.latest_custody_event.event_type

    if asset.location_type == "STORAGE":
        if asset.current_holder_id is not None:
            return ClassifiedAsset(asset, "unresolved", "STORAGE asset still has current_holder_id")
        if event_type == "RETURN":
            return ClassifiedAsset(asset, "confirmed_checked_in", "state is STORAGE and custody events agree")
        if event_type == "" and asset.has_active_event:
            return ClassifiedAsset(asset, "confirmed_checked_in", "never-issued asset has active event history and is STORAGE")
        if event_type == "":
            return ClassifiedAsset(asset, "unresolved", "state is STORAGE without active event proof")
        return ClassifiedAsset(asset, "unresolved", "state is STORAGE but latest custody event is ISSUE")

    if asset.location_type == "IN_CUSTODY":
        if event_type == "ISSUE":
            return ClassifiedAsset(asset, "not_checked_in", "latest custody event is ISSUE")
        if event_type == "RETURN":
            return ClassifiedAsset(asset, "unresolved", "state is IN_CUSTODY but latest custody event is RETURN")
        return ClassifiedAsset(asset, "unresolved", "state is IN_CUSTODY without custody event proof")

    return ClassifiedAsset(asset, "unresolved", f"unsupported active location_type {asset.location_type or 'blank'}")


def verify_accountability(conn: sqlite3.Connection) -> AccountabilityResult:
    return AccountabilityResult(tuple(classify_asset(asset) for asset in _active_assets(conn)))


def _event_label(event: LatestCustodyEvent | None) -> str:
    if event is None:
        return "none"
    return f"#{event.id} {event.event_type} {event.event_date}".strip()


def _holder_label(asset: AccountabilityAsset) -> str:
    if asset.current_holder_id is None:
        return ""
    holder = asset.holder_name
    if asset.holder_organization and asset.holder_organization != holder:
        holder = f"{holder} ({asset.holder_organization})" if holder else asset.holder_organization
    return holder or f"holder_id {asset.current_holder_id}"


def _exception_line(row: ClassifiedAsset) -> str:
    asset = row.asset
    parts = [
        f"{asset.asset_tag}",
        f"classification={row.classification}",
        f"reason={row.reason}",
        f"serial={asset.serial_number or 'blank'}",
        f"type={asset.equipment_type or 'blank'}",
        f"location_type={asset.location_type or 'blank'}",
    ]
    holder = _holder_label(asset)
    if holder:
        parts.append(f"holder={holder}")
    if asset.current_location:
        parts.append(f"storage={asset.current_location}")
    parts.append(f"latest_custody_event={_event_label(asset.latest_custody_event)}")
    return "  - " + "; ".join(parts)


def format_accountability_result(result: AccountabilityResult) -> str:
    lines = ["Asset Accountability Verification", ""]
    lines.extend(
        [
            f"Total active assets evaluated: {result.total_active_assets}",
            f"Confirmed checked in: {len(result.confirmed_checked_in)}",
            f"Not checked in: {len(result.not_checked_in)}",
            f"Unresolved/inconsistent: {len(result.unresolved)}",
            "",
        ]
    )
    if result.passes:
        lines.append(f"PASS: All {result.total_active_assets} active assets are checked in and accounted for.")
        return "\n".join(lines)

    failed_count = len(result.not_checked_in) + len(result.unresolved)
    lines.append(f"FAIL: {failed_count} of {result.total_active_assets} active assets are not confirmed checked in.")
    lines.extend(["", "Exceptions"])
    for row in tuple(result.not_checked_in) + tuple(result.unresolved):
        lines.append(_exception_line(row))
    return "\n".join(lines)


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only verification that active AssetTrack assets are checked in.")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to the AssetTrack SQLite database.")
    args = parser.parse_args(argv)

    try:
        conn = _open_readonly_database(Path(args.db))
    except sqlite3.Error as exc:
        print(f"Could not open database read-only: {exc}", file=sys.stderr)
        return 1

    try:
        result = verify_accountability(conn)
    except sqlite3.Error as exc:
        print(f"Accountability verification failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(format_accountability_result(result))
    return 0 if result.passes else 1


if __name__ == "__main__":
    raise SystemExit(main())
