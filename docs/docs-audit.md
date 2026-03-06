# Documentation Reference Audit (Issue 20-1)

## Purpose
This audit maps repository documentation by in-repo reference status and usage class, using static search only.

## Audit Scope
- `README.md`
- `docs/**/*.md`
- repository references from `README.md`, `docs/`, `assettrack/`, `tests/`, `scripts/`

## Commands Used
- `rg --files -g '*.md' README.md docs`
- `find docs -type f -name '*.md' | sort`
- `rg -n "\]\((\./)?docs/|README\.md|docs/[A-Za-z0-9_./-]+\.md" -S`
- `rg -n "\[[^\]]+\]\(([^)]+)\)" README.md docs/**/*.md`
- `for f in README.md $(find docs -type f -name '*.md' | sort); do rg -n --fixed-strings "$f" README.md docs assettrack tests scripts; done`

## Referenced Docs (In-Repo)
- `README.md`
- `docs/user-guide.md`
  - Referenced in `README.md` as `Operator Manual`.
- `docs/security/trivy-readable.md`
  - Referenced in `README.md` as plain path text.

## Unreferenced Docs (In-Repo)
No in-repo references were found to these markdown docs by full path:
- `docs/PROJECT_INTENT.md`
- `docs/adr/0001-core-architecture-decisions.md`
- `docs/adr/adr-002-core-asset-model-and-crud-boundaries.md`
- `docs/adr/adr-003-audit-and-state-transition-discipline.md`
- `docs/deployment.md`
- `docs/dev-environment.md`
- `docs/docker-data-persistence.md`
- `docs/ingest/opn-2004-format-analysis.md`
- `docs/models/asset.md`
- `docs/operational_assumptions.md`
- `docs/operations/backup_restore.md`
- `docs/scanner_expectations.md`

## Classification

### Field-required Docs
These directly support operator/field deployment and day-2 operations by title/content intent.
- `docs/user-guide.md`
- `docs/deployment.md`
- `docs/docker-data-persistence.md`
- `docs/operations/backup_restore.md`
- `docs/scanner_expectations.md`
- `docs/operational_assumptions.md`

### Developer-reference Docs
These are architecture/design/dev/security reference materials.
- `README.md`
- `docs/dev-environment.md`
- `docs/models/asset.md`
- `docs/ingest/opn-2004-format-analysis.md`
- `docs/adr/0001-core-architecture-decisions.md`
- `docs/adr/adr-002-core-asset-model-and-crud-boundaries.md`
- `docs/adr/adr-003-audit-and-state-transition-discipline.md`
- `docs/security/trivy-readable.md`

### Candidate Legacy Docs
These appear likely legacy based on present codebase context and/or lack of references.
- `docs/PROJECT_INTENT.md`
  - Notes current system "is today" as Tkinter desktop app, which does not match the present Flask web app structure.

## Notes / Ambiguities
- This is a static reference audit. "Unreferenced" means no in-repo link/path matches were found; it does not prove lack of operational use.
- Some docs are clearly useful but currently unlinked from `README.md` or UI templates.
- No app templates or runtime routes were found that link to docs.
