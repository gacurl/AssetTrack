# Issue 27-10 Recon: Asset Search Functionality

## Current Behavior Summary

Asset search is a read-only operator/admin lookup page at `GET /assets/search`.

Why it matters: the page helps an operator quickly find a known machine by tag
or serial number, but it currently answers only the current `assets` row view of
custody/storage. It does not show the receipt or event proof behind the last
movement.

Reviewed:

- `assettrack/intake/app.py`
- `assettrack/intake/templates/asset_search.html`
- `assettrack/intake/templates/report_readonly.html`
- `assettrack/intake/templates/receipts_list.html`
- `tests/test_asset_search_ui.py`
- `tests/test_basic_auth_guard.py`
- `tests/test_admin_system_health.py`
- `docs/models/asset.md`
- `docs/operator/issue-27-68-workflow-cognition-recon.md`
- `docs/recon/issue-27-162-reports-label-decision.md`

Current route behavior:

- Requires login through `@require_login`.
- Preserves the existing inactivity-lock redirect behavior.
- Accepts optional `return_to`, sanitized through `_safe_local_return_to`.
- Reads only from the local SQLite database.
- Uses `_lookup_asset_for_verification()` for lookup.
- Renders results in `asset_search.html`.
- Does not mutate assets, holders, slots, events, receipts, queues, previews, or
  commits.

## Search Inputs Currently Supported

The page supports these GET query inputs:

| Input | Behavior |
| --- | --- |
| `asset_tag` | Trimmed and uppercased before lookup. Partial matching uses `LIKE '%value%'`. Exact matches sort first. |
| `serial_number` | Trimmed before lookup. Partial matching uses `LIKE '%value%'` against non-empty serial numbers. Exact matches sort first. |
| both fields | Both filters are applied. The UI labels this as asset-tag lookup, but the SQL narrows results by both asset tag and serial number. |
| no fields | No search is performed; the page shows the empty search form. |
| `return_to` | Safe local return context only. Currently used for `Back to Report`. Unsafe external values are ignored. |

Result limits:

- Asset-tag lookup returns up to 25 matches.
- Serial-number lookup returns up to 25 matches.
- Combined lookup returns up to 25 matches.

Access:

- Operators and admins can use asset search.
- Admins get an asset-tag link to the admin edit page.
- Operators see asset tags as read-only text.

## Search Result Fields Currently Shown

The visible result table currently shows:

| Field | Source |
| --- | --- |
| Asset tag | `assets.asset_tag` |
| Serial number | `assets.serial_number` |
| Current state | `assets.location_type`, rendered through `asset_state_label()` |
| Current holder | `holders.name` / `holders.organization` joined from `assets.current_holder_id` |
| Home case | `slots.case_name` joined from `assets.home_slot_id` |
| Home slot | `slots.slot_position` joined from `assets.home_slot_id` |

State labels currently include:

- `STORAGE` -> `In storage`
- `IN_CUSTODY` -> `In custody`
- `DISPOSED` / `RETIRED` -> `RETIRED - Not in service`
- empty value -> `Unknown`
- other values -> title-cased location type

The result table does not show:

- building/room or actual field location
- current slot occupancy
- last movement event ID
- last movement event type/date
- receipt ID, receipt key, or receipt link
- receipt delivery status
- accountability status
- condition
- blocked/missing exception status beyond whatever is encoded in
  `location_type`
- mismatch indicators between `location_type`, holder, home slot, and slot
  occupancy

## Operator Questions Answered

| Question | Current answer |
| --- | --- |
| Where is this machine? | Partially. Search shows `In storage`, `In custody`, retired/not in service, and home case/slot. It does not show building/room, actual occupied slot, or last observed location. |
| Who has it? | Partially. If `assets.current_holder_id` points to a holder, the holder name/organization is shown. |
| Is it out with a holder? | Mostly. `Current state = In custody` plus current holder indicates it is out. If state and holder data disagree, the page does not flag the mismatch. |
| Is it stored in a case or slot? | Partially. Home case and home slot are shown. The page does not prove current physical slot occupancy. |
| Is it retired? | Yes, for `DISPOSED` / `RETIRED`, with a terminal visual label. |

## Operator Questions Not Answered

| Question | Gap |
| --- | --- |
| What receipt proves the last movement? | Not answered. Asset search does not join `receipt_queue` or link to receipt detail. Operators must separately use receipt search by asset tag. |
| What event proves the last movement? | Not answered. Asset search does not show the latest active event ID, event type, event date, holder, or event-to-receipt linkage. |
| Is it missing? | Not directly answered. There is no visible missing/accountability exception field in asset search. |
| Is it blocked? | Not directly answered. Search does not surface blocking conditions or workflow eligibility. |
| Is it not where expected? | Not directly answered. Search shows home slot but does not compare current custody/storage state against slot occupancy, building/room, or expected case placement. |
| Is the holder/current state data inconsistent? | Not answered. Search displays fields but does not call out impossible or suspicious combinations. |
| What was the last movement path? | Not answered. No from/to state, from/to holder, or from/to storage context is shown. |

## Risks

- Operators may treat `Home case` / `Home slot` as current physical location even
  when an asset is in custody.
- Operators can find the machine but still need a second workflow to find the
  receipt proof.
- Partial matches are useful, but broad searches may return up to 25 rows
  without proof context, which can slow teardown triage.
- Serial numbers are best-effort identifiers and not guaranteed unique by the
  asset model.
- Search currently reads current state only; it is not an audit-history view.
- Adding proof data incorrectly could weaken custody semantics if receipt or
  event data is treated as mutable search metadata instead of append-only truth.

## Recommended Smallest Safe Implementation Follow-Up

Create a follow-up implementation issue to add a read-only "Last movement proof"
column or compact detail line to asset search results.

Proposed scope:

- Class 2 - Logic / Behavior.
- Keep `GET /assets/search` as the same route.
- Keep current search inputs unchanged.
- Keep current result columns unchanged unless adding one read-only proof column.
- Read the latest non-superseded `asset_events` row per result asset.
- If that event is tied to a receipt through `receipt_queue.source_event_ids_json`,
  show a receipt detail link with receipt key or receipt ID.
- Show the event ID, event type, and event date when no receipt is available.
- Do not update assets, holders, slots, events, receipts, queues, previews, or
  commits.
- Do not change schema.
- Do not add dependencies.
- Do not change receipt creation, receipt snapshots, receipt PDFs, or receipt
  delivery behavior.
- Add focused tests in `tests/test_asset_search_ui.py`.

Suggested operator-facing wording:

```text
Last proof: Receipt issue:12-13, ISSUE, Apr 3 2026
```

or when no receipt exists:

```text
Last proof: Event 42, RETURN, Apr 4 2026
```

Why this is the smallest safe follow-up:

- It keeps asset search as a read-only lookup.
- It does not redefine custody truth.
- It uses existing append-only events and existing receipt rows as proof.
- It avoids schema, route, workflow, queue, preview, commit, SMTP, and Receipt CC
  changes.
- It directly answers the deployment question: "what receipt or event proves the
  last movement?"

Do not include missing/blocked/not-where-expected detection in the same
follow-up unless repo evidence shows those states already have stable,
read-only fields. That should be a separate recon or implementation issue.

## Explicit Non-Changes Confirmation

This recon did not change:

- app behavior
- schema or migrations
- routes
- permissions
- custody logic
- event behavior
- audit history
- receipt behavior
- receipt delivery
- SMTP configuration
- Receipt CC behavior
- Issue workflow
- Return workflow
- queue behavior
- preview behavior
- commit behavior
- tests
- dependencies
