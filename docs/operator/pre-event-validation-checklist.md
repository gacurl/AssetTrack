# Pre-Event Validation Checklist

Use this checklist when planning or reviewing any workflow that can append custody
or audit history.

Validation happens before the append boundary. Validation may block a commit, but
it must not create, edit, delete, or reinterpret event history. A failed or
cancelled action must leave custody truth unchanged.

AssetTrack keeps the operator workflow seam:

`entry -> prerequisite selection -> scan queue -> preview -> commit`

## 1. Confirm the Actor

- [ ] Require an authenticated, active user.
- [ ] Confirm the user's role is allowed to perform the requested action.
- [ ] Reject the action if authentication, session state, or authorization is
      missing or invalid.
- [ ] Do not treat a displayed username or client-provided value as proof of the
      acting user.

## 2. Confirm the Workflow Intent

- [ ] Identify the requested transition before validating the batch, such as
      issue, return, or an approved asset intake action.
- [ ] Keep each workflow on its approved entry path.
- [ ] Do not skip prerequisite selection, queue review, or preview.
- [ ] Reject unsupported or ambiguous transition intent.

## 3. Confirm Required Context

- [ ] Require the approved holder when the transition changes holder custody.
- [ ] Require the approved transaction location when the workflow needs it.
- [ ] Keep holder, location, and storage meaning separate:
      `holder = custody actor`, `location = transaction context`, and
      `case/slot = storage logistics`.
- [ ] Validate any required case or slot against existing approved storage
      records.
- [ ] Reject missing, stale, or unsupported context before commit.

## 4. Confirm Asset Eligibility

- [ ] Resolve every queued asset using its approved custody identifier.
- [ ] Reject missing, unknown, duplicate, retired, or otherwise ineligible
      assets.
- [ ] Confirm each asset's current derived state allows the requested
      transition.
- [ ] Confirm storage state is compatible with the requested transition when
      case or slot placement is involved.
- [ ] Reject the full batch if any asset would produce an invalid or
      unreconciled result.

## 5. Confirm Queue Validity

- [ ] Require a non-empty queue for batch workflows.
- [ ] Confirm the queue belongs to the selected workflow intent.
- [ ] Confirm prerequisites still match the context used to build the queue.
- [ ] Detect duplicate or stale queued items.
- [ ] Re-run required eligibility checks before preview and again before
      commit.

## 6. Confirm Preview

- [ ] Show the operator what will change before any event is appended.
- [ ] Show the selected holder, location, storage context, and affected assets
      when relevant.
- [ ] Keep blocked items visible and prevent commit while blockers remain.
- [ ] Require an explicit commit action from the preview state.
- [ ] Treat preview as read-only verification, not as event history.

## 7. Protect the Append Boundary

- [ ] Append events only after all required validation passes.
- [ ] Keep the event write and the related derived-state update inside the
      approved atomic commit path.
- [ ] Use inserts for append-only custody and audit history.
- [ ] Do not update or delete prior event or audit records.
- [ ] Fail closed: if the transaction fails, do not leave partial state,
      partial history, or a cleared queue.
- [ ] Clear the queue only after a successful commit or an explicit operator
      clear action.

## 8. Confirm Local Persistence

- [ ] Use the existing local SQLite persistence path.
- [ ] Do not add remote persistence or require network access for custody
      commit.
- [ ] Preserve container-restart durability expectations.
- [ ] Stop and require explicit migration planning before any schema change.

## 9. Reconcile After Commit

- [ ] Confirm the appended event history matches the committed action.
- [ ] Confirm the current derived custody state matches the event log.
- [ ] Confirm holder assignment, location, and case/slot storage state remain
      internally consistent where relevant.
- [ ] Confirm the queue clears after successful commit.
- [ ] Surface a clear operator error and investigate if reconciliation fails.

## 10. Keep Delivery Separate

- [ ] Create receipt truth only from the approved committed workflow path.
- [ ] Treat receipt email, receipt resend, and holder follow-up email as
      delivery or communication actions only.
- [ ] Do not make email delivery success a prerequisite for custody truth.
- [ ] Do not let email actions append custody events, rewrite audit history, or
      modify receipt snapshots.

## Future Issue Review

Before approving an implementation issue that can append events, record:

- which workflow intent is affected
- which prerequisites and eligibility rules apply
- where preview occurs
- where the atomic append boundary occurs
- how post-commit reconciliation is verified
- whether receipt or email delivery is involved and how it stays separate
- whether schema, persistence, authorization, or event semantics would change

Stop and request a separate approved plan if the implementation requires a
schema migration, new persistence semantics, changed role boundaries, or changed
event-history semantics.
