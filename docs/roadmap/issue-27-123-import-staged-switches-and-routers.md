# Issue 27-123 Import Staged Switches and Routers

## Status

Implementation is bounded to reviewed switch/router staging rows that comply with:

- `docs/legacy/network_switch_router_staging_template_v1.csv`
- `docs/legacy/network_switch_router_staging_template_v1.md`

## Purpose

Import reviewed switch/router custody staging rows through the existing append-only asset ingest path.

## Required Review Before Import

- Confirm rows contain custody and storage data only.
- Confirm each row has `equipment_type` and an `asset_tag` or fallback `barcode`.
- Resolve duplicate identifiers explicitly.
- Reject CMDB-like and network configuration columns.
- Reject serial-only rows.
- Map case and numeric slot identifiers to an existing slot when slot assignment is requested.

## Protected Boundary

The import must preserve:

- append-only events
- immutable audit history
- state derived from event history
- custody reconciliation with the event log
- offline-first operation
- local SQLite persistence
- role enforcement
- the `entry -> prerequisite -> queue -> preview -> commit` seam

## Non-Goals

- No routes
- No schema or migration changes
- No event payload or custody behavior changes
- No auth, role, or persistence changes
- No CMDB or network configuration behavior

## Stop Conditions

Stop and open a separately approved plan if implementation requires schema changes, migration work, event semantic changes, persistence changes, role changes, or CMDB-like data.
