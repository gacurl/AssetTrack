# Canonical Asset Import CSV Template

Use `asset_import_template.csv` with Admin -> Import Assets at `/admin/assets/import` for supported bulk asset imports.

The older Switch/Router CSV importer is not the Issue 31-2 workflow. Do not use it to verify storage provisioning, and do not treat it as evidence that Import Assets created case/slot storage.

## Workflow

1. Open Admin.
2. Open Import Assets at `/admin/assets/import`.
3. Choose a CSV or XLSX file.
4. Select Analyze Import.
5. Review the preview.
6. Open Technical Details and review row diagnostics.
7. Confirm the preview.
8. Commit the approved rows.
9. Open Cases and verify the case, slot, and occupancy results.

Analyze Import and Preview do not modify the database. They do not create cases, slots, assets, occupancy, or events.

Commit requires explicit confirmation. Approved safe rows commit atomically, and blocked rows do not modify state.

## Required Fields

- `equipment_type` is required.
- `asset_tag` or `barcode` is required.

Supported `equipment_type` values:

- Laptop
- Switch
- Router

## Template Columns

| Column | Use |
| --- | --- |
| `equipment_type` | Required asset type. Use Laptop, Switch, or Router. |
| `asset_tag` | AssetTrack asset tag when assigned. Required when `barcode` is blank. |
| `barcode` | Scannable custody barcode. Required when `asset_tag` is blank. |
| `serial_number` | Manufacturer serial number when available. |
| `manufacturer` | Equipment manufacturer. |
| `model` | Equipment model. |
| `model_code` | Model or catalog code when available. |
| `building_room` | Free-text building or room detail when available. |
| `case_identifier` | Optional storage case identifier. |
| `slot_identifier` | Optional storage slot identifier. |
| `notes_comments` | Short custody or storage note. |

## Storage

Storage fields are optional. Leave `case_identifier` and `slot_identifier` blank when storage is unknown or unavailable.

When both storage fields are present, the import treats them as requested home-slot storage. Preview shows whether the requested slot already exists, is occupied, or will be created.

In Technical Details, Preview explicitly identifies missing case/slot storage that will be created during commit.

Confirmed Commit creates missing slots, assigns the imported assets to those slots, and updates occupancy atomically. If any commit failure occurs, slots, assets, occupancy, and events from that batch roll back together.

Occupied slots remain protected. Import never displaces an existing slot occupant. Rows requesting occupied or unavailable storage may continue as Unslotted only when the admin acknowledges that behavior during preview.

Repeating the same unified import does not create duplicate slots or duplicate occupancy. Existing matching slots and unchanged exact-match assets are reused or left unchanged.

When both `case_identifier` and `slot_identifier` are blank, the row retains the acknowledged Unslotted behavior. The asset can be created in storage with no home slot only after the admin acknowledges Unslotted import during preview.

## After Commit Verification

Use the Cases view as the operator verification point after commit.

A successful import for rows that requested valid case and slot storage must show the new case and slot assignments in Cases. The Unslotted asset count must not increase for those rows.

## Unsupported Fields

AssetTrack import is for custody and storage data. Do not add CMDB, IP address, MAC address, VLAN, topology, monitoring, configuration, switch port, patching, network relationship, running configuration, or device configuration fields.

## BQ25 Shipping Manifest Normalization

Use the local normalizer to convert a BQ25 shipping manifest into an AssetTrack-compatible workbook before using Import Assets.

```bash
./.venv/bin/python -m scripts.normalize_bq25_shipping_manifest data/import/BQ25_shipping_manifest.xlsx data/import/BQ25_assettrack_import.xlsx
```

The normalizer writes a workbook with four sheets:

- `Asset Import`
- `Exceptions`
- `Case Summary`
- `Read Me`

Use the `Asset Import` sheet with Admin -> Import Assets at `/admin/assets/import`.

Normalization rules:

- Only Switch and Router rows are included.
- `Product` identifies Switch versus Router rows.
- `Barcode` becomes `asset_tag`.
- `Serial` or `Seriel` becomes `serial_number`.
- `Make\Model` is split into manufacturer and model; separate `Make` and `Model` columns are used when present.
- `Case #` is the storage source of truth.
- Repeated worksheet headers are ignored.
- Manifest row order within each case determines slot order: first device is slot `1`, second device is slot `2`, and so on.
- Case Summary infers capacity only from an explicit RU value in the case identifier, such as `4RU`, `6RU`, `8RU`, or `16RU`.
- Asset Import creates requested occupied positions only. Unused capacity shown in Case Summary is informational.
- Creating unused empty positions requires a separate approved AssetTrack workflow change.
- Source values are preserved. Questionable values are listed in `Exceptions` instead of being corrected.
- Duplicate normalized asset tags or serial numbers are excluded from `Asset Import` and listed in `Exceptions`.
- The script does not connect to or write the AssetTrack database.

Review `Exceptions` before importing. Known mixed-case serials, nearby model values, case-name variants, duplicate reference cases, and missing reference cases are intentionally flagged without being resolved.
