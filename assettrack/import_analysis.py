from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from assettrack.assets import (
    SUPPORTED_EQUIPMENT_TYPE_MESSAGE,
    equipment_type_label,
    validate_new_equipment_type,
)
from assettrack.barcodes import barcode_lookup_key
from assettrack.cases import normalize_case_size

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
BQ26_PLACEHOLDER_BARCODES = {"", "--"}
BQ26_TYPE_CORRECTIONS = {
    "swtich": "switch",
    "cisco 4331": "router",
    "cisco 4431": "router",
    "dell poweredge r640": "server",
    "3560cx_12": "switch",
    "3560cx-12": "switch",
    "cisco 3560cx_12": "switch",
    "cisco 3560cx-12": "switch",
    "server monitor kvm": "kvm",
}
BQ26_KNOWN_MANUFACTURERS = {
    "apc",
    "cisco",
    "dell",
    "dkx3-832",
    "microsemi",
    "rairtan",
    "synology",
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
    source_fields: frozenset[str] = frozenset()
    barcode_key: str = ""
    source_workbook: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def storage_intent(self) -> str:
        return "slotted" if self.case_identifier and self.slot_identifier else "unslotted"

    def has_source_field(self, field: str) -> bool:
        return field in self.source_fields


@dataclass(frozen=True)
class AssetImportAnalysisIssue:
    row_number: int
    category: str
    message: str
    fields: tuple[str, ...] = ()
    asset_identifier: str = ""


@dataclass(frozen=True)
class AssetImportAnalysis:
    filename: str
    file_type: str
    rows: tuple[AssetImportAnalysisRow, ...]
    warnings: tuple[str, ...] = ()
    issues: tuple[AssetImportAnalysisIssue, ...] = ()
    case_plans: tuple[dict[str, object], ...] = ()
    ignored_rows: int = 0
    barcode_keys: tuple[str, ...] = ()

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
            "issues": [issue.__dict__ for issue in self.issues],
            "case_plans": list(self.case_plans),
            "ignored_rows": self.ignored_rows,
        }


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value or "").strip()


def _normalize_slot_identifier(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, bool):
        return str(value).strip()
    if isinstance(value, int):
        return str(value)

    text = str(value or "").strip()
    if not text:
        return ""

    try:
        numeric_value = Decimal(text)
    except InvalidOperation:
        return text

    # Spreadsheet readers commonly coerce whole-number cells to floats. Slot
    # identifiers are logical integers, so normalize at the import boundary and
    # give downstream reconciliation one canonical representation.
    if numeric_value.is_finite() and numeric_value == numeric_value.to_integral_value():
        return str(int(numeric_value))
    return text


def _first_line(value: object) -> str:
    text = str(value or "").strip()
    return text.splitlines()[0] if text else ""


def _type_source_key(value: object) -> str:
    text = _normalize_bq26_text(value).lower()
    return re.sub(r"\s+", " ", text).strip()


def _normalize_bq26_text(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, bool):
        return str(value).strip()
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        numeric_value = Decimal(text)
    except InvalidOperation:
        return text
    if numeric_value.is_finite() and numeric_value == numeric_value.to_integral_value():
        return str(int(numeric_value))
    return text


def _normalize_bq26_type(value: object, *, make: object = "", model: object = "") -> str:
    source_key = _type_source_key(value)
    make_model_key = _type_source_key(f"{_normalize_bq26_text(make)} {_normalize_bq26_text(model)}")
    if make_model_key in BQ26_TYPE_CORRECTIONS:
        return validate_new_equipment_type(BQ26_TYPE_CORRECTIONS[make_model_key])
    if source_key in BQ26_TYPE_CORRECTIONS:
        return validate_new_equipment_type(BQ26_TYPE_CORRECTIONS[source_key])
    try:
        return validate_new_equipment_type(value)
    except ValueError:
        if make_model_key:
            return validate_new_equipment_type(make_model_key)
        raise


