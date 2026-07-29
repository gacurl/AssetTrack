# CI Security Baseline

This document explains AssetTrack's CI security controls and the operator response when one of those controls reports a failure.

This repository uses a minimal GitHub Actions security baseline for pull requests and pushes.

## Included

- Trivy filesystem scanning for:
  - Python dependency vulnerabilities from `requirements.txt`
  - repository misconfigurations
  - committed secret exposure
- Trivy container image scanning for the existing Docker build
- CycloneDX SBOM generation for the built image
- least-privilege workflow permissions with `contents: read`
- advisory reports include all severities: `UNKNOWN`, `LOW`, `MEDIUM`, `HIGH`, and `CRITICAL`

## Failure Thresholds

- `MEDIUM`, `HIGH`, and `CRITICAL` findings fail the workflow
- `LOW` and `UNKNOWN` findings are advisory and uploaded as workflow artifacts
- `--ignore-unfixed` is enabled so the baseline does not fail on issues without an upstream fix

Why it matters:
- the current baseline reports every severity for visibility while blocking known findings above Low
- this keeps lower-severity and unknown findings visible for review without treating them as clean

## Trivy Reference and Update Path

- `aquasecurity/setup-trivy` is pinned to commit `3fb12ec12f41e471780db15c232d5dd185dcb514` (`v0.2.6`)
- the installed Trivy CLI version is pinned in workflow input: `v0.70.0`
- Trivy action refs and Trivy CLI versions are supply-chain-sensitive and must be reviewed before any change
- avoid floating Trivy refs such as `@master`, `@main`, or mutable tags where possible
- prefer full SHA pinning for third-party actions
- update path:
  - review the specific target Trivy CLI release and the specific target action release before changing either pin
  - avoid known compromised Trivy versions and avoid assuming that a newer release is automatically safe
  - update the workflow `version` only after that review
  - if Aqua publishes a newer trusted `setup-trivy` release, update the pinned commit SHA as a separate reviewable change after verifying that exact commit

Why it matters:
- the March 2026 Trivy supply-chain incident affected mutable action references and compromised releases during a short window
- full commit pinning for `setup-trivy` reduces that exposure, but pinning still requires human review before each bump

## Not Forced Yet

- GitHub dependency review is not enabled in this baseline because support depends on repository security settings and dependency graph availability; forcing it without verification risks a permanently failing workflow
- CodeQL runs as a separate GitHub Actions workflow and should be triaged as a code-scanning control, not as a Trivy finding
- Gitleaks is not added because Trivy secret scanning already provides a low-risk secret scanning baseline without another toolchain

## Triage Guidance

- treat `MEDIUM`, `HIGH`, and `CRITICAL` findings as merge blockers until fixed or explicitly risk-accepted
- review advisory findings from uploaded artifacts during the normal patch cadence process and convert real issues into scoped remediation work
- if a finding is a false positive, document the suppression in a separate change instead of weakening the baseline broadly

## Failure Response Checklist

Use this checklist when `Security Baseline`, `CodeQL`, Dependabot, secret scanning, or a supporting CI workflow fails.

Do not weaken, bypass, suppress, delete, or lower protections, tests, scan thresholds, scanner configuration, workflow permissions, branch rules, or security alerts to make a check pass.

Why it matters:
- a baseline failure is a control doing its job
- the response must remove the narrow source of risk without reducing the control that found it

### First Pass

1. Open the failed GitHub Actions run or security alert.
2. Find the first meaningful error:
   - use the first failing step with package, file, rule, secret type, CVE, advisory, or exit code detail
   - skip setup noise, cache restore messages, artifact upload messages, and later repeated failures until the first concrete finding is recorded
3. Identify the scanner and category:
   - CodeQL: source code or workflow-reachable code pattern
   - Trivy filesystem: dependency, repository misconfiguration, or committed secret pattern
   - Trivy image: container OS package, image dependency, image build context, or SBOM evidence
   - Dependabot or dependency alert: package advisory
   - GitHub secret scanning or Trivy secret scan: committed secret or credential pattern
   - CI workflow failure: build, syntax, test, permissions, action pin, artifact, cache, or scanner runtime failure
