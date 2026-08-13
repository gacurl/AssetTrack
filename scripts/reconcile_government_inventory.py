from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assettrack.barcodes import barcode_lookup_key
from assettrack.db import DB_PATH
from assettrack.import_analysis import _normalize_header, _normalize_text


TERMINAL_LOCATION_TYPES = {"DISPOSED", "RETIRED"}


@dataclass(frozen=True)
class GovernmentRecord:
    row_number: int
    asset_tag: str
    compare_tag: str
    serial_number: str
    mac_address: str
    equipment_type: str

    @property
    def key(self) -> str:
        return barcode_lookup_key(self.compare_tag)


@dataclass(frozen=True)
class AssetTrackRecord:
    id: int
    asset_tag: str
    serial_number: str
    location_type: str

    @property
    def key(self) -> str:
        return barcode_lookup_key(self.asset_tag)

    @property
    def is_terminal(self) -> bool:
        return self.location_type.upper() in TERMINAL_LOCATION_TYPES


@dataclass(frozen=True)
class ReconciliationResult:
    government_records: tuple[GovernmentRecord, ...]
    assettrack_active_records: tuple[AssetTrackRecord, ...]
    assettrack_terminal_records: tuple[AssetTrackRecord, ...]
    tag_matches: tuple[tuple[GovernmentRecord, AssetTrackRecord], ...]
    government_only: tuple[GovernmentRecord, ...]
    assettrack_only_active: tuple[AssetTrackRecord, ...]
    identity_conflicts: tuple[tuple[GovernmentRecord, AssetTrackRecord], ...]
    ambiguous_government_tags: tuple[tuple[str, tuple[GovernmentRecord, ...]], ...]
    ambiguous_assettrack_tags: tuple[tuple[str, tuple[AssetTrackRecord, ...]], ...]
    duplicate_serial_warnings: tuple[tuple[str, tuple[GovernmentRecord, ...]], ...]
    duplicate_mac_warnings: tuple[tuple[str, tuple[GovernmentRecord, ...]], ...]
    terminal_matches: tuple[tuple[GovernmentRecord, AssetTrackRecord], ...]
    terminal_assettrack_only: tuple[AssetTrackRecord, ...]

    def summary_counts(self) -> dict[str, int]:
        return {
            "government_records": len(self.government_records),
            "assettrack_active_records_considered": len(self.assettrack_active_records),
            "exact_or_normalized_tag_matches": len(self.tag_matches),
            "government_only_assets": len(self.government_only),
            "assettrack_only_active_assets": len(self.assettrack_only_active),
            "identity_conflicts": len(self.identity_conflicts),
            "ambiguous_normalized_tags": len(self.ambiguous_government_tags) + len(self.ambiguous_assettrack_tags),
            "duplicate_serial_warnings": len(self.duplicate_serial_warnings),
            "duplicate_mac_warnings": len(self.duplicate_mac_warnings),
            "retired_disposed_assettrack_records": len(self.assettrack_terminal_records),
            "retired_disposed_tag_matches": len(self.terminal_matches),
            "retired_disposed_assettrack_only": len(self.terminal_assettrack_only),
        }


@dataclass(frozen=True)
class ReconciliationDiscrepancy:
    key: str
    category: str
    label: str
    normalized_asset_key: str
    snapshot: dict[str, object]
    snapshot_json: str