def normalize_bq26_case_name(value: object) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = re.split(r"\s+-\s+", text, maxsplit=1)[0]
    text = re.split(r"\s+[A-Za-z]{3,9}-\d{1,2}\b", text, maxsplit=1)[0]
    text = re.sub(r"\s+", "", text).upper()
    match = re.fullmatch(r"(\d+)RU-?(\d+)", text)
    if match:
        return f"{int(match.group(1))}RU-{int(match.group(2)):02d}"
    return text


def _case_size_from_source(value: object) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    lowered = re.sub(r"\s+", " ", text).strip().lower()
    aliases = {
        "small wheel": "Small Wheel",
        "medium wheel": "Medium Wheel",
        "large wheel": "Large Wheel",
        "16ru": "16 Rack Unit Wheel",
        "16 ru": "16 Rack Unit Wheel",
        "16 rack unit wheel": "16 Rack Unit Wheel",
        "4ru": "4 Rack Unit Wheel",
        "4 ru": "4 Rack Unit Wheel",
        "4 rack unit wheel": "4 Rack Unit Wheel",
        "6ru": "6 Rack Unit Wheel",
        "6 ru": "6 Rack Unit Wheel",
        "6 rack unit wheel": "6 Rack Unit Wheel",
        "8ru": "8 Rack Unit Wheel",
        "8 ru": "8 Rack Unit Wheel",
        "8 rack unit wheel": "8 Rack Unit Wheel",
        "white case": "White Case",
        "white cases": "White Case",
        "sm-case": "SM-Case",
        "sm case": "SM-Case",
    }
    return normalize_case_size(aliases.get(lowered, text))


def _is_placeholder_barcode(value: object) -> bool:
    text = _normalize_bq26_text(value).lower()
    return text in BQ26_PLACEHOLDER_BARCODES or bool(re.fullmatch(r"-{2,}", text))


def _normalize_bq26_header(value: object) -> str:
    text = _normalize_bq26_text(value).lower()
    text = text.replace("\\", " ")
    text = re.sub(r"\([^)]*\)", "", text)
    text = text.replace("#", "_#")
    text = re.sub(r"[^a-z0-9#]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    aliases = {
        "case_#": "case_#",
        "commnet": "commnet",
        "make_model": "make_model",
        "seriel": "serial",
        "product": "equipment_type",
    }
    return aliases.get(text, text)


def _bq26_raw_rows(dataframe: pd.DataFrame) -> list[list[object]]:
    return [
        [row[index] for index in range(len(row))]
        for row in dataframe.itertuples(index=False, name=None)
    ]


def _bq26_header_map(values: list[object]) -> dict[str, int]:
    header: dict[str, int] = {}
    for index, value in enumerate(values):
        key = _normalize_bq26_header(value)
        if key:
            header.setdefault(key, index)
    return header


def _bq26_cell(row: list[object], index: int | None) -> object:
    if index is None or index >= len(row):
        return ""
    return row[index]


def _split_bq26_make_model(make: object, model: object, make_model: object) -> tuple[str, str]:
    make_text = _normalize_bq26_text(make)
    model_text = _normalize_bq26_text(model)
    make_model_text = _normalize_bq26_text(make_model)
    if make_text or model_text or not make_model_text:
        return make_text, model_text or make_model_text
    parts = make_model_text.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() in BQ26_KNOWN_MANUFACTURERS:
        return parts[0], parts[1]
    return "", make_model_text


