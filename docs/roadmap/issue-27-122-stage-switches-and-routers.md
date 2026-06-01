# Issue 27-122 Stage Switches and Routers

## Purpose

Add repo-tracked planning artifacts for future switch/router custody staging.

This issue defines the staging contract before any import behavior is implemented.

## Artifacts

- `docs/fixtures/imports/network/network_switch_router_staging_template_v1.csv`
- `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md`
- `docs/roadmap/issue-27-123-import-staged-switches-and-routers.md`

## Boundary

AssetTrack tracks equipment custody and storage. It must not become a CMDB or network configuration system.

The staging template allows custody-safe identifiers, equipment description, storage location, case/slot placement, and short notes. It excludes IP addresses, MAC addresses, VLANs, switch ports, topology, patching, network relationships, running configuration, and device configuration.

## Why It Matters

Operators need a reviewable, diff-friendly CSV contract before switch/router rows are considered for import. Defining that contract first keeps later implementation bounded to custody and storage.

## Non-Goals

- No import code
- No routes
- No model, schema, or migration changes
- No event or custody logic changes
- No auth or role changes
- No persistence changes
- No XLSX tracking

## Completion Check

- The CSV template is tracked and human-readable.
- The Markdown spec defines allowed rows, identifiers, duplicate review, rejected CMDB-like fields, and review-before-import expectations.
- Future import planning is separated into Issue 27-123.