4. Record the finding before changing files:
   - run name and URL
   - scanner and job
   - package, file, image layer, action, rule, CVE, advisory, or secret type
   - installed version and fixed version when provided
   - highest severity
   - category: code, dependency, container, secret, workflow, or CI
5. Determine whether the same finding exists on `main`:
   - check the latest relevant run on `main`
   - compare the package version, file path, workflow step, image layer, rule, CVE, advisory, or secret pattern
   - if `main` already has the same finding, record that it predates the branch and create a scoped remediation plan instead of hiding the failure
6. Find the narrowest responsible source:
   - code: smallest function, route, template, parser, or helper that triggers CodeQL or tests
   - dependency: direct requirement, lock/generated dependency source, Docker install line, or transitive parent
   - container: Dockerfile line, base image tag or digest, OS package, copied artifact, or build step
   - secret: exact committed file/path and whether the value is real, test-only, expired, or placeholder
   - workflow: exact YAML job, step, permission, action pin, cache, artifact, or scanner invocation

### Approval Triggers

Get explicit approval before any response that would:

- change workflow files, scanner commands, scanner versions, thresholds, permissions, branch/ruleset policy, or action pins
- change runtime dependencies, Docker base images, package pins, or build behavior
- add, remove, or replace security tools
- suppress, ignore, accept, or defer a real finding
- touch authentication, authorization, persistence, recovery, receipt integrity, event history, custody logic, or offline-first behavior

### Stop Conditions

Stop and report when:

- the smallest fix would require schema, persistence, event, custody, auth, workflow, dependency, Docker, or CI behavior changes outside the approved issue
- the finding cannot be reproduced or the artifact is missing
- the scanner database update failed and the result is inconclusive
- the only apparent fix is to weaken or delete a protection

### Smallest-Safe-Fix Rule

Fix only the narrowest source that caused the failure.

- For code failures, change the specific unsafe code path and add focused verification.
- For dependency failures, select the minimum version that resolves all listed findings for that package unless a larger bump is separately approved.
- For container failures, change the smallest image, package, or build input that removes the finding.
- For secret failures, remove the secret from tracked files, rotate real credentials, and document rotation evidence; do not simply rename or mask the value.
- For workflow failures, fix the exact broken job or step after approval; do not relax gates or permissions.

### Compact Worksheet

```text
Run / alert:
Branch:
Main status:
Scanner:
Category: code | dependency | container | secret | workflow | CI
First meaningful error:
Artifact / log:
Package / file / image layer / workflow step:
Installed or current value:
Highest severity:
Minimum fixed version or narrow fix:
Exists on main: yes | no | unknown
Responsible source:
Approval needed: yes | no
Approved issue:
Chosen smallest-safe fix:
Verification:
Disposition:
```

### Worked Example: `pypdf`

```text
Run / alert: Security Baseline failure
Branch: issue branch under review
Main status: compare latest Security Baseline run on main before changing files
Scanner: Trivy
Category: dependency
First meaningful error: pypdf advisory rows in filesystem or image report
Artifact / log: trivy filesystem or image report
Package / file / image layer / workflow step: pypdf
Installed or current value: 6.13.3
Highest severity: High
Minimum fixed version or narrow fix: pypdf==6.14.2
Exists on main: record after comparison
Responsible source: direct Python dependency pin
Approval needed: yes, because dependency pins and runtime package contents change
Approved issue: scoped pypdf remediation issue
Chosen smallest-safe fix: update only pypdf to 6.14.2 unless tests require a separately approved supporting change
Verification: dependency install, compile/test coverage, Docker rebuild, Security Baseline rerun
Disposition: fixed only after reports show the listed pypdf findings cleared
```

Why `6.14.2`:
- installed version in this example: `6.13.3`
- highest listed severity: `High`
- minimum version resolving all listed findings: `6.14.2`
- do not choose a broader dependency refresh unless a separate approved issue requires it

For weekly review, severity triage, monthly patch cadence, and risk acceptance guidance, use [`patch-cadence.md`](patch-cadence.md).