def _read_bq26_case_plans(dataframe: pd.DataFrame) -> tuple[dict[str, dict[str, object]], tuple[str, ...]]:
    raw_rows = _bq26_raw_rows(dataframe)
    warnings: list[str] = []
    plans: dict[str, dict[str, object]] = {}
    for header_index, values in enumerate(raw_rows):
        header = _bq26_header_map(values)
        if "name_cases" in header and "quantity" in header:
            case_column = header["name_cases"]
            quantity_column = header["quantity"]
            case_size_column = header.get("case_size")
            case_number_column = header.get("case_#")
            for row in raw_rows[header_index + 1 :]:
                raw_case = _bq26_cell(row, case_column) or _bq26_cell(row, case_number_column)
                case_name = normalize_bq26_case_name(raw_case)
                if not case_name:
                    continue
                try:
                    quantity = int(Decimal(_normalize_slot_identifier(_bq26_cell(row, quantity_column))))
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError(f"Name Cases row for {case_name}: quantity must be a whole number.") from exc
                if quantity < 0:
                    raise ValueError(f"Name Cases row for {case_name}: quantity cannot be negative.")
                case_size = _case_size_from_source(_bq26_cell(row, case_size_column)) if case_size_column is not None else ""
                if case_name in plans:
                    warnings.append(f"Duplicate Name Cases entry for {case_name}; first entry was used.")
                    continue
                plans[case_name] = {
                    "case_name": case_name,
                    "case_size": case_size,
                    "quantity": quantity,
                    "assigned_count": 0,
                    "warnings": [],
                }
            break
        quantity_pairs = [
            (index, index + 1)
            for index, value in enumerate(values[:-1])
            if _normalize_bq26_text(value) and _normalize_bq26_header(values[index + 1]).startswith("qty")
        ]
        if quantity_pairs:
            for case_column, quantity_column in quantity_pairs:
                case_size = _case_size_from_source(values[case_column])
                for row in raw_rows[header_index + 1 :]:
                    case_name = normalize_bq26_case_name(_bq26_cell(row, case_column))
                    if not case_name:
                        continue
                    try:
                        quantity = int(Decimal(_normalize_slot_identifier(_bq26_cell(row, quantity_column))))
                    except (InvalidOperation, ValueError) as exc:
                        raise ValueError(f"Name Cases row for {case_name}: quantity must be a whole number.") from exc
                    if quantity < 0:
                        raise ValueError(f"Name Cases row for {case_name}: quantity cannot be negative.")
                    if case_name in plans:
                        warnings.append(f"Duplicate Name Cases entry for {case_name}; first entry was used.")
                        continue
                    plans[case_name] = {
                        "case_name": case_name,
                        "case_size": case_size,
                        "quantity": quantity,
                        "assigned_count": 0,
                        "warnings": [],
                    }
            break
    if not plans:
        raise ValueError("Malformed BQ26 workbook. Name Cases contains no valid cases.")
    return plans, tuple(warnings)


def _bq26_asset_sheet_names(sheets: dict[str, pd.DataFrame]) -> tuple[str, ...]:
    sheet_names: list[str] = []
    for sheet_name, dataframe in sheets.items():
        if sheet_name.strip().lower() == "name cases":
            continue
        for values in _bq26_raw_rows(dataframe):
            header = _bq26_header_map(values)
            if "barcode" in header and "case_#" in header:
                sheet_names.append(sheet_name)
                break
    if not sheet_names:
        raise ValueError("Malformed BQ26 workbook. No asset worksheet with Barcode and Case # columns was found.")
    return tuple(sheet_names)


def _bq26_row_value(raw_row: dict[str, object], *names: str) -> object:
    for name in names:
        if name in raw_row:
            return raw_row.get(name)
    return ""


def _iter_bq26_asset_rows(sheets: dict[str, pd.DataFrame]):
    logical_row_number = 1
    for sheet_name, dataframe in sheets.items():
        if sheet_name.strip().lower() == "name cases":
            continue
        header: dict[str, int] | None = None
        for values in _bq26_raw_rows(dataframe):
            candidate = _bq26_header_map(values)
            if "barcode" in candidate and "case_#" in candidate:
                header = candidate
                continue
            if "barcode" in candidate:
                continue
            if header is None:
                continue
            barcode = _bq26_cell(values, header.get("barcode"))
            if not _normalize_bq26_text(barcode) and not any(_normalize_bq26_text(value) for value in values):
                continue
            logical_row_number += 1
            make, model = _split_bq26_make_model(
                _bq26_cell(values, header.get("make")),
                _bq26_cell(values, header.get("model")),
                _bq26_cell(values, header.get("make_model")),
            )
            yield (
                logical_row_number,
                sheet_name,
                {
                    "barcode": barcode,
                    "serial": _bq26_cell(values, header.get("serial")),
                    "equipment_type": _bq26_cell(values, header.get("equipment_type")),
                    "make": make,
                    "model": model,
                    "case_#": _bq26_cell(values, header.get("case_#")),
                    "commnet": _bq26_cell(values, header.get("commnet")),
                },
            )


