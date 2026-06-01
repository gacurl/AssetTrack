from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from assettrack.db import bootstrap_db
from assettrack.ingest.committer import BatchCommitError, commit_batch

ALLOWED_COLUMNS = {
    "asset_tag",
    "barcode",
    "serial_number",
    "equipment_type",
    "manufacturer",
    "model",
    "location_building",
    "case_identifier",
    "slot_identifier",
    "notes_comments",
}
REJECTED_CMDB_COLUMNS = {
    "ip_address",
    "mac_address",
    "vlan",
    "switch_port",
    "topology",
    "patching",
    "network_relationships",
    "running_configuration",
    "device_configuration",
}
ALLOWED_EQUIPMENT_TYPES = {"switch", "router"}


@dataclass(frozen=True)
class NetworkAssetImportRow:
    row_number: int
    asset_tag: str
    serial_number: str
    equipment_type: str
    manufacturer: str
    model: str
    building: str
    case_identifier: str
    slot_identifier: str
    notes: str

    def to_ingest_row(self, *, actor: str, timestamp: str) -> dict[str, object]:
        return {
            "row_number": self.row_number,
            "data": {
                "asset_tag": self.asset_tag,
                "serial_number": self.serial_number,
                "equipment_type": self.equipment_type,
                "manufacturer": self.manufacturer,
                "model": self.model,
                "building": self.building,
                "case_number": self.case_identifier,
                "slot_number": self.slot_identifier,
                "notes": self.notes,
                "timestamp": timestamp,
                "event_type": "SCAN",
                "operator_id": actor,
            },
        }


@dataclass(frozen=True)
class NetworkAssetImportReport:
    processed: int
    imported: int
    errors: tuple[str, ...]

    def summary(self) -> dict[str, int]:
        return {
            "processed": self.processed,
            "imported": self.imported,
            "errors": len(self.errors),
        }


