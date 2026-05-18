# AssetTrack — Codex Operating Rules

This file is the authoritative rule set.

If any other document conflicts with this file:
→ THIS FILE WINS

---

## 1. System Definition

AssetTrack is:

- offline-first
- append-only
- event-sourced

State is derived from immutable event history.

---

## 2. Non-Negotiable Invariants

These must NEVER be violated:

- events are append-only
- audit history is never modified or deleted
- state derives from event history
- custody state must reconcile with event log
- offline-first operation must remain intact
- SQLite persistence must not change without approval
- role enforcement must not be bypassable
- no hidden refactors
- no silent behavior changes

If a task risks any invariant:
→ STOP immediately

---

## 3. Execution Discipline

- one issue per branch
- branch: issue-X-Y-description
- commit: Issue X-Y: <plain English>
- explicit file staging only (no git add .)
- no scope expansion

---

## 4. Change Classification

All work must be classified:

- Class 1 — UI / Presentation
- Class 2 — Logic / Behavior
- Class 3 — Schema
- Class 4 — Security
- Class 5 — Infrastructure

Classes 3–5 require explicit approval.

---

## 5. Required Workflow Seam

Must remain intact:

entry → prerequisite → queue → preview → commit

Rules:

- do not reorder
- do not shortcut
- preview requires valid queue
- entry must not redirect into preview

---

## 6. Testing Discipline

For workflow changes:

1. docker compose up -d --build
2. use incognito browser

Smoke test:

- login
- enter workflow
- perform action
- verify queue/state
- verify preview
- verify commit
- verify queue clears

---

## 7. Output Requirements

For implementation:

1. focused diff summary
2. files changed
3. why it works
4. risks
5. tests run
6. manual verification

---

## 8. Stop Conditions

STOP if:

- schema change required (no approval)
- event semantics change required
- persistence behavior changes
- auth boundaries weaken
- scope expands
- requirement unclear

When stopping, report:

- what was attempted
- what is blocking
- smallest safe next step

---

## 9. Communication Style (Smart Brevity Constraint)

All communication must follow:

- Lead with the answer
- Remove non-essential detail
- Use scannable structure (bullets, short sections)
- Always answer: "why it matters"

This applies to:
- Issues
- PR descriptions
- Codex prompts
- Handoff summaries

Purpose:
Operators must understand state and next action in seconds under pressure.

---

## 10. Codex Context Rule

Codex must ONLY rely on:

- AGENTS.md
- docs/codex/PROJECT_MEMORY.md
- docs/codex/CURRENT_STATE.md

Do NOT:

- infer from other repos
- reuse patterns without confirmation

If unsure:
→ ASK before acting