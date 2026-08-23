# AssetTrack Release Notes

Version: `v2.0.0`

## Release summary

AssetTrack `v2.0.0` is the current field-ready release of the offline-first asset custody system. This release packages the current workflow, deployment path, and operational guidance into a clean release baseline for evaluation and controlled use.

The visible application version, this release-notes version, and the Git tag for
the deployed release must match.

## Key features

- Offline-first local operation with no required external services
- Login-protected operator workflow
- Admin-only user management and asset management screens
- Add asset workflow for creating new tracked equipment
- Holder management for assigning custody to people or organizations
- Issue workflow with preview-before-commit discipline
- Return workflow with preview-before-commit discipline
- Dashboard views for inventory, custody, slots, holders, and cases

## Audit-safe event model

AssetTrack is designed around audit discipline:

- Events are append-only
- Audit history is never edited or deleted in place
- System state is derived from recorded events
- Queue commits are atomic and fail closed when validation blocks a transition
- Custody and slot state must reconcile with the event history

## Offline-first architecture

AssetTrack is intended for environments where reliability and local operation matter more than external integration.

- The application runs locally in Docker
- SQLite is used for persistence
- The active database path inside the container is `/app/data/assettrack.db`
- Normal operation does not require internet access once the image is built

## Docker deployment

The supported deployment path for this MVP release is Docker Compose:

```bash
docker compose up -d --build
```

The application listens on port `8000` by default:

- `http://localhost:8000`

## Security posture

This release includes a clean Trivy filesystem release scan for:

- vulnerabilities
- secrets
- Dockerfile misconfigurations

See the release security summary here:

- [security-report.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/release/security-report.md)

See the detailed Trivy readout here:

- [trivy-readable.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/security/trivy-readable.md)

## Operational intent

This MVP is suitable for controlled field distribution where operators need:

- a predictable local workflow
- durable SQLite-backed persistence
- clear admin/operator separation
- an auditable issue and return process

This release does not change the system invariants:

- no schema changes
- no hidden refactors
- no silent behavior changes
