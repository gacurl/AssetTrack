# Issue 27-26: Recon Multi-Location Holder Support

## Conclusion

AssetTrack holders are global custody actors. They are not location-scoped
records.

The current model already allows one holder to receive or return assets across
multiple transaction locations. Issue-time location choices may be
operationally filtered by the holder's organization-to-building mappings, but
that filter does not make the holder belong to one building.

Keep the current boundary:

`holder = custody actor`, `location = transaction context`, and
`case/slot = storage logistics`.

Do not add location-scoped holders as a small implementation change. Any request
for holder-location membership needs a separate schema and migration planning
issue first.

## Current Data Model

### Holders

The `holders` table stores:

- holder identity and type
- one optional `organization_id`
- active or inactive status
- identifier, email, and contact information

It does not store:

- `building_id`
- room
- location membership
- a holder-to-building join table

Holder create and edit flows require one organization selection. They do not
ask for a building or room.

### Locations and Storage

Location and storage are represented outside the holder record:

- `assets.building`, `assets.room`, and `assets.building_room` record current
  asset location context.
- `buildings` stores approved building names.
- `organization_buildings` maps an organization to one or more approved
  buildings.
- cases and slots represent storage logistics.

This means one organization, and therefore a holder assigned to that
organization, can operate across multiple mapped buildings without duplicating
the holder.

## Current Workflow Behavior

### Holder Directory and Selection

Holder search and listing are global. They can be filtered by active or inactive
status, and assignment selection hides inactive holders. There is no building or
room filter in the holder directory.

The Issue workflow stores one selected global holder ID in the operator session.
The selected holder remains a custody prerequisite before Issue queue work.

### Issue Location

The Issue workflow separately asks for the current transaction building and
room.

When the selected holder has an organization with mapped buildings, Issue limits
the building choices to those mapped buildings. A commit using a different
building is rejected. When no organization-to-building mappings exist, the
current code falls back to the approved building list.

At commit, the issued asset receives:

- `location_type = IN_CUSTODY`
- the selected `current_holder_id`
- the selected building, room, and combined `building_room`

The appended Issue event records the holder and transaction location context.

### Return

Return does not ask the operator to select a holder or transaction building. It
validates each queued asset's current `IN_CUSTODY` state and home slot, derives
the prior holder from the asset, appends Return history, clears
`current_holder_id`, and restores storage state.

A Return batch may contain assets from more than one holder. In that case, the
receipt keeps per-asset prior holder facts and does not claim one batch-level
holder.

### Receipts

Receipt snapshots keep holder identity and location context separate:

- Issue receipts snapshot the selected holder and Issue transaction location.
- Return receipts snapshot prior holder facts from stored event history.
- Receipt delivery uses the stored receipt snapshot.

Location does not redefine holder identity, and email delivery does not define
custody truth.

## Where the UI Can Be Misread

The Issue building dropdown is constrained by the selected holder's
organization mappings when mappings exist. An operator could read this as the
holder being assigned to one location.

That is not the data model:

- the holder belongs to one organization, not one building
- the organization may map to multiple buildings
- the selected building is transaction context for the Issue action
- the holder directory remains global

The existing operator workflow model already states the intended meaning:
holder identity does not change when location changes.

## Risks of Adding Location-Scoped Holders

Making holders location-scoped would affect more than filtering:

- Existing holder identity could fragment into duplicate records by building.
- Global email uniqueness rules would need an explicit decision.
- Issue selection, session holder state, and organization-to-building checks
  could conflict or duplicate each other.
- Return batches with assets from multiple holders or locations would need
  careful display and receipt rules.
- Dashboard holder counts, reports, imports, and drilldowns would need a
  consistent scope definition.
- Receipt snapshots and historical events must remain readable without
  rewriting prior history.
- A schema change would require an explicit migration and backfill plan for
  existing holders.

Do not infer a location-scoped holder model from the current Issue dropdown.

## Smallest Safe Future Path

No runtime change is needed to support a global holder receiving or returning
assets across multiple approved transaction locations. Current behavior already
supports that case.

If operators only need easier discovery, start with a separate Class 1 or
Class 2 issue for read-only holder filtering. That issue must define whether the
filter means:

- holder organization mapped to a building
- assets currently held at a building
- historical holder activity at a building

These are different questions and must not be treated as interchangeable.

If operators need persistent holder-to-location membership, open a schema
planning issue before implementation. Do not add a building column directly to
`holders` without deciding whether membership is one-to-one or many-to-many and
how existing records will be migrated.

## Proposed Follow-On Issues

Open only if operator need is confirmed.

### Optional: Define read-only holder location filtering semantics

Document which operational question a holder location filter should answer.
Keep holder identity global. Specify the affected directory, report, or
drilldown surfaces and the expected behavior when a holder operates across
multiple buildings. Do not change schema or custody event semantics.

### Optional: Plan holder-to-location membership schema and migration

Use only if AssetTrack needs explicit persistent holder-location membership
beyond organization-to-building mappings and asset transaction history. Decide
one-to-one versus many-to-many membership, migration rules for existing
holders, import impact, UI impact, receipt display impact, and event-history
compatibility before implementation.

## Repo Evidence Reviewed

- `assettrack/db.py`
- `assettrack/holders.py`
- `assettrack/intake/app.py`
- `assettrack/intake/templates/holder_new.html`
- `assettrack/intake/templates/holder_edit.html`
- `assettrack/intake/templates/holders_search.html`
- `tests/test_holders.py`
- `tests/test_holder_creation_viability.py`
- `tests/test_issue_holder_prerequisite.py`
- `tests/test_issue_location_wiring.py`
- `tests/test_return_batch.py`
- `tests/test_receipt_detail.py`
- `docs/operator/workflow-model.md`

## Scope Confirmation

This recon does not change runtime behavior, routes, templates, tests, schema,
persistence, custody truth, receipt truth, audit history, or event history.
