# CI Security Baseline

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

- `CRITICAL` findings fail the workflow
- `HIGH`, `MEDIUM`, `LOW`, and `UNKNOWN` findings are advisory and uploaded as workflow artifacts
- `--ignore-unfixed` is enabled so the baseline does not fail on issues without an upstream fix

Why it matters:
- the current baseline reports every severity for visibility while blocking only `CRITICAL` findings
- this keeps the pipeline usable while still surfacing lower-severity issues for review

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
- CodeQL is not enabled in this baseline because repository eligibility depends on GitHub Code Security availability; add it only after confirming support in repository settings
- Gitleaks is not added because Trivy secret scanning already provides a low-risk secret scanning baseline without another toolchain

## Triage Guidance

- treat `CRITICAL` findings as merge blockers until fixed or explicitly risk-accepted
- review advisory findings from uploaded artifacts during the normal patch cadence process and convert real issues into scoped remediation work
- if a finding is a false positive, document the suppression in a separate change instead of weakening the baseline broadly
