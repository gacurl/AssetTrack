# Network Switch/Router Staging Template v1

## Purpose

Use `network_switch_router_staging_template_v1.csv` to prepare switch and router custody records for operator review.

This template is a planning and staging artifact only. It does not upload data, create assets, append events, or implement import behavior.

AssetTrack tracks equipment custody and storage. It is not a CMDB or network configuration system.

## Allowed Rows

- One physical switch or router per row.
- `equipment_type` must be `switch` or `router`.
- Use custody and storage details only.
- Leave a field blank when the value is unknown.
- Do not add columns without a separate review of the staging contract.

## Fields

| Field | Use |
| --- | --- |
| `asset_tag` | AssetTrack asset tag, when assigned. |
| `barcode` | Scannable custody barcode, when available. |
| `serial_number` | Manufacturer serial number, when available. |
| `equipment_type` | Required. Use `switch` or `router`. |
| `manufacturer` | Equipment manufacturer. |
| `model` | Equipment model. |
| `location_building` | Current storage location or building. |
| `case_identifier` | Storage case identifier, when applicable. |
| `slot_identifier` | Storage slot identifier, when applicable. |
| `notes_comments` | Short custody or storage note. Do not enter configuration data. |

## Required Identifiers

- Every row must include `equipment_type`.
- Every row must include at least one custody-safe identifier: `asset_tag`, `barcode`, or `serial_number`.
- Rows without a usable identifier must be corrected before import planning continues.

## Duplicate Handling

- Treat repeated `asset_tag`, `barcode`, or `serial_number` values as review items.
- Do not silently merge, overwrite, or discard duplicate rows.
- Resolve duplicates during staging review before any future import attempt.

## Rejected Fields

Do not add or record CMDB-like or network configuration fields, including:

- IP address
- MAC address
- VLAN
- switch port
- topology
- patching
- network relationships
- running configuration
- device configuration

## Review Before Import

Operators must review staged rows against this CSV and Markdown contract before any future import work proceeds.

Import behavior is intentionally out of scope. A later issue must define validation, preview, duplicate resolution, event behavior, and commit boundaries before runtime implementation begins.
