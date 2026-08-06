# Issue 31-13 Asset Location Map Decision

Classification: Class 2 - Logic / Behavior decision. Documentation only.

Why it matters: The Dashboard map currently mixes custody and storage orientation. Greg approved the hierarchy, labels, and current data sources so follow-on implementation can rename and reorder the map without adding schema, backfill, or a parallel source of truth.

## Decision

Rename the Dashboard `Custody Map` to `Asset Location Map`.

Use this hierarchy:

Asset Domain -> Mission Area -> Building -> Custody Holder -> Asset

The map remains read-only and continues to show active asset location orientation. It must continue excluding Disposed assets.

## Approved Source Fields

| Level | Approved source | Approved blank/fallback display | Notes |
| --- | --- | --- | --- |
| Asset Domain | Derived from `assets.equipment_type` | Existing unclassified fallback may remain unless Issue 31-14 changes display copy explicitly. | This replaces the `Operational Domain` label. The source remains derived logic, not a persisted field. |
| Mission Area | `holders.organization` | `No Mission Area Recorded` | This is a limitation: Mission Area currently comes from the holder organization, not from an independently assigned asset field. |
| Building | `assets.building` | `No Building Recorded` | Do not switch to the `buildings` reference table without a separate approved data-source decision. |
| Custody Holder | `holders.name`, then `assets.current_holder_id` | `No Custody Holder` | Stored assets without a holder should use this fallback instead of implying person custody. |
| Asset | `assets.asset_tag` | Existing asset-tag fallback may remain unless Issue 31-14 changes display copy explicitly. | Asset tags remain the visible asset identity. |

## Stored And Unslotted Assets

- Keep Stored assets visible in the Asset Location Map.
- Keep Unslotted assets visible.
- Explicitly label Unslotted assets as `Unslotted`.
- Continue excluding Disposed assets.

Why it matters: the current map already includes non-disposed Stored assets. Renaming the map avoids implying every asset in the tree is in person custody.

## No Schema Or Persistence Approval

This decision does not approve:

- schema changes;
- migrations;
- backfills;
- new persisted fields;
- new database relationships;
- dependency changes;
- event rewrites;
- audit rewrites;
- custody/event semantic changes.

Issues 31-14 and 31-15 must implement the approved display and hierarchy using existing data only.

## Implementation Constraints For Follow-On Issues

- Preserve the source-of-truth mapping in this document.
- Preserve the read-only Dashboard behavior.
- Preserve existing authentication and role behavior.
- Preserve exclusion of Disposed assets.
- Do not make Mission Area authoritative beyond `holders.organization`.
- Do not create a new Mission Area field, Asset Domain field, or location hierarchy table.
- Do not treat blank holder organization as an asset-level Mission Area fact.
- Do not hide Stored or Unslotted assets as part of the rename/reorder work.
- Do not change slot, custody, event, audit, Issue, Return, or storage assignment behavior.

## Non-Decisions

- This document does not decide a future independent Mission Area model.
- This document does not decide whether Asset Domain should become editable reference data.
- This document does not decide whether Building should later be sourced from the reference `buildings` table.
- This document does not implement Issues 31-14 or 31-15.
- This document changes no application code, templates, tests, schema, data, dependencies, routes, authorization, persistence, events, custody behavior, or storage behavior.
