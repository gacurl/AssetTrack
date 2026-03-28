# AssetTrack Codex Instructions

AssetTrack is an offline-first, append-only, event-sourced asset custody system.

## Non-negotiable invariants

- Events are append-only.
- Audit history is never modified or deleted.
- System state derives from event history.
- Asset custody state must reconcile with the event log.
- Offline-first operation must remain intact.
- SQLite persistence must not change unless explicitly approved.
- Role enforcement must not be bypassable.
- No hidden refactors.
- No silent behavior changes.

## Workflow rules

- One GitHub issue per branch.
- Branch names should follow: `issue-X-Y-short-description`
- Commit messages should follow: `Issue X-Y: <plain English>`
- Stay within issue scope.
- Do not expand scope without explicit instruction.
- Stop if a change risks invariants.
- Prefer the smallest safe change.
- No dependency additions without approval.
- No schema or migration changes without explicit approval.
- No event payload/history semantic changes without explicit approval.

## Required workflow seam

Keep this workflow intact:

`entry page → prerequisite selection → scan queue → preview → commit`

Do not shortcut or reorder that seam unless the issue explicitly requires it.

## Change discipline

Classify changes before implementation:

- Class 1 — UI / Presentation
- Class 2 — Logic / Behavior
- Class 3 — Data Model / Schema
- Class 4 — Security / Authentication
- Class 5 — Infrastructure / Persistence

Classes 3 through 5 require explicit approval before implementation.

## Testing discipline

When changing workflow behavior:

1. Rebuild with Docker:
   `docker compose up -d --build`
2. Use an incognito browser session.
3. Perform a manual smoke test through the real operator path.

Minimum smoke test:
- login
- enter workflow
- perform operator action
- verify queue/state change
- verify preview
- verify commit
- verify queue clears

CI success alone is not enough.

## Output format

For implementation tasks, return:

1. Focused diff summary
2. Files changed
3. Why it works
4. Risks / edge cases
5. Tests run
6. Manual verification steps
7. Commit message only if implementation is complete

## Stop conditions

Stop immediately if:

- schema or migration is required without approval
- event payload/history semantics must change without approval
- persistence behavior changes
- auth boundaries weaken
- requirement is ambiguous in a way that risks audit integrity
- scope expands beyond the issue

When stopping, report:

- what was attempted
- what is blocking progress
- the smallest safe next step

## Preferred style

- Use plain language.
- Explain simply and explain why.
- No fluff.
- Favor operator clarity over cleverness.
- Prefer focused diffs over broad rewrites.