def _normalize_header(name: str | None) -> str:
    return str(name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_text(value: str | None) -> str:
    return str(value or "").strip()


def _load_rows(csv_path: str | Path, conn: sqlite3.Connection) -> NetworkAssetImportReport | list[NetworkAssetImportRow]:
    path = Path(csv_path)
    if not path.exists():
        return NetworkAssetImportReport(processed=0, imported=0, errors=(f"CSV not found: {path}",))

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return NetworkAssetImportReport(processed=0, imported=0, errors=("CSV header row is required.",))

        headers = [_normalize_header(field_name) for field_name in reader.fieldnames]
        if any(not header for header in headers):
            return NetworkAssetImportReport(processed=0, imported=0, errors=("CSV headers must not be blank.",))
        if len(set(headers)) != len(headers):
            return NetworkAssetImportReport(processed=0, imported=0, errors=("CSV headers must be unique.",))

        rejected = sorted(set(headers) & REJECTED_CMDB_COLUMNS)
        if rejected:
            return NetworkAssetImportReport(
                processed=0,
                imported=0,
                errors=(f"Rejected CMDB-like CSV columns: {', '.join(rejected)}",),
            )
        unsupported = sorted(set(headers) - ALLOWED_COLUMNS)
        if unsupported:
            return NetworkAssetImportReport(
                processed=0,
                imported=0,
                errors=(f"Unsupported CSV columns: {', '.join(unsupported)}",),
            )

        rows: list[NetworkAssetImportRow] = []
        errors: list[str] = []
        seen_asset_tags: dict[str, int] = {}
        seen_serial_numbers: dict[str, int] = {}
        processed = 0

        for line_number, raw_row in enumerate(reader, start=2):
            normalized_row = {_normalize_header(key): value for key, value in raw_row.items() if key is not None}
            if None in raw_row:
                errors.append(f"Row {line_number}: malformed CSV row has extra columns.")
                continue
            if any(value is None for value in normalized_row.values()):
                errors.append(f"Row {line_number}: malformed CSV row has missing columns.")
                continue
            if all(not _normalize_text(value) for value in normalized_row.values()):
                continue

            processed += 1
            asset_tag = _normalize_text(normalized_row.get("asset_tag")).upper()
            barcode = _normalize_text(normalized_row.get("barcode")).upper()
            serial_number = _normalize_text(normalized_row.get("serial_number"))
            equipment_type = _normalize_text(normalized_row.get("equipment_type")).lower()
            case_identifier = _normalize_text(normalized_row.get("case_identifier")).upper()
            slot_identifier = _normalize_text(normalized_row.get("slot_identifier"))

            if not asset_tag:
                asset_tag = barcode
            if not asset_tag:
                errors.append(f"Row {line_number}: asset_tag is required; barcode may be used when asset_tag is blank.")
            if equipment_type not in ALLOWED_EQUIPMENT_TYPES:
                errors.append(f"Row {line_number}: equipment_type must be switch or router.")

            previous_asset_row = seen_asset_tags.get(asset_tag)
            if asset_tag and previous_asset_row is not None:
                errors.append(f"Row {line_number}: duplicate canonical asset_tag matches row {previous_asset_row}: {asset_tag}")
            elif asset_tag:
                seen_asset_tags[asset_tag] = line_number

            normalized_serial = serial_number.upper()
            previous_serial_row = seen_serial_numbers.get(normalized_serial)
            if normalized_serial and previous_serial_row is not None:
                errors.append(f"Row {line_number}: duplicate serial_number matches row {previous_serial_row}: {serial_number}")
            elif normalized_serial:
                seen_serial_numbers[normalized_serial] = line_number

            if (case_identifier and not slot_identifier) or (slot_identifier and not case_identifier):
                errors.append(f"Row {line_number}: case_identifier and slot_identifier must both be present for slot assignment.")
            elif case_identifier and slot_identifier:
                try:
                    slot_position = int(slot_identifier)
                except ValueError:
                    errors.append(f"Row {line_number}: slot_identifier must be numeric.")
                else:
                    slot = conn.execute(
                        """
                        SELECT s.id, s.current_asset_tag,
                               EXISTS(SELECT 1 FROM slot_occupancy so WHERE so.slot_id = s.id) AS occupied
                        FROM slots s
                        WHERE UPPER(s.case_name) = UPPER(?)
                          AND s.slot_position = ?
                        LIMIT 1;
                        """,
                        (case_identifier, slot_position),
                    ).fetchone()
                    if slot is None:
                        errors.append(f"Row {line_number}: case_identifier + slot_identifier does not reference an existing slot.")
                    elif bool(slot["occupied"]) or _normalize_text(slot["current_asset_tag"]):
                        errors.append(f"Row {line_number}: selected slot is already occupied.")

            rows.append(
                NetworkAssetImportRow(
                    row_number=line_number,
                    asset_tag=asset_tag,
                    serial_number=serial_number,
                    equipment_type=equipment_type,
                    manufacturer=_normalize_text(normalized_row.get("manufacturer")),
                    model=_normalize_text(normalized_row.get("model")),
                    building=_normalize_text(normalized_row.get("location_building")),
                    case_identifier=case_identifier,
                    slot_identifier=slot_identifier,
                    notes=_normalize_text(normalized_row.get("notes_comments")),
                )
            )

        for row in rows:
            existing_asset = conn.execute(
                "SELECT 1 FROM assets WHERE UPPER(asset_tag) = UPPER(?) LIMIT 1;",
                (row.asset_tag,),
            ).fetchone()
            if row.asset_tag and existing_asset is not None:
                errors.append(f"Row {row.row_number}: asset_tag already exists: {row.asset_tag}")

            if row.serial_number:
                existing_serial = conn.execute(
                    """
                    SELECT 1
                    FROM assets
                    WHERE TRIM(COALESCE(serial_number, '')) <> ''
                      AND UPPER(serial_number) = UPPER(?)
                    LIMIT 1;
                    """,
                    (row.serial_number,),
                ).fetchone()
                if existing_serial is not None:
                    errors.append(f"Row {row.row_number}: serial_number already exists: {row.serial_number}")

        if errors:
            return NetworkAssetImportReport(processed=processed, imported=0, errors=tuple(errors))
        return rows


def import_network_assets_csv(
    csv_path: str | Path,
    *,
    db_path: str | Path,
    actor: str,
) -> NetworkAssetImportReport:
    normalized_actor = _normalize_text(actor)
    if not normalized_actor:
        return NetworkAssetImportReport(processed=0, imported=0, errors=("actor is required.",))

    path = Path(db_path)
    bootstrap_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        parsed = _load_rows(csv_path, conn)
    finally:
        conn.close()

    if isinstance(parsed, NetworkAssetImportReport):
        return parsed
    if not parsed:
        return NetworkAssetImportReport(processed=0, imported=0, errors=("CSV contains no import rows.",))

    timestamp = datetime.now(timezone.utc).isoformat()
    ingest_rows = [row.to_ingest_row(actor=normalized_actor, timestamp=timestamp) for row in parsed]
    try:
        result = commit_batch(ingest_rows, db_path=str(path))
    except BatchCommitError as exc:
        return NetworkAssetImportReport(processed=len(parsed), imported=0, errors=(f"Import failed: {exc}",))
    return NetworkAssetImportReport(processed=len(parsed), imported=result.committed_count, errors=())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assettrack.network_asset_import")
    parser.add_argument("csv_path", help="Path to reviewed network switch/router staging CSV")
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    parser.add_argument("--actor", required=True, help="Operator performing the import")
    args = parser.parse_args(argv)

    report = import_network_assets_csv(args.csv_path, db_path=args.db, actor=args.actor)
    print(json.dumps(report.summary(), sort_keys=True))
    if report.errors:
        for error in report.errors:
            print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
