# Issue 27-79 Stakeholder Feedback Triage

Source:
- JAR54 and TCM feedback from the 23 Apr TEM
- Design principle: make AssetTrack intuitive from an AD LOG/operator perspective

Purpose:
- preserve stakeholder feedback
- classify each theme into roadmap action
- keep traceability separate from implementation

## Classification Summary

### Already completed

#### dashboard clutter reduction
- classification: already completed
- reason: the dashboard was reduced to five primary cards and the old dominant At a Glance block was replaced with calmer, lower-noise structure.
- linked existing issue: Issue 27-78
- risk note: none beyond presentation; custody and workflow seams were preserved.

#### field-operational custody mapping
- classification: already completed
- reason: the dashboard now includes a read-only field-operational custody map, and the hierarchy is collapsible down to holder level.
- linked existing issue: Issue 27-78, Issue 27-91
- risk note: explicitly presentation-only; no custody state is created outside events.

#### issue workflow order
- classification: already completed
- reason: current Issue flow preserves prerequisite -> queue -> review -> commit and the recent 27-series work clarified queue control grouping, prerequisite visibility, blocked-item hierarchy, and post-add landing position.
- linked existing issue: Issue 27-85, Issue 27-87, Issue 27-88, Issue 27-89
- risk note: protected seam remains intact.

#### backup and restore process
- classification: already completed
- reason: the repo already has admin backup export, restore, recovery acknowledgment, restore history, operator docs, and test coverage around recovery mode.
- linked existing issue: existing restore and recovery work in current repo state
- risk note: high-safety surface; keep future changes separate from workflow UX cleanup.

#### patch/update cadence
- classification: already completed
- reason: patch/update cadence is already documented as an operational/security discipline.
- linked existing issue: Issue 27-82
- linked doc: `docs/security/patch-cadence.md`
- risk note: none to custody logic; this is release/security process.

### Closed as superseded

#### Smart Brevity UI overlay
- classification: closed as superseded
- reason: the useful part of this feedback is being handled through targeted workflow/dashboard simplification, not a separate app-wide overlay feature.
- linked existing issue: Issue 27-73, Issue 27-78
- recommended follow-on issue if needed: none unless a future cross-app writing/style audit is requested
- risk note: a literal overlay would be broad, ambiguous, and likely to expand scope without helping operators act faster.

### Existing issue

#### add-assets clarity
- classification: existing issue
- reason: this theme is already partially covered by workflow-surface compression and preview demotion work tied to the shared queue/review model.
- linked existing issue: Issue 27-73, Issue 27-84, Issue 27-86
- recommended follow-on issue if needed: a small add-assets-only cleanup issue after current milestone review
- risk note: keep add-assets on the same queue -> review discipline; do not merge it into Issue or Return behavior.

### New issue required

#### holder follow-up email
- classification: new issue required
- reason: the repo supports receipt email send/retry, but the feedback theme reads like operator-facing holder follow-up workflow refinement rather than core custody commit behavior.
- linked existing issue: none
- recommended follow-on issue: `Clarify holder follow-up email workflow and operator handoff`
- risk note: email delivery must remain downstream of committed receipt/custody state; do not make email a custody source of truth.

### Needs recon

#### equipment type simplification
- classification: needs recon
- reason: current equipment type handling spans asset creation, reporting, dashboard grouping, and legacy values. Simplifying it safely needs a bounded review before implementation.
- linked existing issue: none
- recommended follow-on issue: `Recon equipment type simplification for operator-facing workflows`
- risk note: can drift into schema, migration, or legacy-data normalization if not scoped carefully.

#### network device tracking
- classification: needs recon
- reason: current dashboard domain grouping gives a light read-only Network view, but fuller network-device tracking could easily drift toward topology or CMDB behavior.
- linked existing issue: Issue 27-78
- recommended follow-on issue: `Recon network device tracking boundaries without introducing CMDB behavior`
- risk note: high scope risk; must stay custody-oriented and offline-first.

#### case search and case validation
- classification: needs recon
- reason: the repo already has case drilldowns and slot/case state, but the feedback theme combines search, validation, and possibly workflow checks into one broad bucket.
- linked existing issue: none
- recommended follow-on issue: `Recon case search and validation needs across storage workflows`
- risk note: may touch slot assignment rules and workflow guardrails; keep custody/event semantics unchanged.

#### multi-location holder behavior
- classification: needs recon
- reason: this theme likely touches custody semantics, holder context, location meaning, and possibly issue/return workflow expectations.
- linked existing issue: none
- recommended follow-on issue: `Recon multi-location holder behavior without changing custody truth`
- risk note: high semantic risk; do not implement without explicit decisions on how location context relates to holder custody.

### Out of scope for current milestone

- none identified from the embedded list once the superseded and recon buckets are applied.

## Proposed Follow-On Issues

1. `Recon equipment type simplification for operator-facing workflows`
- purpose: reduce operator-facing type complexity without forcing schema or legacy-data decisions too early

2. `Recon network device tracking boundaries without introducing CMDB behavior`
- purpose: define the safe limit of network-oriented visibility inside an asset custody system

3. `Recon case search and validation needs across storage workflows`
- purpose: separate basic lookup needs from validation/guardrail changes

4. `Clarify holder follow-up email workflow and operator handoff`
- purpose: improve the operator-facing follow-up path after receipts exist, without making email part of custody truth

5. `Recon multi-location holder behavior without changing custody truth`
- purpose: determine whether this is a workflow, reporting, or data-model problem before any implementation issue is opened

## Bucket View

### Completed
- dashboard clutter reduction
- field-operational custody mapping
- issue workflow order
- backup and restore process
- patch/update cadence

### Superseded
- Smart Brevity UI overlay

### Existing issue
- add-assets clarity

### New issue required
- holder follow-up email

### Needs recon
- equipment type simplification
- network device tracking
- case search and case validation
- multi-location holder behavior

## Notes

- JAR54 feedback is preserved here as a planning source, not an implementation bucket.
- The safest interpretation of the feedback is operator-first clarity, not feature expansion.
- Any future issue touching custody semantics, schema, auth, persistence, or the queue -> review -> commit seam should be treated as higher-risk work.
