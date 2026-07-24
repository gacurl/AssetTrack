from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from assettrack.assets import (
    SUPPORTED_EQUIPMENT_TYPE_MESSAGE,
    equipment_type_label,
    validate_new_equipment_type,
)

IDENTITY_COLUMNS = ("asset_tag", "barcode", "clean_asset_tag")
REQUIRED_COLUMNS = {"equipment_type"}
ALLOWED_COLUMNS = {
    "asset_tag",
    "barcode",
    "clean_asset_tag",
    "serial_number",
    "equipment_type",
    "manufacturer",
    "model",
    "model_code",
    "building_room",
    "location_building",
    "case_identifier",
    "slot_identifier",
    "case_number",
    "slot_number",
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


@dataclass(frozen=True)
class AssetImportAnalysisRow:
    row_number: int
    asset_tag: str
    serial_number: str
    equipment_type: str
    manufacturer: str
    model: str
    model_code: str
    building_room: str
    location_building: str
    case_identifier: str
    slot_identifier: str
    notes: str

    @property
    def storage_intent(self) -> str:
        return "slotted" if self.case_identifier and self.slot_identifier else "unslotted"


@dataclass(frozen=True)
class AssetImportAnalysis:
    filename: str
    file_type: str
    rows: tuple[AssetImportAnalysisRow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def equipment_types(self) -> list[str]:
        values = {row.equipment_type for row in self.rows}
        return [equipment_type_label(value) for value in sorted(values)]

    def to_template_result(self) -> dict:
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "equipment_types": self.equipment_types,
            "warnings": list(self.warnings),
        }


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value or "").strip()


def _first_line(value: object) -> str:
    text = str(value or "").strip()
    return text.splitlines()[0] if text else ""


def _validate_headers(headers: list[str], *, file_type: str) -> tuple[str, ...]:
    if any(not header for header in headers):
        raise ValueError(f"Malformed {file_type} file. Column headers cannot be blank.")
    if len(headers) != len(set(headers)):
        raise ValueError(f"Malformed {file_type} file. Column headers must be unique.")

    unsupported = sorted((set(headers) - ALLOWED_COLUMNS) | (set(headers) & REJECTED_CMDB_COLUMNS))
    warnings: list[str] = []
    if unsupported:
        warnings.append(
            f"Ignored unsupported {file_type} column"
            f"{'' if len(unsupported) == 1 else 's'}: {', '.join(unsupported)}."
        )

    missing = sorted(REQUIRED_COLUMNS - set(headers))
    if missing:
        raise ValueError(
            f"Missing required {file_type} column"
            f"{'' if len(missing) == 1 else 's'}: {', '.join(missing)}."
        )
    if not set(IDENTITY_COLUMNS).intersection(headers):
        raise ValueError(
            f"Missing required {file_type} column: asset_tag or barcode."
        )
    return tuple(warnings)


def _canonical_row(raw_row: dict[str, object], *, row_number: int) -> AssetImportAnalysisRow | None:
    row = {
        normalized_key: _normalize_text(value)
        for key, value in raw_row.items()
        if (normalized_key := _normalize_header(key)) in ALLOWED_COLUMNS
    }
    if not any(row.values()):
        return None

    asset_tag = ""
    for column in IDENTITY_COLUMNS:
        asset_tag = _normalize_text(row.get(column)).upper()
        if asset_tag:
            break
    if not asset_tag:
        raise ValueError(f"Row {row_number}: asset_tag or barcode is required.")

    try:
        equipment_type = validate_new_equipment_type(row.get("equipment_type", ""))
    except ValueError as exc:
        message = _first_line(exc) or SUPPORTED_EQUIPMENT_TYPE_MESSAGE
        raise ValueError(f"Row {row_number}: {message}") from exc

    case_identifier = _normalize_text(row.get("case_identifier")).upper()
    if not case_identifier:
        case_number = _normalize_text(row.get("case_number")).upper()
        case_identifier = f"CASE-{case_number}" if case_number else ""
    slot_identifier = _normalize_text(row.get("slot_identifier")) or _normalize_text(row.get("slot_number"))

    if bool(case_identifier) != bool(slot_identifier):
        raise ValueError(f"Row {row_number}: storage case and slot must both be present or both be blank.")

    return AssetImportAnalysisRow(
        row_number=row_number,
        asset_tag=asset_tag,
        serial_number=_normalize_text(row.get("serial_number")),
        equipment_type=equipment_type,
        manufacturer=_normalize_text(row.get("manufacturer")),
        model=_normalize_text(row.get("model")),
        model_code=_normalize_text(row.get("model_code")),
        building_room=_normalize_text(row.get("building_room")),
        location_building=_normalize_text(row.get("location_building")),
        case_identifier=case_identifier,
        slot_identifier=slot_identifier,
        notes=_normalize_text(row.get("notes_comments")),
    )


