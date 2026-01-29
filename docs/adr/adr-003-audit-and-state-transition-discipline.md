# ADR 003 — Audit Logging & State Transition Discipline

**Date:** 2026-01-29  
**Status:** Accepted  
**Milestone:** 2 — Audit & State Discipline

---

## Context

AssetTrack must support reliable, auditable inventory operations in offline and semi-connected environments.

Audit records must reflect actual system state changes, not intent, and must be resistant to accidental omission or bypass.

A scattered or convention-based approach to audit logging would be fragile over time.

---

## Decision

1. **Audit logging is append-only**
   - All audit records are written via `INSERT` only.
   - No updates or deletes to audit history are permitted.

2. **Audit records are written only after successful commits**
   - Audit entries are created *after* database commits and guard checks.
   - Failed or no-op updates do not generate audit noise.

3. **State changes flow through explicit transition functions**
   - Intentional state changes must go through dedicated transition functions.
   - These functions apply the update and record the audit event together.

4. **CRUD helpers remain data-focused**
   - CRUD helpers may log events, but enforcement of state transitions lives in the transition layer.

---

## Consequences

- Guarantees audit completeness for state changes.
- Simplifies reasoning about asset history.
- Avoids premature workflow or policy engines.
- Establishes a clear pattern for future state transitions.

---

## Non-Goals

- No approval workflows
- No role-based enforcement
- No UI coupling
- No batch ingest logic (handled in Milestone 3)

---

## Related Issues

- Issue 2-1: Audit table bootstrap  
- Issue 2-2: Append-only audit writer  
- Issue 2-3: CRUD audit hooks  
- Issue 2-4: State transition choke point  
