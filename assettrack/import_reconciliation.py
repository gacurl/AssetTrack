from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from assettrack.assets import equipment_type_label
from assettrack.import_analysis import AssetImportAnalysis, AssetImportAnalysisRow

DEFAULTS_BEFORE_COMMIT = (
    ("location_type", "STORAGE"),
    ("current_holder", "Unassigned"),
    ("custody_state", "in_stock"),
    ("accountability_status", "accountable"),
    ("condition", "serviceable"),
    ("storage", "Unslotted when no available slot is provided"),
)

CHANGE_FIELDS = (
    ("serial_number", "serial_number", "serial_number"),
    ("equipment_type", "equipment_type", "equipment_type"),
    ("manufacturer", "manufacturer", "manufacturer"),
    ("model", "model", "model"),
    ("model_code", "model_code", "model_code"),
    ("building_room", "building_room", "building_room"),
    ("location_building", "building", "location_building"),
    ("notes", "notes", "notes_comments"),
)

CATEGORY_LABELS = {
    "new_asset": "New Asset",
    "unchanged_exact_match": "Unchanged Exact Match",
    "proposed_update": "Proposed Update",
    "unslotted_import": "Unslotted Import",
    "slot_conflict_unslotted": "Slot Conflict Eligible For Unslotted Import",
    "identity_conflict": "Identity Conflict",
    "invalid_duplicate_upload_row": "Invalid Or Duplicate Upload Row",
}
CATEGORY_ORDER = tuple(CATEGORY_LABELS)
ATTENTION_CATEGORIES = (
    "proposed_update",
    "slot_conflict_unslotted",
    "identity_conflict",
    "invalid_duplicate_upload_row",
)


@dataclass(frozen=True)
class AssetImportFieldChange:
    field: str
    current: str
    proposed: str


@dataclass(frozen=True)
class AssetImportPreviewRow:
    row_number: int
    asset_tag: str
    asset_identifier: str
    category: str
    category_label: str
    message: str
    changed_fields: tuple[AssetImportFieldChange, ...] = ()
    warnings: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetImportPreviewContext:
    assets_by_tag: dict[str, sqlite3.Row]
    assets_by_serial: dict[str, sqlite3.Row]
    slots_by_case_position: dict[tuple[str, int], sqlite3.Row]
    occupants_by_slot_id: dict[int, sqlite3.Row]
    home_slots_by_id: dict[int, sqlite3.Row]


@dataclass(frozen=True)
class AssetImportPreview:
    filename: str
    file_type: str
    rows: tuple[AssetImportPreviewRow, ...]
    warnings: tuple[str, ...]
    defaults: tuple[tuple[str, str], ...]
    unslotted_acknowledged: bool

    @property
    def totals(self) -> dict[str, int]:
        totals = {category: 0 for category in CATEGORY_ORDER}
        for row in self.rows:
            totals[row.category] = totals.get(row.category, 0) + 1
        return totals

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def requires_unslotted_acknowledgment(self) -> bool:
        return any(row.category in {"unslotted_import", "slot_conflict_unslotted"} for row in self.rows)

    @property
    def blocks_without_unslotted_acknowledgment(self) -> bool:
        return self.requires_unslotted_acknowledgment and not self.unslotted_acknowledged

    def to_template_result(self) -> dict[str, object]:
        row_dicts = [
            {
                "row_number": row.row_number,
                "asset_tag": row.asset_tag,
                "asset_identifier": row.asset_identifier,
                "category": row.category,
                "category_label": row.category_label,
                "message": row.message,
                "warnings": list(row.warnings),
                "fields": list(row.fields),
                "changed_fields": [
                    {"field": change.field, "current": change.current, "proposed": change.proposed}
                    for change in row.changed_fields
                ],
            }
            for row in self.rows
        ]
        rows_by_category = {
            category: [row for row in row_dicts if row["category"] == category]
            for category in CATEGORY_ORDER
        }
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "warnings": list(self.warnings),
            "defaults": [{"field": field, "value": value} for field, value in self.defaults],
            "totals": self.totals,
            "category_labels": CATEGORY_LABELS,
            "category_order": CATEGORY_ORDER,
            "attention_categories": ATTENTION_CATEGORIES,
            "rows": row_dicts,
            "rows_by_category": rows_by_category,
            "total_rows": self.total_rows,
            "unslotted_acknowledged": self.unslotted_acknowledged,
            "requires_unslotted_acknowledgment": self.requires_unslotted_acknowledgment,
            "blocks_without_unslotted_acknowledgment": self.blocks_without_unslotted_acknowledgment,
        }


def _text(value: object) -> str:
    return str(value or "").strip()