def _validate_duplicates(rows: list[AssetImportAnalysisRow]) -> None:
    seen_asset_tags: dict[str, int] = {}
    seen_serial_numbers: dict[str, int] = {}
    for row in rows:
        previous_asset_row = seen_asset_tags.get(row.asset_tag)
        if previous_asset_row is not None:
            raise ValueError(
                f"Row {row.row_number}: duplicate asset_tag matches row {previous_asset_row}: {row.asset_tag}."
            )
        seen_asset_tags[row.asset_tag] = row.row_number

        normalized_serial = row.serial_number.upper()
        if not normalized_serial:
            continue
        previous_serial_row = seen_serial_numbers.get(normalized_serial)
        if previous_serial_row is not None:
            raise ValueError(
                f"Row {row.row_number}: duplicate serial_number matches row {previous_serial_row}: {row.serial_number}."
            )
        seen_serial_numbers[normalized_serial] = row.row_number


def _analyze_rows(
    raw_rows: list[dict[str, object]],
    *,
    headers: list[str],
    filename: str,
    file_type: str,
) -> AssetImportAnalysis:
    warnings = _validate_headers(headers, file_type=file_type)

    rows: list[AssetImportAnalysisRow] = []
    for offset, raw_row in enumerate(raw_rows, start=2):
        row = _canonical_row(raw_row, row_number=offset)
        if row is not None:
            rows.append(row)

    _validate_duplicates(rows)
    return AssetImportAnalysis(filename=filename, file_type=file_type.upper(), rows=tuple(rows), warnings=warnings)


def analyze_asset_import_csv(csv_path: str | Path, *, filename: str) -> AssetImportAnalysis:
    path = Path(csv_path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("Malformed CSV file. Include a header row.")

            headers = [_normalize_header(header) for header in reader.fieldnames]
            raw_rows: list[dict[str, object]] = []
            for row_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    raise ValueError(f"Malformed CSV file. Row {row_number} has extra columns.")
                if any(value is None for value in raw_row.values()):
                    raise ValueError(f"Malformed CSV file. Row {row_number} has missing columns.")
                raw_rows.append({str(key): value for key, value in raw_row.items() if key is not None})
    except UnicodeDecodeError as exc:
        raise ValueError("Malformed CSV file. Upload a UTF-8 CSV file.") from exc
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV file. {exc}") from exc

    return _analyze_rows(raw_rows, headers=headers, filename=filename, file_type="CSV")


def analyze_asset_import_xlsx(xlsx_path: str | Path, *, filename: str) -> AssetImportAnalysis:
    path = Path(xlsx_path)
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"PK":
                raise ValueError("Malformed XLSX file. Upload a valid .xlsx workbook.")
        dataframe = pd.read_excel(path, engine="openpyxl")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Malformed XLSX file. Upload a valid .xlsx workbook.") from exc

    headers = [_normalize_header(header) for header in dataframe.columns]
    raw_rows = [
        {str(column): row[column] for column in dataframe.columns}
        for _, row in dataframe.iterrows()
    ]
    return _analyze_rows(raw_rows, headers=headers, filename=filename, file_type="XLSX")
