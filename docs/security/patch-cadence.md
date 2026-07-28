# AssetTrack Patch Cadence Policy

## Purpose

This policy defines how AssetTrack security scan findings and routine updates are reviewed and acted on without risking field instability, data loss, or operator disruption.

Why it matters:
- AssetTrack is an offline-first field system
- updates must improve security without weakening reliability
- non-critical changes should not disrupt active field operations

## Scope

This policy applies to:

- GitHub Actions security baseline results from Issue 27-82
- Trivy filesystem scan artifacts
- Trivy image scan artifacts
- dependency and base-image patch planning
- deployment verification before release use

This policy does not authorize:

- app behavior changes
- custody workflow changes
- database engine changes
- automated dependency update tooling

## Weekly Security Review

Review security scan results once each week.

Minimum weekly review steps:

1. Open the most recent `Security Baseline` workflow run in GitHub Actions.
2. Review the filesystem scan artifacts.
3. Review the image scan artifacts.
4. Confirm whether any `CRITICAL` findings are present.
5. Review advisory findings for real and relevant issues.
6. Record follow-up work as scoped issues when needed.

Review focus:

- new findings since the prior review
- findings affecting runtime dependencies
- findings affecting the Docker base image
- secrets or misconfiguration findings that indicate real exposure

Why it matters:
- weekly review keeps the backlog current without forcing unnecessary mid-week churn

## Monthly Routine Patch Cadence

Apply routine dependency and container patch updates once each month unless field operations require deferral.

Monthly patch window expectations:

1. Review open advisory findings from the weekly scan reviews.
2. Select routine dependency and base-image updates that are real, relevant, and low-risk.
3. Rebuild the Docker image after dependency or base-image updates.
4. Run required verification before deployment.
5. Deploy only after verification is clean.

Routine monthly work is the default path for:

- `HIGH` findings that are real but not urgent
- `MEDIUM`, `LOW`, and `UNKNOWN` findings that remain relevant
- normal patch refresh of Python dependencies and container packages

Why it matters:
- monthly cadence gives predictable maintenance without causing constant field change

## Immediate Patch Criteria

Patch sooner than the monthly cadence when risk justifies it.

Immediate patch review is required when any of the following are true:

- a `CRITICAL` finding is confirmed as real and relevant
- a `HIGH` finding has active exploitation risk or materially weakens a security boundary
- a secret finding indicates real credential exposure
- a base-image or dependency issue affects authentication, authorization, or recovery safeguards
- delaying the patch would create materially higher operational or security risk than patching now

Immediate patches still require verification before deployment.

Why it matters:
- urgent risk should not wait for the routine calendar

## Severity Handling

### CRITICAL

- treat as a blocker
- investigate immediately
- patch before deployment unless an explicit documented risk acceptance is approved
- if not immediately patchable, document containment and the smallest safe next step

### HIGH

- review during the weekly scan process
- create a scoped issue if the finding is real and relevant
- patch on the monthly cadence unless immediate patch criteria are met

### MEDIUM

- track during weekly review
- group into routine monthly maintenance when relevant

### LOW

- track during weekly review
- address opportunistically during monthly routine maintenance when relevant

### UNKNOWN

- treat as advisory
- review for package relevance and available upstream clarification
- track during routine cadence unless more concrete risk information appears

Why it matters:
- the workflow provides full visibility across severities, and `MEDIUM`, `HIGH`, and `CRITICAL` findings block the pipeline

## Advisory Finding Triage

Not every advisory finding requires action.

During triage, confirm:

- the affected package or image layer is actually used
- the finding applies to the shipped runtime, not only an unused path
- a fix exists upstream
- the finding is not an obvious false positive
- the operational risk justifies patching now versus during the next monthly cycle

Create a follow-up issue when:

- the finding is real and relevant
- remediation requires a dependency or base-image update
- additional testing or release planning is needed

Why it matters:
- triage keeps scan noise from turning into field instability

## Field-Event Blackout Guidance

Avoid non-critical updates during active field events, live exercises, or other operationally sensitive windows.

During a field-event blackout:

- do not deploy routine monthly updates
- do not deploy changes for `MEDIUM`, `LOW`, or `UNKNOWN` findings
- defer non-urgent `HIGH` remediation until the event closes

Exceptions:

- `CRITICAL` findings
- `HIGH` findings that meet immediate patch criteria

Why it matters:
- field reliability takes priority over non-urgent churn

## Docker Rebuild Expectations

After any dependency update or base-image update:

- rebuild the Docker image
- confirm the container starts cleanly
- confirm SQLite persistence survives restart
- do not use destructive Docker cleanup commands as part of routine patching

Why it matters:
- AssetTrack runs in Docker, so dependency changes are not complete until the image is rebuilt and verified

## Required Verification Before Deployment

Before deploying an update based on scan findings:

1. Run `python3 -m compileall .`
2. Rebuild and start the container with `./scripts/bootstrap_docker.sh`
3. Confirm the container is running with `docker compose ps`
4. Open the application and confirm the login page appears
5. Log in with a valid account
6. Confirm dashboard access works
7. Confirm normal restart behavior preserves SQLite data

If the update touches dependency or image layers that may affect runtime behavior, also perform the normal smoke test path for the release.

Why it matters:
- security patching must not introduce field breakage or data loss

## Reviewing Issue 27-82 Scan Artifacts

The `Security Baseline` workflow publishes advisory artifacts for both filesystem and image scans.

Review expectations:

- read the table report first for operator-friendly summary
- use the JSON report when the table output needs deeper confirmation
- compare filesystem and image findings to see whether the issue is source-level, dependency-level, or image-level
- use the SBOM as reference material when identifying affected components

Why it matters:
- artifact review should support fast decisions, not just archive data

## Documentation Discipline

When a finding is accepted, deferred, or determined to be a false positive:

- document the decision in the related issue or maintenance record
- keep the rationale brief and explicit
- avoid broad suppressions unless the false positive is well understood

Why it matters:
- clear records reduce repeated triage and preserve operator trust
