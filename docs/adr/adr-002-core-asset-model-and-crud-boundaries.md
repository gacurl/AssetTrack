# ADR 002 — Core Asset Model & CRUD Boundaries

**Date:** 2026-01-26  
**Status:** Accepted  
**Milestone:** 1 — Core Asset Model

---

## Context

AssetTrack requires a clear, durable representation of physical assets that can be managed offline and reasoned about without a UI or network dependency.

Early design decisions needed to establish:
- what constitutes an “asset”
- how assets are created, updated, and retired
- what logic belongs in core data access vs higher-level behavior

The system must remain simple, inspectable, and resilient to future feature growth.

---

## Decision

1. **Assets are represented as rows in a single `assets` table**
   - Each asset has a stable `asset_tag` as its primary identifier.
   - Asset attributes are stored as explicit columns (not JSON blobs).

2. **CRUD operations are implemented as explicit helper functions**
   - Asset creation, update, and retirement are handled by named functions.
   - No implicit side effects beyond the requested operation.

3. **CRUD helpers focus on data correctness, not workflow**
   - CRUD functions validate allowed fields and apply changes.
   - They do not enforce business processes or approval rules.

4. **Retirement is a state change, not a deletion**
   - Assets are never deleted.
   - Retirement marks an asset as inactive while preserving history.

---

## Consequences

- Provides a stable foundation for auditability and state tracking.
- Keeps the data model understandable without a UI.
- Enables offline-first workflows.
- Defers policy, workflow, and batch logic to later milestones.

---

## Non-Goals

- No audit logging (introduced in Milestone 2)
- No batch ingest or review flows
- No user roles or permissions
- No UI concerns

---

## Related Issues

- Issue 1-1: Asset model definition  
- Issue 1-2: SQLite schema bootstrap  
- Issue 1-3: Core CRUD helpers  
- Issue 1-4: Asset retirement handling  