def _chunked(values: list[str], size: int = 900):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _asset_by_tag(conn: sqlite3.Connection, asset_tag: str, context: AssetImportPreviewContext | None = None) -> sqlite3.Row | None:
    if context is not None:
        return context.assets_by_tag.get(asset_tag.upper())
    return conn.execute(
        """
        SELECT *
        FROM assets
        WHERE UPPER(asset_tag) = UPPER(?)
        LIMIT 1;
        """,
        (asset_tag,),
    ).fetchone()


def _asset_by_serial(conn: sqlite3.Connection, serial_number: str, context: AssetImportPreviewContext | None = None) -> sqlite3.Row | None:
    if not serial_number:
        return None
    if context is not None:
        return context.assets_by_serial.get(serial_number.upper())
    return conn.execute(
        """
        SELECT *
        FROM assets
        WHERE TRIM(COALESCE(serial_number, '')) <> ''
          AND UPPER(serial_number) = UPPER(?)
        LIMIT 1;
        """,
        (serial_number,),
    ).fetchone()


def _slot_for_row(
    conn: sqlite3.Connection,
    row: AssetImportAnalysisRow,
    context: AssetImportPreviewContext | None = None,
) -> tuple[sqlite3.Row | None, str | None]:
    if not row.case_identifier or not row.slot_identifier:
        return None, None
    try:
        slot_position = int(row.slot_identifier)
    except ValueError:
        return None, "slot_identifier must be numeric"
    if context is not None:
        slot = context.slots_by_case_position.get((row.case_identifier.upper(), slot_position))
        return slot, None

    slot = conn.execute(
        """
        SELECT id, case_name, slot_position, current_asset_tag
        FROM slots
        WHERE UPPER(case_name) = UPPER(?)
          AND slot_position = ?
        LIMIT 1;
        """,
        (row.case_identifier, slot_position),
    ).fetchone()
    return slot, None


def _slot_occupant(conn: sqlite3.Connection, slot_id: int, context: AssetImportPreviewContext | None = None) -> sqlite3.Row | None:
    if context is not None:
        return context.occupants_by_slot_id.get(slot_id)
    return conn.execute(
        """
        SELECT a.asset_tag
        FROM slot_occupancy so
        JOIN assets a ON a.id = so.asset_id
        WHERE so.slot_id = ?
        LIMIT 1;
        """,
        (slot_id,),
    ).fetchone()


def _same_slot(asset: sqlite3.Row | None, slot: sqlite3.Row | None) -> bool:
    if asset is None or slot is None or asset["home_slot_id"] is None:
        return False
    return int(asset["home_slot_id"]) == int(slot["id"])


def _slot_label(slot: sqlite3.Row) -> str:
    return f"{_text(slot['case_name'])} / {_text(slot['slot_position'])}"

def _row_slot_label(row: AssetImportAnalysisRow) -> str:
    return f"{row.case_identifier} / {row.slot_identifier}"


def _asset_home_slot_label(
    conn: sqlite3.Connection,
    asset: sqlite3.Row,
    context: AssetImportPreviewContext | None = None,
) -> str:
    if asset["home_slot_id"] is None:
        return "Unslotted"
    if context is not None:
        slot = context.home_slots_by_id.get(int(asset["home_slot_id"]))
        if slot is not None:
            return _slot_label(slot)
    slot = conn.execute(
        """
        SELECT case_name, slot_position
        FROM slots
        WHERE id = ?
        LIMIT 1;
        """,
        (asset["home_slot_id"],),
    ).fetchone()
    if slot is not None:
        return _slot_label(slot)
    fallback_case = _text(asset["case_number"])
    fallback_slot = _text(asset["slot_number"])
    if fallback_case or fallback_slot:
        return f"{fallback_case or 'Unknown case'} / {fallback_slot or 'Unknown slot'}"
    return f"home_slot_id {asset['home_slot_id']}"


def _field_changes(asset: sqlite3.Row, row: AssetImportAnalysisRow) -> tuple[AssetImportFieldChange, ...]:
    changes: list[AssetImportFieldChange] = []
    for row_field, asset_field, source_field in CHANGE_FIELDS:
        if not row.has_source_field(source_field):
            continue
        proposed = _text(getattr(row, row_field))
        if not proposed:
            continue
        current = _text(asset[asset_field]) if asset_field in asset.keys() else ""
        if current != proposed:
            changes.append(AssetImportFieldChange(field=asset_field, current=current, proposed=proposed))
    return tuple(changes)