def _analyze_bq26_workbook(
    sheets: dict[str, pd.DataFrame],
    *,
    filename: str,
) -> AssetImportAnalysis:
    case_sheet = next(
        (dataframe for sheet_name, dataframe in sheets.items() if sheet_name.strip().lower() == "name cases"),
        None,
    )
    if case_sheet is None:
        raise ValueError("Malformed BQ26 workbook. Name Cases worksheet is required.")
    case_plans, case_warnings = _read_bq26_case_plans(case_sheet)
    asset_sheet_names = _bq26_asset_sheet_names(sheets)
    warnings = list(case_warnings)
    if any(sheet_name.strip().lower() not in {"network", "network inventory", "bq26 network"} for sheet_name in asset_sheet_names):
        warnings.append("Asset worksheet names are descriptive only and were accepted.")

    rows: list[AssetImportAnalysisRow] = []
    issues: list[AssetImportAnalysisIssue] = []
    case_asset_ordinals: dict[str, int] = {}
    ignored_rows = 0
    seen_barcodes: dict[str, int] = {}
    seen_serials: dict[str, int] = {}

    for offset, _sheet_name, raw in _iter_bq26_asset_rows(sheets):
        raw_barcode = _normalize_bq26_text(_bq26_row_value(raw, "barcode"))
        if _is_placeholder_barcode(raw_barcode):
            ignored_rows += 1
            continue
        barcode_key = barcode_lookup_key(raw_barcode)
        if not barcode_key:
            ignored_rows += 1
            continue
        case_name = normalize_bq26_case_name(_bq26_row_value(raw, "case_#"))
        if not case_name or case_name not in case_plans:
            issues.append(
                AssetImportAnalysisIssue(
                    row_number=offset,
                    category="invalid_upload_row",
                    message=f"Case # does not match Name Cases: {_normalize_text(_bq26_row_value(raw, 'case_#')) or 'blank'}.",
                    fields=("case_#",),
                    asset_identifier=raw_barcode,
                )
            )
            continue
        previous_barcode_row = seen_barcodes.get(barcode_key)
        if previous_barcode_row is not None:
            issues.append(
                AssetImportAnalysisIssue(
                    row_number=offset,
                    category="duplicate_upload_row",
                    message=f"duplicate normalized barcode matches row {previous_barcode_row}: {raw_barcode}.",
                    fields=("barcode",),
                    asset_identifier=raw_barcode,
                )
            )
            continue
        seen_barcodes[barcode_key] = offset

        serial = _normalize_text(_bq26_row_value(raw, "serial"))
        normalized_serial = serial.upper()
        if normalized_serial:
            previous_serial_row = seen_serials.get(normalized_serial)
            if previous_serial_row is not None:
                issues.append(
                    AssetImportAnalysisIssue(
                        row_number=offset,
                        category="duplicate_upload_row",
                        message=f"duplicate serial matches row {previous_serial_row}: {serial}.",
                        fields=("serial",),
                        asset_identifier=raw_barcode,
                    )
                )
                continue
            seen_serials[normalized_serial] = offset

        try:
            equipment_type = _normalize_bq26_type(
                _bq26_row_value(raw, "equipment_type", "type"),
                make=_bq26_row_value(raw, "make"),
                model=_bq26_row_value(raw, "model"),
            )
        except ValueError as exc:
            message = _first_line(exc) or SUPPORTED_EQUIPMENT_TYPE_MESSAGE
            issues.append(
                AssetImportAnalysisIssue(
                    row_number=offset,
                    category="invalid_upload_row",
                    message=message,
                    fields=("equipment_type", "make", "model"),
                    asset_identifier=raw_barcode,
                )
            )
            continue

        case_asset_ordinals[case_name] = case_asset_ordinals.get(case_name, 0) + 1
        ordinal = case_asset_ordinals[case_name]
        notes = _normalize_text(_bq26_row_value(raw, "commnet", "notes", "comment"))
        row_warnings: list[str] = []
        if not serial:
            row_warnings.append("Missing serial number.")
        rows.append(
            AssetImportAnalysisRow(
                row_number=offset,
                asset_tag=raw_barcode,
                serial_number=serial,
                equipment_type=equipment_type,
                manufacturer=_normalize_text(_bq26_row_value(raw, "make")),
                model=_normalize_bq26_text(_bq26_row_value(raw, "model")),
                model_code="",
                building_room="",
                location_building="",
                case_identifier=case_name,
                slot_identifier=str(ordinal),
                notes=notes,
                source_fields=frozenset(
                    {
                        "asset_tag",
                        "barcode",
                        "serial_number",
                        "equipment_type",
                        "manufacturer",
                        "model",
                        "notes_comments",
                        "case_identifier",
                        "slot_identifier",
                    }
                ),
                barcode_key=barcode_key,
                source_workbook="BQ26",
                warnings=tuple(row_warnings),
            )
        )

    for case_name, plan in case_plans.items():
        assigned_count = int(case_asset_ordinals.get(case_name, 0))
        quantity = int(plan["quantity"])
        plan["assigned_count"] = assigned_count
        plan_warnings = list(plan.get("warnings") or [])
        if assigned_count < quantity:
            plan_warnings.append(f"{case_name} has {assigned_count} barcoded assets for {quantity} provisioned slots.")
        plan["warnings"] = plan_warnings
        if assigned_count > quantity:
            for row in rows:
                if row.case_identifier == case_name:
                    issues.append(
                        AssetImportAnalysisIssue(
                            row_number=row.row_number,
                            category="case_over_capacity",
                            message=f"{case_name} has {assigned_count} barcoded assets but Name Cases quantity is {quantity}.",
                            fields=("case_#", "quantity"),
                            asset_identifier=row.asset_tag,
                        )
                    )

    over_capacity_rows = {issue.row_number for issue in issues if issue.category == "case_over_capacity"}
    if over_capacity_rows:
        rows = [row for row in rows if row.row_number not in over_capacity_rows]

    warnings.extend(
        warning
        for plan in case_plans.values()
        for warning in (plan.get("warnings") or [])
    )
    return AssetImportAnalysis(
        filename=filename,
        file_type="BQ26 XLSX",
        rows=tuple(rows),
        warnings=tuple(warnings),
        issues=tuple(issues),
        case_plans=tuple(case_plans[case_name] for case_name in sorted(case_plans)),
        ignored_rows=ignored_rows,
        barcode_keys=tuple(sorted(seen_barcodes)),
    )


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


