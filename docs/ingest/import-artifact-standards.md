# Import Artifact Standards

## Purpose

Define where import-adjacent artifacts belong, how they are named, and what is tracked in git versus kept local-only.

This standard is documentation-only. It does not change import behavior, schema, event model, or runtime workflows.

## Tracked vs Local-Only

### Tracked in git

- Canonical import templates (CSV)
- Canonical import template specs/instructions (Markdown)
- Canonical sample files used for operator/reference documentation (CSV)
- Import contract and standards docs
- Import utilities/scripts that are part of repo tooling
- Planning docs for import-related roadmap work

### Local-only (not tracked)

- Runtime import inputs used by operators in the field
- Generated staging reports
- Ad-hoc spreadsheets and one-off extracts
- Any sensitive/operational data files

Runtime/local files must remain under `data/import/` (or other ignored local paths) and must not be committed.

## Canonical Locations

- `docs/fixtures/imports/<domain>/`
  - Tracked canonical templates and samples (CSV + companion docs)
- `docs/ingest/`
  - Import contract/spec documentation and standards
- `data/import/`
  - Local runtime imports and generated staging reports only
- `tools/` or `scripts/`
  - Import utilities, following existing repo patterns
- `docs/roadmap/`
  - Planning/triage/recon issue documentation only

## Naming Conventions

Use lowercase snake_case with explicit purpose and major-version suffix.

- Template CSV:
  - `<domain>_<purpose>_template_v<major>.csv`
- Template spec/instructions:
  - `<domain>_<purpose>_template_v<major>.md`
- Sample CSV:
  - `<domain>_<purpose>_sample_v<major>.csv`

## Default Tracked Template Format

Default tracked format is:

- `.csv` for machine/operator template rows
- `.md` for field definitions, constraints, and usage notes

Rationale: diff-friendly, reviewable, portable, and aligned with current repo ignore rules.

## Spreadsheet (XLSX) Policy

- `.xlsx` remains ignored by default.
- Do not force-add `.xlsx` artifacts unless a separate, explicit approval issue authorizes it.
- If spreadsheet support is later approved for a specific template, scope and rationale must be documented first.

## Network Staging Example (Future)

For switch/router staging artifacts, tracked canonical files should follow:

- `docs/fixtures/imports/network/network_switch_router_staging_template_v1.csv`
- `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md`
- `docs/fixtures/imports/network/network_switch_router_staging_sample_v1.csv`

Operational uploads/exports for these templates remain local-only under `data/import/`.

