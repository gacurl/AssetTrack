# Issue 27-123 Import Staged Switches and Routers

## Status

Future planning boundary only. Do not implement import behavior until staged switch/router rows have been reviewed against:

- `docs/fixtures/imports/network/network_switch_router_staging_template_v1.csv`
- `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md`

## Purpose

Plan a later, separately approved path for importing reviewed switch/router custody staging rows.

## Required Review Before Implementation

- Confirm rows contain custody and storage data only.
- Confirm each row has `equipment_type` and at least one supported identifier.
- Resolve duplicate identifiers explicitly.
- Reject CMDB-like and network configuration columns.
- Define validation, preview, and commit behavior before runtime work begins.

## Protected Boundary

Any future implementation must preserve:

- append-only events
- immutable audit history
- state derived from event history
- custody reconciliation with the event log
- offline-first operation
- local SQLite persistence
- role enforcement
- the `entry -> prerequisite -> queue -> preview -> commit` seam

## Non-Goals For This Planning Doc

- No import implementation
- No routes
- No schema or migration changes
- No event payload or custody behavior changes
- No auth, role, or persistence changes
- No CMDB or network configuration behavior

## Stop Conditions

Stop and open a separately approved plan if implementation requires schema changes, migration work, event semantic changes, persistence changes, role changes, or CMDB-like data.
