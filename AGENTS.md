# AssetTrack — Codex Operating Rules

This file is the authoritative rule set.

If any other document conflicts with this file:
→ THIS FILE WINS

---

## 1. System Definition

AssetTrack is:

* offline-first
* append-only
* event-sourced

State is derived from immutable event history.

---

## 2. Non-Negotiable Invariants

These must NEVER be violated:

* events are append-only
* audit history is never modified or deleted
* state derives from event history
* custody state must reconcile with event log
* offline-first operation must remain intact
* SQLite persistence must not change without approval
* role enforcement must not be bypassable
* no hidden refactors
* no silent behavior changes

If a task risks any invariant:
→ STOP immediately

---

## 3. Execution Discipline

* one issue per branch
* branch: issue-X-Y-description
* commit: Issue X-Y: <plain English>
* explicit file staging only (no git add .)
* no scope expansion
* after an issue branch is merged and the user is back on main, delete the completed local branch:
  `git branch -D <branch-name>`
* do not delete active or unmerged branches unless the user confirms merge is complete
* default to one `git status --short --branch` at the end of branch setup
* ask for extra status checks only when useful: dirty files, failed branch switch, merge/rebase, pre-commit, or confusion

---

## 4. Change Classification

All work must be classified:

* Class 1 — UI / Presentation
* Class 2 — Logic / Behavior
* Class 3 — Schema
* Class 4 — Security
* Class 5 — Infrastructure

Classes 3–5 require explicit approval.

---

## 5. Required Workflow Seam

Must remain intact:

entry → prerequisite → queue → preview → commit

Rules:

* do not reorder
* do not shortcut
* preview requires valid queue
* entry must not redirect into preview

---

## 6. Local Settings And Delivery Metadata

* `app_settings` stores local runtime configuration
* receipt CC may be configured through local app settings
* local app settings must not become custody truth, receipt truth, event truth, or audit truth
* schema changes to app settings still require explicit migration approval
* receipt CC is delivery metadata only
* receipt CC is not custody truth, receipt truth, event truth, or audit truth
* receipt CC can be persisted as delivery metadata for sent receipts
* email delivery failure must not roll back custody or receipt creation

---

## 7. Manual Add Assets Navigation

* manual Add Assets launchers are hidden from normal navigation
* `/add-assets` remains available by direct URL
* import/upload paths remain intact
* do not re-add Manual Add Assets to normal navigation without explicit approval

---

## 8. Testing Discipline

For workflow changes:

1. docker compose up -d --build
2. use incognito browser

Smoke test:

* login
* enter workflow
* perform action
* verify queue/state
* verify preview
* verify commit
* verify queue clears

---

## 9. Output Requirements

For implementation:

1. focused diff summary
2. files changed
3. why it works
4. risks
5. tests run
6. manual verification

---

## 10. PR Descriptions

* Codex may provide raw exit-report material
* final PR descriptions should be prepared/reviewed by Chat from the Codex exit report
* PR descriptions must use the AssetTrack PR standard

---

## 11. Codex Prompt Size Discipline

Codex prompts must use the smallest safe instruction set for the issue.

Default prompt sizes:

* Tiny: recon, docs-only work, copy cleanup, and narrow UI presentation changes
* Small: narrow template changes or workflow presentation changes with focused tests
* Medium: behavior changes that affect workflow state, queue behavior, preview readiness, commit gating, or coordinated tests
* Large: avoid unless explicitly approved

Do not include full Constitution restatements in every Codex prompt.

Only expand prompts when the issue touches:

* schema or migrations
* security or authentication
* persistence
* custody/event behavior
* commit behavior
* receipt truth
* Docker/runtime behavior
* dependency changes

For normal Milestone 27 cleanup work, Codex prompts should be short task cards with:

* issue number and title
* classification
* branch name
* task
* scope
* non-goals
* required checks
* stop conditions
* expected exit report

Avoid repeating long invariant lists unless the issue can threaten those invariants.

The goal is safe execution with low token waste.

Codex prompts should still include:

* token-use estimate only: low, low-medium, medium, or high
* fix confidence
* no cost estimates

Rules:

* if token use is high, recommend splitting work into smaller GitHub issues first
* if fix confidence is below 99.1%, recommend splitting or narrowing the work first
* medium prompts may proceed only when scope is tight, invariants are protected, and verification is clear
* large prompts require explicit user approval before use

---

## 12. Stop Conditions

STOP if:

* schema change required (no approval)
* event semantics change required
* persistence behavior changes
* auth boundaries weaken
* scope expands
* requirement unclear

When stopping, report:

* what was attempted
* what is blocking
* smallest safe next step

---

## 13. Communication Style (Smart Brevity Constraint)

All communication must follow:

* Lead with the answer
* Remove non-essential detail
* Use scannable structure (bullets, short sections)
* Always answer: "why it matters"

This applies to:

* Issues
* PR descriptions
* Codex prompts
* Handoff summaries

Purpose:
Operators must understand state and next action in seconds under pressure.

---

## 14. Codex Context Rule

Codex source-of-truth hierarchy:

1. direct task instructions
2. AGENTS.md
3. docs/codex/PROJECT_MEMORY.md
4. docs/codex/CURRENT_STATE.md
5. repo state
6. Codex memories (recall only, never authority)

Do NOT:

* infer from other repos
* reuse patterns without confirmation

Codex memories are non-authoritative recall only.
Use memories to reduce repeated context setup, never to override:

* direct task instructions
* AGENTS.md
* docs/codex/PROJECT_MEMORY.md
* docs/codex/CURRENT_STATE.md
* current repo state

If unsure:
→ ASK before acting
---

## 15. Business Rule Consistency

When modifying an existing business rule, review the entire application for other workflows governed by that same rule.

Examples include:

* required vs optional fields
* asset identity
* holder identity
* import validation
* storage assignment
* Building, Room, Case, and Slot rules
* authorization
* navigation
* reports
* command-line utilities
* import scripts
* validators
* committers
* operator documentation

Requirements:

* implement business-rule changes consistently across equivalent workflows
* do not leave parallel UI, API, import, script, validator, or report paths enforcing different versions of the same rule without documented justification
* consistency review is part of the active issue scope when locations share the same governing business rule
* consistency review does not authorize unrelated cleanup, dependency additions, structural refactoring, or scope expansion

Examples:

* making Room optional requires reviewing every workflow that requires Room
* making Slot optional requires reviewing every workflow that requires Slot
* changing asset identity matching requires reviewing every asset import and reconciliation path
* changing import validation requires reviewing UI imports, command-line imports, shared validators, and related documentation