def _canonical_json(data: dict[str, object]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def discrepancy_key_from_snapshot(snapshot: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _canonical_text(value: object) -> str:
    return _normalize_text(value).upper()


def _government_snapshot(record: GovernmentRecord) -> dict[str, object]:
    return {
        "asset_tag": _normalize_text(record.asset_tag),
        "compare_tag": _normalize_text(record.compare_tag),
        "normalized_asset_key": record.key,
        "serial_number": _canonical_text(record.serial_number),
        "mac_address": _canonical_text(record.mac_address),
        "equipment_type": _canonical_text(record.equipment_type),
        "row_number": int(record.row_number),
    }


def _assettrack_snapshot(record: AssetTrackRecord) -> dict[str, object]:
    return {
        "id": int(record.id),
        "asset_tag": _normalize_text(record.asset_tag),
        "normalized_asset_key": record.key,
        "serial_number": _canonical_text(record.serial_number),
        "location_type": _canonical_text(record.location_type),
    }


def _member_tags(records: tuple[GovernmentRecord, ...] | tuple[AssetTrackRecord, ...]) -> list[str]:
    return sorted(_normalize_text(getattr(record, "asset_tag")) for record in records)


def _make_discrepancy(
    *,
    category: str,
    label: str,
    normalized_asset_key: str,
    government: list[dict[str, object]] | None = None,
    assettrack: list[dict[str, object]] | None = None,
    duplicate_value: str = "",
    member_tags: list[str] | None = None,
) -> ReconciliationDiscrepancy:
    snapshot: dict[str, object] = {
        "category": category,
        "normalized_asset_key": normalized_asset_key,
        "government": government or [],
        "assettrack": assettrack or [],
        "duplicate_value": duplicate_value,
        "member_tags": sorted(member_tags or []),
    }
    snapshot_json = _canonical_json(snapshot)
    return ReconciliationDiscrepancy(
        key=discrepancy_key_from_snapshot(snapshot),
        category=category,
        label=label,
        normalized_asset_key=normalized_asset_key,
        snapshot=snapshot,
        snapshot_json=snapshot_json,
    )


def active_discrepancies(result: ReconciliationResult) -> tuple[ReconciliationDiscrepancy, ...]:
    discrepancies: list[ReconciliationDiscrepancy] = []

    for record in result.government_only:
        discrepancies.append(
            _make_discrepancy(
                category="government_only_asset",
                label=f"Government-only asset {record.asset_tag}",
                normalized_asset_key=record.key,
                government=[_government_snapshot(record)],
                member_tags=[record.asset_tag],
            )
        )
    for record in result.assettrack_only_active:
        discrepancies.append(
            _make_discrepancy(
                category="assettrack_only_active_asset",
                label=f"AssetTrack-only active asset {record.asset_tag}",
                normalized_asset_key=record.key,
                assettrack=[_assettrack_snapshot(record)],
                member_tags=[record.asset_tag],
            )
        )
    for government, asset in result.identity_conflicts:
        discrepancies.append(
            _make_discrepancy(
                category="identity_conflict",
                label=f"Identity conflict {government.asset_tag}",
                normalized_asset_key=government.key or asset.key,
                government=[_government_snapshot(government)],
                assettrack=[_assettrack_snapshot(asset)],
                member_tags=[government.asset_tag, asset.asset_tag],
            )
        )
    for key, records in result.ambiguous_government_tags:
        discrepancies.append(
            _make_discrepancy(
                category="ambiguous_government_normalized_tag",
                label=f"Ambiguous government normalized tag {key}",
                normalized_asset_key=key,
                government=[_government_snapshot(record) for record in records],
                member_tags=_member_tags(records),
            )
        )
    for key, records in result.ambiguous_assettrack_tags:
        discrepancies.append(
            _make_discrepancy(
                category="ambiguous_assettrack_normalized_tag",
                label=f"Ambiguous AssetTrack normalized tag {key}",
                normalized_asset_key=key,
                assettrack=[_assettrack_snapshot(record) for record in records],
                member_tags=_member_tags(records),
            )
        )
    for key, records in result.duplicate_serial_warnings:
        discrepancies.append(
            _make_discrepancy(
                category="duplicate_government_serial",
                label=f"Duplicate government serial {key}",
                normalized_asset_key="",
                government=[_government_snapshot(record) for record in records],
                duplicate_value=key,
                member_tags=_member_tags(records),
            )
        )
    for key, records in result.duplicate_mac_warnings:
        discrepancies.append(
            _make_discrepancy(
                category="duplicate_government_mac",
                label=f"Duplicate government MAC {key}",
                normalized_asset_key="",
                government=[_government_snapshot(record) for record in records],
                duplicate_value=key,
                member_tags=_member_tags(records),
            )
        )
    for government, asset in result.terminal_matches:
        discrepancies.append(
            _make_discrepancy(
                category="retired_disposed_tag_match",
                label=f"Retired/disposed tag match {government.asset_tag}",
                normalized_asset_key=government.key or asset.key,
                government=[_government_snapshot(government)],
                assettrack=[_assettrack_snapshot(asset)],
                member_tags=[government.asset_tag, asset.asset_tag],
            )
        )
    for record in result.terminal_assettrack_only:
        discrepancies.append(
            _make_discrepancy(
                category="retired_disposed_assettrack_only",
                label=f"Retired/disposed AssetTrack-only asset {record.asset_tag}",
                normalized_asset_key=record.key,
                assettrack=[_assettrack_snapshot(record)],
                member_tags=[record.asset_tag],
            )
        )

    return tuple(sorted(discrepancies, key=lambda item: (item.category, item.label, item.key)))


def _read_inventory_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=object, keep_default_na=False)
    if suffix == ".xlsx":
        sheets = pd.read_excel(path, engine="openpyxl", sheet_name=None, dtype=object)
        if len(sheets) != 1:
            names = ", ".join(sorted(sheets))
            raise ValueError(f"Expected one government inventory sheet; found: {names}")
        return next(iter(sheets.values()))
    raise ValueError("Unsupported inventory file type. Use .csv or .xlsx.")


def load_government_records(path: str | Path) -> tuple[GovernmentRecord, ...]:
    inventory_path = Path(path)
    if not inventory_path.exists():
        raise ValueError(f"Government inventory file not found: {inventory_path}")

    frame = _read_inventory_frame(inventory_path)
    column_map: dict[str, object] = {}
    for column in frame.columns:
        normalized = _normalize_header(column)
        if normalized and not normalized.startswith("unnamed"):
            column_map.setdefault(normalized, column)

    tag_column = column_map.get("asset_tag") or column_map.get("barcode")
    compare_column = column_map.get("clean_asset_tag") or tag_column
    serial_column = column_map.get("serial_number")
    mac_column = column_map.get("mac_address")
    type_column = column_map.get("equipment_type")
    if tag_column is None and compare_column is None:
        raise ValueError("Government inventory must include asset_tag, clean_asset_tag, or barcode.")

    records: list[GovernmentRecord] = []
    for index, row in frame.iterrows():
        asset_tag = _normalize_text(row.get(tag_column, "")) if tag_column is not None else ""
        compare_tag = _normalize_text(row.get(compare_column, "")) if compare_column is not None else asset_tag
        serial_number = _normalize_text(row.get(serial_column, "")) if serial_column is not None else ""
        mac_address = _normalize_text(row.get(mac_column, "")) if mac_column is not None else ""
        equipment_type = _normalize_text(row.get(type_column, "")) if type_column is not None else ""
        if not any((asset_tag, compare_tag, serial_number, mac_address, equipment_type)):
            continue
        records.append(
            GovernmentRecord(
                row_number=int(index) + 2,
                asset_tag=asset_tag or compare_tag,
                compare_tag=compare_tag or asset_tag,
                serial_number=serial_number,
                mac_address=mac_address,
                equipment_type=equipment_type,
            )
        )
    return tuple(records)


def load_assettrack_records(conn: sqlite3.Connection) -> tuple[AssetTrackRecord, ...]:
    rows = conn.execute(
        """
        SELECT id, asset_tag, serial_number, location_type
        FROM assets
        ORDER BY UPPER(asset_tag) ASC, id ASC;
        """
    ).fetchall()
    return tuple(
        AssetTrackRecord(
            id=int(row["id"]),
            asset_tag=_normalize_text(row["asset_tag"]),
            serial_number=_normalize_text(row["serial_number"]),
            location_type=_normalize_text(row["location_type"]),
        )
        for row in rows
    )


def _group_government_by_key(records: tuple[GovernmentRecord, ...]) -> dict[str, list[GovernmentRecord]]:
    groups: dict[str, list[GovernmentRecord]] = defaultdict(list)
    for record in records:
        if record.key:
            groups[record.key].append(record)
    return groups


def _group_assettrack_by_key(records: tuple[AssetTrackRecord, ...]) -> dict[str, list[AssetTrackRecord]]:
    groups: dict[str, list[AssetTrackRecord]] = defaultdict(list)
    for record in records:
        if record.key:
            groups[record.key].append(record)
    return groups


def _duplicate_government_field(
    records: tuple[GovernmentRecord, ...],
    field_name: str,
) -> tuple[tuple[str, tuple[GovernmentRecord, ...]], ...]:
    groups: dict[str, list[GovernmentRecord]] = defaultdict(list)
    for record in records:
        value = _normalize_text(getattr(record, field_name)).upper()
        if value:
            groups[value].append(record)
    return tuple((key, tuple(value)) for key, value in sorted(groups.items()) if len(value) > 1)


def reconcile_inventory(conn: sqlite3.Connection, inventory_path: str | Path) -> ReconciliationResult:
    government_records = load_government_records(inventory_path)
    assettrack_records = load_assettrack_records(conn)
    active_records = tuple(record for record in assettrack_records if not record.is_terminal)
    terminal_records = tuple(record for record in assettrack_records if record.is_terminal)

    government_by_key = _group_government_by_key(government_records)
    assettrack_active_by_key = _group_assettrack_by_key(active_records)
    assettrack_terminal_by_key = _group_assettrack_by_key(terminal_records)

    ambiguous_government_tags = tuple(
        (key, tuple(records))
        for key, records in sorted(government_by_key.items())
        if len(records) > 1
    )
    ambiguous_assettrack_tags = tuple(
        (key, tuple(records))
        for key, records in sorted(assettrack_active_by_key.items())
        if len(records) > 1
    )
    ambiguous_government_keys = {key for key, _records in ambiguous_government_tags}
    ambiguous_assettrack_keys = {key for key, _records in ambiguous_assettrack_tags}

    tag_matches: list[tuple[GovernmentRecord, AssetTrackRecord]] = []
    identity_conflicts: list[tuple[GovernmentRecord, AssetTrackRecord]] = []
    government_only: list[GovernmentRecord] = []
    terminal_matches: list[tuple[GovernmentRecord, AssetTrackRecord]] = []
    matched_active_keys: set[str] = set()
    matched_terminal_keys: set[str] = set()

    for government in sorted(government_records, key=lambda record: (record.key, record.row_number)):
        key = government.key
        if not key or key in ambiguous_government_keys or key in ambiguous_assettrack_keys:
            continue
        active_match = assettrack_active_by_key.get(key, [])
        if len(active_match) == 1:
            asset = active_match[0]
            matched_active_keys.add(key)
            if (
                government.serial_number
                and asset.serial_number
                and government.serial_number.upper() != asset.serial_number.upper()
            ):
                identity_conflicts.append((government, asset))
            else:
                tag_matches.append((government, asset))
            continue
        terminal_match = assettrack_terminal_by_key.get(key, [])
        if len(terminal_match) == 1:
            matched_terminal_keys.add(key)
            terminal_matches.append((government, terminal_match[0]))
            continue
        government_only.append(government)

    assettrack_only_active = tuple(
        record
        for record in active_records
        if record.key and record.key not in matched_active_keys and record.key not in ambiguous_assettrack_keys
    )
    terminal_assettrack_only = tuple(
        record
        for record in terminal_records
        if record.key and record.key not in matched_terminal_keys
    )

    return ReconciliationResult(
        government_records=government_records,
        assettrack_active_records=active_records,
        assettrack_terminal_records=terminal_records,
        tag_matches=tuple(sorted(tag_matches, key=lambda item: item[0].asset_tag)),
        government_only=tuple(sorted(government_only, key=lambda record: record.asset_tag)),
        assettrack_only_active=tuple(sorted(assettrack_only_active, key=lambda record: record.asset_tag)),
        identity_conflicts=tuple(sorted(identity_conflicts, key=lambda item: item[0].asset_tag)),
        ambiguous_government_tags=ambiguous_government_tags,
        ambiguous_assettrack_tags=ambiguous_assettrack_tags,
        duplicate_serial_warnings=_duplicate_government_field(government_records, "serial_number"),
        duplicate_mac_warnings=_duplicate_government_field(government_records, "mac_address"),
        terminal_matches=tuple(sorted(terminal_matches, key=lambda item: item[0].asset_tag)),
        terminal_assettrack_only=tuple(sorted(terminal_assettrack_only, key=lambda record: record.asset_tag)),
    )


def _record_tags(records) -> str:
    values = [getattr(record, "asset_tag") for record in records]
    return ", ".join(values) if values else "None"


def format_reconciliation(result: ReconciliationResult) -> str:
    lines = ["Government Inventory Reconciliation", "", "Summary"]
    for key, value in result.summary_counts().items():
        lines.append(f"  {key}: {value}")

    sections = [
        ("Exact / Normalized Tag Matches", [f"{gov.asset_tag} -> {asset.asset_tag}" for gov, asset in result.tag_matches]),
        ("Government-Only Assets", [record.asset_tag for record in result.government_only]),
        ("AssetTrack-Only Active Assets", [record.asset_tag for record in result.assettrack_only_active]),
        (
            "Identity Conflicts",
            [
                f"{gov.asset_tag} -> {asset.asset_tag}; serial {gov.serial_number or 'blank'} != {asset.serial_number or 'blank'}"
                for gov, asset in result.identity_conflicts
            ],
        ),
        (
            "Ambiguous Government Normalized Tags",
            [f"{key}: {_record_tags(records)}" for key, records in result.ambiguous_government_tags],
        ),
        (
            "Ambiguous AssetTrack Normalized Tags",
            [f"{key}: {_record_tags(records)}" for key, records in result.ambiguous_assettrack_tags],
        ),
        (
            "Duplicate Government Serial Warnings",
            [f"{key}: {_record_tags(records)}" for key, records in result.duplicate_serial_warnings],
        ),
        (
            "Duplicate Government MAC Warnings",
            [f"{key}: {_record_tags(records)}" for key, records in result.duplicate_mac_warnings],
        ),
        (
            "Retired / Disposed AssetTrack Tag Matches",
            [f"{gov.asset_tag} -> {asset.asset_tag} ({asset.location_type})" for gov, asset in result.terminal_matches],
        ),
        (
            "Retired / Disposed AssetTrack-Only Assets",
            [f"{record.asset_tag} ({record.location_type})" for record in result.terminal_assettrack_only],
        ),
    ]
    for title, rows in sections:
        lines.extend(["", title])
        if rows:
            lines.extend(f"  - {row}" for row in rows)
        else:
            lines.append("  None")
    return "\n".join(lines)


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only reconciliation of government inventory against AssetTrack.")
    parser.add_argument("inventory_path", help="Path to the government inventory .xlsx or .csv file.")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to the AssetTrack SQLite database.")
    args = parser.parse_args(argv)

    try:
        conn = _open_readonly_database(Path(args.db))
    except sqlite3.Error as exc:
        print(f"Could not open database read-only: {exc}", file=sys.stderr)
        return 1

    try:
        result = reconcile_inventory(conn, args.inventory_path)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Reconciliation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(format_reconciliation(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
