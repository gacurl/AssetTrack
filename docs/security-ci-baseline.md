# Security CI Baseline

## Purpose

AssetTrack security CI protects the deployable field image from known Medium,
High, or Critical security findings while preserving readable reports for human
triage.

Why it matters: the field image must remain safe to deploy without changing
AssetTrack runtime behavior, custody truth, receipt truth, event history,
SQLite persistence, or offline-first operation.

## Workflows

### CI

Workflow: `.github/workflows/ci.yml`

Runs on:

- `push`
- `pull_request`

Scans and checks:

- Python source compilation with `python -m compileall .`

Gate behavior:

- compile failures fail the workflow
- this workflow does not perform vulnerability or secret scanning

Permissions:

- `contents: read`

### Security Baseline

Workflow: `.github/workflows/security-baseline.yml`

Runs on:

- `push`
- `pull_request`

Permissions:

- workflow default: `contents: read`
- each Trivy job: `contents: read`

No production secrets are required or passed to the scan jobs.

## Security Jobs

### Trivy Filesystem, Dependency, And Secret Scan

Job: `trivy-filesystem`

What it scans:

- repository filesystem
- Python dependency manifests and lock data available to Trivy
- Dockerfile and repository misconfiguration findings
- committed secret patterns

Report command:

- `trivy fs --scanners vuln,misconfig,secret`
- report severities: `UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL`
- output formats: table and JSON

Fail gate:

- `MEDIUM,HIGH,CRITICAL`

Report-only findings:

- `UNKNOWN`
- `LOW`

### Trivy Container Image Scan

Job: `trivy-image`

What it scans:

- locally built deployable Docker image
- OS package vulnerabilities
- application dependency vulnerabilities visible inside the image
- image SBOM generation

Report command:

- `trivy image`
- report severities: `UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL`
- output formats: table, JSON, and CycloneDX SBOM

Fail gate:

- `MEDIUM,HIGH,CRITICAL`

Report-only findings:

- `UNKNOWN`
- `LOW`

## Severity Policy

Deployable-image security checks must not pass with known findings above Low.

- `LOW`: report only; does not fail the workflow
- `MEDIUM`: fails filesystem/dependency and image gates
- `HIGH`: fails filesystem/dependency and image gates
- `CRITICAL`: fails filesystem/dependency and image gates
- `UNKNOWN`: report only; must be triaged explicitly before release reliance

Unknown findings are not treated as clean. Operators must review them because
the scanner could not assign a reliable severity.

## Trivy Version Control

The workflow installs Trivy through `aquasecurity/setup-trivy` pinned to a full
commit SHA, with the reviewed tag noted in a comment.

Current controls:

- setup action pinned to a full commit SHA
- Trivy CLI version pinned with `version: v0.70.0`
- comments warn against floating refs such as `@master`, `@main`, or mutable tags

Any future bump must review both:

- the setup action commit
- the Trivy CLI version

## Trivy Database Updates

The Trivy CLI updates vulnerability databases during scan execution using
Trivy's standard database update behavior. The setup step enables Trivy cache
support so repeated runs can reuse cached scanner data where GitHub Actions
allows it.

If a database update fails, the scan job should be treated as inconclusive and
the image must not be considered cleared by CI.

## Reports And Artifacts

Human-readable reports are uploaded even when scan gates fail.

Filesystem artifacts:

- artifact name: `trivy-filesystem-reports`
- `trivy-reports/fs-all-severities.txt`
- `trivy-reports/fs-all-severities.json`

Image artifacts:

- artifact name: `trivy-image-reports`
- `trivy-reports/image-all-severities.txt`
- `trivy-reports/image-all-severities.json`
- `trivy-reports/image-sbom.cdx.json`

The upload steps use `if: always()` so reports remain available for failed
security runs.

## Finding Triage

Operators should triage findings from the uploaded table report first, then use
the JSON report when exact package, path, or vulnerability identifiers are
needed.

Required follow-on action:

- `MEDIUM`: fix, update, remove, or document an approved release-blocking
  exception before relying on the image
- `HIGH`: fix before release reliance unless an explicit owner-approved
  emergency exception exists
- `CRITICAL`: fix before release reliance
- `UNKNOWN`: review and classify explicitly; do not treat as clean without
  human triage
- `LOW`: track and remediate opportunistically unless context makes the finding
  operationally sensitive

Do not resolve findings by weakening scan scope, removing readable artifacts, or
changing runtime behavior outside a dedicated issue.

## Secret Protection

Security scan jobs do not need AssetTrack runtime secrets.

Current protections:

- jobs run with `contents: read`
- no production environment is selected
- no secret values are passed through `env`
- scan commands read repository contents and a locally built Docker image only
- artifact uploads contain scanner output, not configured runtime secrets

If a future scan requires credentials, stop and design a separate least-privilege
workflow before adding secrets.
