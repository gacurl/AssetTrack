# Workflow Model

AssetTrack uses one operator workflow seam:

`entry -> prerequisite selection -> scan queue -> preview -> commit`

## Custody Model Terms

- holder = custody actor
- location = transaction context (where issue/return happened, or where an asset is currently recorded)
- case/slot = storage logistics

Operator guidance:

- a holder can receive or return assets across multiple locations
- holder identity does not change when location changes
- location by itself does not create or transfer custody
- custody truth comes from committed event history

## Primary / Global Destinations

These pages begin or anchor work:

- `Dashboard`
- `Issue`
- `Return`
- `Holders`
- `Stage Assets` for admin intake
- `Admin Tools` for admin maintenance

## Workflow-Local Navigation

These links help complete the active workflow and should return the operator to it:

- holder search and holder selection during Issue
- current-location setup during Issue
- queue-local links such as jump-to-queue or jump-to-scan

## Contextual / Admin Surfaces

These pages support lookup, maintenance, or follow-up work but are not primary workflow entry points:

- reports
- receipts
- search
- admin drilldown pages such as users, imports, and reference data

## Transitional Preview States

These are review states between queue and commit:

- `/preview`
- `/issue/preview`
- `/return/preview`

Preview is a verification state, not a destination.

## Commit Gravity

Commit actions are terminal and high-gravity:

- they finalize the queued batch
- they append the resulting record
- they must not compete with ordinary navigation

Operators should not face multiple competing entry paths for the same workflow intent.