def _preview_row(
    conn: sqlite3.Connection,
    row: AssetImportAnalysisRow,
    context: AssetImportPreviewContext | None = None,
) -> AssetImportPreviewRow:
    existing = _asset_by_tag(conn, row.asset_tag, context)
    serial_match = _asset_by_serial(conn, row.serial_number, context)
    if serial_match is not None and _text(serial_match["asset_tag"]).upper() != row.asset_tag.upper():
        return AssetImportPreviewRow(
            row_number=row.row_number,
            asset_tag=row.asset_tag,
            asset_identifier=row.asset_tag,
            category="identity_conflict",
            category_label=CATEGORY_LABELS["identity_conflict"],
            message=f"serial_number matches existing asset {serial_match['asset_tag']}",
            fields=("serial_number",),
        )

    storage_requested = row.storage_intent == "slotted"
    if existing is None and not storage_requested:
        return AssetImportPreviewRow(
            row_number=row.row_number,
            asset_tag=row.asset_tag,
            asset_identifier=row.asset_tag,
            category="unslotted_import",
            category_label=CATEGORY_LABELS["unslotted_import"],
            message="No storage case and slot supplied; row can continue as Unslotted after acknowledgment.",
            warnings=("Storage will remain Unslotted.",),
        )

    slot = None
    if storage_requested:
        slot, slot_error = _slot_for_row(conn, row, context)
        if slot_error is not None:
            return AssetImportPreviewRow(
                row_number=row.row_number,
                asset_tag=row.asset_tag,
                asset_identifier=row.asset_tag,
                category="slot_conflict_unslotted",
                category_label=CATEGORY_LABELS["slot_conflict_unslotted"],
                message=f"{slot_error}; row can continue as Unslotted after acknowledgment.",
                warnings=("Requested storage is unavailable.",),
                fields=("case_identifier", "slot_identifier"),
            )

        if slot is not None:
            occupant = _slot_occupant(conn, int(slot["id"]), context)
            legacy_current_asset_tag = _text(slot["current_asset_tag"])
            occupied_by_other = occupant is not None and _text(occupant["asset_tag"]).upper() != row.asset_tag.upper()
            legacy_occupied_by_other = legacy_current_asset_tag and legacy_current_asset_tag.upper() != row.asset_tag.upper()
            if occupied_by_other or legacy_occupied_by_other:
                occupant_tag = _text(occupant["asset_tag"]) if occupant is not None else legacy_current_asset_tag
                return AssetImportPreviewRow(
                    row_number=row.row_number,
                    asset_tag=row.asset_tag,
                    asset_identifier=row.asset_tag,
                    category="slot_conflict_unslotted",
                    category_label=CATEGORY_LABELS["slot_conflict_unslotted"],
                    message=f"Requested slot is occupied by {occupant_tag}; row can continue as Unslotted after acknowledgment.",
                    warnings=("Existing slot occupants are never displaced.",),
                    fields=("case_identifier", "slot_identifier"),
                )

    if existing is None:
        message = f"New {equipment_type_label(row.equipment_type)} asset with available storage."
        if storage_requested and slot is None:
            message = f"New {equipment_type_label(row.equipment_type)} asset with storage to create: {_row_slot_label(row)}."
        return AssetImportPreviewRow(
            row_number=row.row_number,
            asset_tag=row.asset_tag,
            asset_identifier=row.asset_tag,
            category="new_asset",
            category_label=CATEGORY_LABELS["new_asset"],
            message=message,
            warnings=("Missing storage will be created during commit.",) if storage_requested and slot is None else (),
        )

    changes = list(_field_changes(existing, row))
    if storage_requested and not _same_slot(existing, slot):
        changes.append(
            AssetImportFieldChange(
                field="home_slot",
                current=_asset_home_slot_label(conn, existing, context),
                proposed=_slot_label(slot) if slot is not None else f"{_row_slot_label(row)} (will be created)",
            )
        )
    if changes:
        message = "Existing asset has proposed field updates."
        if len(changes) == 1 and changes[0].field == "home_slot":
            message = "Existing asset would move to a different available home slot."
        return AssetImportPreviewRow(
            row_number=row.row_number,
            asset_tag=row.asset_tag,
            asset_identifier=row.asset_tag,
            category="proposed_update",
            category_label=CATEGORY_LABELS["proposed_update"],
            message=message,
            changed_fields=tuple(changes),
        )

    return AssetImportPreviewRow(
        row_number=row.row_number,
        asset_tag=row.asset_tag,
        asset_identifier=row.asset_tag,
        category="unchanged_exact_match",
        category_label=CATEGORY_LABELS["unchanged_exact_match"],
        message="Upload row matches current asset data exactly.",
    )