def _raw_asset_identifier(raw_row: dict[str, object]) -> str:
    row = {
        normalized_key: _normalize_text(value)
        for key, value in raw_row.items()
        if (normalized_key := _normalize_header(key)) in ALLOWED_COLUMNS
    }
    for column in IDENTITY_COLUMNS:
        identifier = _normalize_text(row.get(column)).upper()
        if identifier:
            return identifier
    return ""


def _canonical_row(raw_row: dict[str, object], *, row_number: int) -> AssetImportAnalysisRow | None:
    row = {
        normalized_key: _normalize_slot_identifier(value)
        if normalized_key in {"slot_identifier", "slot_number"}
        else _normalize_text(value)
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
    slot_identifier = _normalize_slot_identifier(row.get("slot_identifier")) or _normalize_slot_identifier(row.get("slot_number"))

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
        source_fields=frozenset(row),
    )


def _duplicate_issues(rows: list[AssetImportAnalysisRow]) -> tuple[AssetImportAnalysisIssue, ...]:
    issues: list[AssetImportAnalysisIssue] = []
    seen_asset_tags: dict[str, int] = {}
    seen_serial_numbers: dict[str, int] = {}
    for row in rows:
        previous_asset_row = seen_asset_tags.get(row.asset_tag)
        if previous_asset_row is not None:
            issues.append(
                AssetImportAnalysisIssue(
                    row_number=row.row_number,
                    category="duplicate_upload_row",
                    message=f"duplicate asset_tag matches row {previous_asset_row}: {row.asset_tag}.",
                    fields=("asset_tag",),
                    asset_identifier=row.asset_tag,
                )
            )
        else:
            seen_asset_tags[row.asset_tag] = row.row_number

        normalized_serial = row.serial_number.upper()
        if not normalized_serial:
            continue
        previous_serial_row = seen_serial_numbers.get(normalized_serial)
        if previous_serial_row is not None:
            issues.append(
                AssetImportAnalysisIssue(
                    row_number=row.row_number,
                    category="duplicate_upload_row",
                    message=f"duplicate serial_number matches row {previous_serial_row}: {row.serial_number}.",
                    fields=("serial_number",),
                    asset_identifier=row.asset_tag,
                )
            )
        else:
            seen_serial_numbers[normalized_serial] = row.row_number
    return tuple(issues)