def _build_preview_context(conn: sqlite3.Connection, rows: tuple[AssetImportAnalysisRow, ...]) -> AssetImportPreviewContext:
    asset_tags = {row.asset_tag.upper() for row in rows if row.asset_tag}
    serial_numbers = {row.serial_number.upper() for row in rows if row.serial_number}
    assets_by_tag: dict[str, sqlite3.Row] = {}
    assets_by_serial: dict[str, sqlite3.Row] = {}
    home_slot_ids: set[int] = set()

    for chunk in _chunked(sorted(asset_tags)):
        placeholders = ", ".join("?" for _ in chunk)
        for asset in conn.execute(
            f"""
            SELECT *
            FROM assets
            WHERE asset_tag IN ({placeholders});
            """,
            chunk,
        ).fetchall():
            normalized_tag = _text(asset["asset_tag"]).upper()
            assets_by_tag.setdefault(normalized_tag, asset)
            if asset["home_slot_id"] is not None:
                home_slot_ids.add(int(asset["home_slot_id"]))

    unmatched_asset_tags = asset_tags - set(assets_by_tag)
    if unmatched_asset_tags or serial_numbers:
        for asset in conn.execute("SELECT * FROM assets;").fetchall():
            normalized_tag = _text(asset["asset_tag"]).upper()
            normalized_serial = _text(asset["serial_number"]).upper()
            if normalized_tag in unmatched_asset_tags:
                assets_by_tag.setdefault(normalized_tag, asset)
            if normalized_serial and normalized_serial in serial_numbers:
                assets_by_serial.setdefault(normalized_serial, asset)
            if (normalized_tag in unmatched_asset_tags or normalized_serial in serial_numbers) and asset["home_slot_id"] is not None:
                home_slot_ids.add(int(asset["home_slot_id"]))

    requested_cases: set[str] = set()
    requested_positions: set[int] = set()
    for row in rows:
        if not row.case_identifier or not row.slot_identifier:
            continue
        try:
            requested_positions.add(int(row.slot_identifier))
        except ValueError:
            continue
        requested_cases.add(row.case_identifier.upper())

    slots_by_case_position: dict[tuple[str, int], sqlite3.Row] = {}
    requested_slot_ids: set[int] = set()
    if requested_cases:
        for slot in conn.execute(
            """
            SELECT id, case_name, slot_position, current_asset_tag
            FROM slots
            """
        ).fetchall():
            normalized_case = str(slot["case_name"]).upper()
            if normalized_case not in requested_cases:
                continue
            slot_position = int(slot["slot_position"])
            if slot_position not in requested_positions:
                continue
            slots_by_case_position[(normalized_case, slot_position)] = slot
            requested_slot_ids.add(int(slot["id"]))

    occupants_by_slot_id: dict[int, sqlite3.Row] = {}
    for slot_id_chunk in _chunked([str(slot_id) for slot_id in sorted(requested_slot_ids)]):
        placeholders = ", ".join("?" for _ in slot_id_chunk)
        for occupant in conn.execute(
            f"""
            SELECT so.slot_id, a.asset_tag
            FROM slot_occupancy so
            JOIN assets a ON a.id = so.asset_id
            WHERE so.slot_id IN ({placeholders})
            ORDER BY so.slot_id;
            """,
            slot_id_chunk,
        ).fetchall():
            occupants_by_slot_id[int(occupant["slot_id"])] = occupant

    home_slots_by_id: dict[int, sqlite3.Row] = {}
    for slot_id_chunk in _chunked([str(slot_id) for slot_id in sorted(home_slot_ids)]):
        placeholders = ", ".join("?" for _ in slot_id_chunk)
        for slot in conn.execute(
            f"""
            SELECT id, case_name, slot_position
            FROM slots
            WHERE id IN ({placeholders})
            ORDER BY id;
            """,
            slot_id_chunk,
        ).fetchall():
            home_slots_by_id[int(slot["id"])] = slot

    return AssetImportPreviewContext(
        assets_by_tag=assets_by_tag,
        assets_by_serial=assets_by_serial,
        slots_by_case_position=slots_by_case_position,
        occupants_by_slot_id=occupants_by_slot_id,
        home_slots_by_id=home_slots_by_id,
    )


def build_asset_import_preview(
    conn: sqlite3.Connection,
    analysis: AssetImportAnalysis,
    *,
    unslotted_acknowledged: bool = False,
) -> AssetImportPreview:
    context = _build_preview_context(conn, analysis.rows)
    rows: list[AssetImportPreviewRow] = [
        AssetImportPreviewRow(
            row_number=issue.row_number,
            asset_tag="",
            asset_identifier=issue.asset_identifier,
            category="invalid_duplicate_upload_row",
            category_label=CATEGORY_LABELS["invalid_duplicate_upload_row"],
            message=issue.message,
            fields=issue.fields,
        )
        for issue in analysis.issues
    ]
    rows.extend(_preview_row(conn, row, context) for row in analysis.rows)
    rows.sort(key=lambda row: row.row_number)
    return AssetImportPreview(
        filename=analysis.filename,
        file_type=analysis.file_type,
        rows=tuple(rows),
        warnings=analysis.warnings,
        defaults=DEFAULTS_BEFORE_COMMIT,
        unslotted_acknowledged=unslotted_acknowledged,
    )