def _validate_duplicates(rows: list[AssetImportAnalysisRow]) -> None:
    issues = _duplicate_issues(rows)
    if not issues:
        return
    first = issues[0]
    raise ValueError(f"Row {first.row_number}: {first.message}")


def _analyze_rows(
    raw_rows: list[dict[str, object]],
    *,
    headers: list[str],
    filename: str,
    file_type: str,
    collect_row_errors: bool = False,
) -> AssetImportAnalysis:
    warnings = _validate_headers(headers, file_type=file_type)

    rows: list[AssetImportAnalysisRow] = []
    issues: list[AssetImportAnalysisIssue] = []
    for offset, raw_row in enumerate(raw_rows, start=2):
        try:
            row = _canonical_row(raw_row, row_number=offset)
        except ValueError as exc:
            if not collect_row_errors:
                raise
            issues.append(
                AssetImportAnalysisIssue(
                    row_number=offset,
                    category="invalid_upload_row",
                    message=str(exc).removeprefix(f"Row {offset}: "),
                    asset_identifier=_raw_asset_identifier(raw_row),
                )
            )
            continue
        if row is not None:
            rows.append(row)

    duplicate_issues = _duplicate_issues(rows)
    if duplicate_issues:
        if not collect_row_errors:
            first = duplicate_issues[0]
            raise ValueError(f"Row {first.row_number}: {first.message}")
        issues.extend(duplicate_issues)

    duplicate_row_numbers = {issue.row_number for issue in duplicate_issues}
    if duplicate_row_numbers:
        rows = [row for row in rows if row.row_number not in duplicate_row_numbers]

    return AssetImportAnalysis(
        filename=filename,
        file_type=file_type.upper(),
        rows=tuple(rows),
        warnings=warnings,
        issues=tuple(issues),
    )


def analyze_asset_import_csv(
    csv_path: str | Path,
    *,
    filename: str,
    collect_row_errors: bool = False,
) -> AssetImportAnalysis:
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

    return _analyze_rows(
        raw_rows,
        headers=headers,
        filename=filename,
        file_type="CSV",
        collect_row_errors=collect_row_errors,
    )


def analyze_asset_import_xlsx(
    xlsx_path: str | Path,
    *,
    filename: str,
    collect_row_errors: bool = False,
) -> AssetImportAnalysis:
    path = Path(xlsx_path)
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"PK":
                raise ValueError("Malformed XLSX file. Upload a valid .xlsx workbook.")
        sheets = pd.read_excel(path, engine="openpyxl", sheet_name=None)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Malformed XLSX file. Upload a valid .xlsx workbook.") from exc

    normalized_sheet_names = {sheet_name.strip().lower() for sheet_name in sheets}
    if "name cases" in normalized_sheet_names:
        raw_sheets = pd.read_excel(path, engine="openpyxl", sheet_name=None, header=None)
        return _analyze_bq26_workbook(raw_sheets, filename=filename)

    dataframe = next(iter(sheets.values()))
    headers = [_normalize_header(header) for header in dataframe.columns]
    raw_rows = [
        {str(column): row[column] for column in dataframe.columns}
        for _, row in dataframe.iterrows()
    ]
    return _analyze_rows(
        raw_rows,
        headers=headers,
        filename=filename,
        file_type="XLSX",
        collect_row_errors=collect_row_errors,
    )
