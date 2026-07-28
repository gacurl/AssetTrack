# CI/CD Security Audit

Issue: 29-22

Date: 2026-07-22

Scope: audit only. No workflow, repository setting, dependency, application, Docker, authentication, schema, persistence, event, or custody change was made.

## Executive Summary

AssetTrack has a small CI/CD footprint with two active GitHub Actions workflows:

- `CI`
- `Security Baseline`

No deployment workflow was found under `.github/workflows/`.

The strongest current controls are:

- workflows set `contents: read`
- no workflow passes production secrets
- Trivy scans the repository filesystem, dependencies, Docker configuration, committed secret patterns, and the built container image
- Trivy reports and image SBOM artifacts are uploaded
- the Trivy setup action is pinned to a full commit SHA

The main security gaps are:

- `main` has no classic branch protection and no repository rulesets visible through read-only GitHub access
- repository default `GITHUB_TOKEN` permission is `write`, even though the workflows override it to read-only
- most GitHub Actions are pinned to movable version tags instead of full commit SHAs
- no CodeQL, Bandit, Semgrep, or other SAST workflow is active
- normal CI compiles Python but does not run the pytest suite
- Dependabot security updates are disabled
- Docker base image uses a mutable tag instead of a digest pin
- artifact retention is implicit instead of declared in workflow YAML

Why it matters: the current pipeline catches many dependency, container, filesystem, and secret-pattern risks, but it does not yet provide strong protection against direct changes to `main`, mutable CI supply-chain inputs, missed application regressions, or missing SAST coverage.

## Audit Method

Reviewed local files:

- `.github/workflows/ci.yml`
- `.github/workflows/security-baseline.yml`
- `requirements.txt`
- `Dockerfile`
- `docker-compose.yml`
- existing CI/security docs under `docs/security-ci-baseline.md` and `docs/security/ci-baseline.md`

Read-only GitHub checks used:

- `gh repo view --json nameWithOwner,defaultBranchRef,isPrivate,visibility`
- `gh api repos/:owner/:repo`
- `gh api repos/:owner/:repo/branches/main/protection`
- `gh api repos/:owner/:repo/rulesets`
- `gh api repos/:owner/:repo/actions/permissions`
- `gh api repos/:owner/:repo/actions/permissions/workflow`
- `gh api repos/:owner/:repo/actions/workflows`
- `gh api repos/:owner/:repo/actions/artifacts`
- `gh api repos/:owner/:repo/vulnerability-alerts --include`
- `gh api repos/:owner/:repo/dependabot/alerts`
- `gh api repos/:owner/:repo/code-scanning/alerts`

No repository settings were changed.

## Pipeline Inventory

### Workflow Inventory

| Workflow | File | Triggers | Status | Purpose |
|---|---|---:|---|---|
| CI | `.github/workflows/ci.yml` | `push`, `pull_request` | Active | Install Python dependencies and compile Python files. |
| Security Baseline | `.github/workflows/security-baseline.yml` | `push`, `pull_request` | Active | Run Trivy filesystem/dependency/secret/misconfiguration scan and Trivy image scan with SBOM artifact. |

Read-only GitHub workflow inventory confirmed only these two active workflows.

### Job Inventory

| Workflow | Job | Runner | Token Permissions | Main Commands |
|---|---|---|---|---|
| CI | `build` | `ubuntu-latest` | workflow-level `contents: read` | checkout, setup Python 3.12, install `requirements.txt`, `python -m compileall .` |
| Security Baseline | `trivy-filesystem` | `ubuntu-latest` | workflow-level and job-level `contents: read` | checkout, setup Trivy, `trivy fs --scanners vuln,misconfig,secret`, upload reports |
| Security Baseline | `trivy-image` | `ubuntu-latest` | workflow-level and job-level `contents: read` | checkout, setup Trivy, `docker build`, `trivy image`, image SBOM, upload reports |

### Actions Inventory

| Action | Used In | Ref Type | Current Ref | Risk |
|---|---|---|---|---|
| `actions/checkout` | both workflows | movable tag | `v5` | Version tag can move. |
| `actions/setup-python` | CI | movable tag | `v5` | Version tag can move. |
| `aquasecurity/setup-trivy` | Security Baseline | full commit SHA | `3fb12ec12f41e471780db15c232d5dd185dcb514` with comment `v0.2.6` | Best current action-pinning control. |
| `actions/upload-artifact` | Security Baseline | movable tag | `v4` | Version tag can move. |

### Dependency And Build Inputs

| Area | Evidence | Current State |
|---|---|---|
| Python runtime | `Dockerfile` | `python:3.12.13-alpine3.23` tag. |
| Docker pip | `Dockerfile` | `pip==26.1.2` pinned. |
| CI Python | `.github/workflows/ci.yml` | `actions/setup-python@v5` with Python `3.12`. |
| CI pip | `.github/workflows/ci.yml` | `python -m pip install --upgrade pip` without a pip version pin. |
| Python packages | `requirements.txt` | Direct dependencies are pinned with exact `==` versions. |
| Python lock/hash file | local repo | No hash-locked requirements file found. |
| Docker dependency scan | `.github/workflows/security-baseline.yml` | Trivy image scan covers OS and image-visible packages. |
| Docker base image pinning | `Dockerfile` | Base image uses a mutable tag, not a digest. |
| Dependabot config | `.github/` | No Dependabot config file found. |

## Existing Effective Controls

### Workflow Triggers

Both workflows run on:

- `push`
- `pull_request`

This gives coverage for direct branch pushes and pull requests.

The workflows do not use `pull_request_target`. That is a good control because `pull_request_target` can expose elevated context to untrusted pull request code when used incorrectly.

### GITHUB_TOKEN Least Privilege In Workflow YAML

Both workflow files set:

```yaml
permissions:
  contents: read
```

The Trivy jobs also repeat:

```yaml
permissions:
  contents: read
```

This keeps workflow job tokens read-only for repository contents.

### Test And Build Coverage

The CI workflow compiles all Python files with:

```bash
python -m compileall .
```

This catches syntax errors across the repository.

### Dependency, Container, Filesystem, Misconfiguration, And Secret-Pattern Coverage

The Security Baseline workflow runs:

```bash
trivy fs --scanners vuln,misconfig,secret
```

It also runs:

```bash
trivy image
```

The filesystem scan covers repository files, Python dependency manifests visible to Trivy, Dockerfile misconfigurations, and committed secret patterns.

The image scan covers the built Docker image, including OS packages and application dependencies visible inside the image.

The image job also generates a CycloneDX SBOM:

```bash
trivy image --format cyclonedx
```

### Security Gate Thresholds

The active `security-baseline.yml` fails on:

- `MEDIUM`
- `HIGH`
- `CRITICAL`

for both filesystem and image findings.

### Secrets Handling

No workflow passes AssetTrack runtime secrets through `env`.

No workflow selects a GitHub environment.

`docker-compose.yml` references runtime SMTP and demo-token environment variables for local deployment, but those are not passed in CI workflow YAML.

GitHub repository security settings visible through read-only API:

- secret scanning: enabled
- secret scanning push protection: enabled
- secret scanning non-provider patterns: disabled
- secret scanning validity checks: disabled

### Artifact Availability

Trivy artifacts are uploaded with `if: always()`, so reports remain available when scan gates fail.

Observed artifact names:

- `trivy-filesystem-reports`
- `trivy-image-reports`

Observed artifact evidence from GitHub API showed artifacts expiring about 90 days after creation.

### Runner Security

All jobs use GitHub-hosted `ubuntu-latest` runners.

No self-hosted runner was referenced in workflow YAML.

No workflow step uses repository secrets.

## Findings

| ID | Risk | Finding | Evidence | Impact |
|---|---|---|---|---|
| F-01 | High | `main` has no classic branch protection and no repository rulesets visible through read-only GitHub API. | `gh api repos/:owner/:repo/branches/main/protection` returned `Branch not protected`; `gh api repos/:owner/:repo/rulesets` returned `[]`. | A direct push or unreviewed change could bypass CI expectations if repository permissions allow it. |
| F-02 | High | Repository default `GITHUB_TOKEN` permission is `write`, and workflow tokens can approve pull request reviews. | `gh api repos/:owner/:repo/actions/permissions/workflow` returned `default_workflow_permissions: write` and `can_approve_pull_request_reviews: true`. | Current workflows override to read-only, but future workflows could inherit broader token permissions by mistake. |
| F-03 | Medium | GitHub Actions policy allows all actions and does not require SHA pinning. | `gh api repos/:owner/:repo/actions/permissions` returned `allowed_actions: all` and `sha_pinning_required: false`. | Future workflow changes could add unreviewed or mutable third-party actions. |
| F-04 | Medium | Several actions use movable tags instead of full commit SHAs. | `actions/checkout@v5`, `actions/setup-python@v5`, and `actions/upload-artifact@v4` are tag refs. | Mutable action tags add supply-chain risk. |
| F-05 | Medium | No active SAST workflow was found. | Only `CI` and `Security Baseline` workflows are active; code scanning API returned no analysis found. | Python security defects that are not dependency, secret, or misconfiguration findings may not be caught by CI. |
| F-06 | Medium | CI does not run the test suite. | `.github/workflows/ci.yml` runs dependency install and `python -m compileall .`, but no `pytest`. | Application, auth, custody, receipt, or persistence regressions can pass CI if syntax is valid. |
| F-07 | Medium | Dependabot security updates are disabled. | Repository API returned `dependabot_security_updates: disabled`; no `.github/dependabot.yml` file was found. | Known vulnerable dependency fixes require manual discovery and update work. |
| F-08 | Medium | Docker base image is pinned by tag but not by digest. | `Dockerfile` uses `FROM python:3.12.13-alpine3.23`. | Rebuilding later can consume different base image contents under the same tag. |
| F-09 | Low | Artifact retention is implicit. | `upload-artifact` steps do not set `retention-days`; GitHub API showed current artifacts expiring about 90 days after creation. | Retention behavior depends on repository/org defaults and may drift. |
| F-10 | Low | CI upgrades pip without pinning the installed pip version. | `.github/workflows/ci.yml` runs `python -m pip install --upgrade pip`; Dockerfile pins `pip==26.1.2`. | CI dependency resolution can drift independently from the Docker build path. |
| F-11 | Low | CI security docs now agree about the Trivy severity gate. | `docs/security/ci-baseline.md`, `docs/security-ci-baseline.md`, and `security-baseline.yml` all describe the active `MEDIUM,HIGH,CRITICAL` fail gate. | Operators can see which findings block CI. |
| F-12 | Low | Trivy uses `--ignore-unfixed`. | Both filesystem and image scan commands include `--ignore-unfixed`. | Vulnerabilities without an upstream fix do not fail the gate and need human review through report artifacts. |

## Coverage Assessment

| Coverage Area | Current Coverage | Gap |
|---|---|---|
| Syntax/build check | `python -m compileall .` | No automated pytest gate in CI. |
| Unit/integration tests | Not present in workflows | Add focused pytest or full pytest workflow. |
| SAST | No active CodeQL/Bandit/Semgrep workflow found | Add GitHub-native CodeQL first if available. |
| Dependency scan | Trivy filesystem and image scans; Dependabot alerts endpoint accessible | Dependabot security updates disabled; no scheduled update config. |
| Container scan | Trivy image scan on locally built Docker image | Base image not digest-pinned. |
| Filesystem scan | Trivy filesystem scan | Uses `--ignore-unfixed`; needs artifact triage. |
| Secret scanning in CI | Trivy secret scanner | Good baseline; non-provider GitHub secret patterns and validity checks are disabled. |
| GitHub secret scanning | Enabled with push protection | Non-provider patterns and validity checks disabled. |
| Artifact integrity | Trivy reports and SBOM uploaded | No explicit retention; no artifact attestation or signing. |
| Runner security | GitHub-hosted runners only | Docker build runs on pull requests, so untrusted PR Dockerfile changes execute on hosted runners. No secrets are passed, which limits impact. |

## Settings That Could Not Be Verified

The following were not fully verified with available read-only access:

- required status checks for branch protection, because `main` returned not protected
- whether organization-level rules apply outside repository rulesets
- whether repository administrators are required to use 2FA
- whether Actions approval is required for first-time external contributors
- whether private vulnerability reporting is enabled
- whether secret scanning validity checks are unavailable for plan reasons or simply disabled
- whether GitHub Advanced Security features beyond visible secret scanning are available for this repository
- whether deployment environments exist, because no workflow references an environment
- whether artifact retention is controlled at an organization level

## Proposed Follow-On Issues

Ordered by risk first, then effort.

| Order | Risk | Effort | Proposed Issue |
|---:|---|---|---|
| 1 | High | Low | Enable branch protection or repository rules for `main`, requiring pull requests and passing CI/security checks before merge. |
| 2 | High | Low | Change repository default workflow token permissions from `write` to `read`, keeping explicit per-job permissions for any future write needs. |
| 3 | Medium | Low | Restrict allowed GitHub Actions to trusted sources and require full-length SHA pinning where repository policy supports it. |
| 4 | Medium | Low-Medium | Pin `actions/checkout`, `actions/setup-python`, and `actions/upload-artifact` to reviewed full commit SHAs. |
| 5 | Medium | Medium | Add GitHub-native CodeQL for Python if available for the repository. |
| 6 | Medium | Low | Add pytest to CI using the existing `.venv`/requirements pattern or a clean GitHub Actions install. |
| 7 | Medium | Low | Enable Dependabot security updates and add a minimal `.github/dependabot.yml` for `pip` and GitHub Actions. |
| 8 | Medium | Medium | Evaluate digest pinning for the Docker base image and define a reviewed update process that preserves offline deployment needs. |
| 9 | Low | Low | Set explicit `retention-days` for Trivy artifacts and SBOMs. |
| 10 | Low | Low | Keep CI security documentation aligned with the active `MEDIUM,HIGH,CRITICAL` Trivy gate. |
| 11 | Low | Low | Pin CI pip version or remove the CI pip upgrade so CI dependency installation tracks the Docker path more closely. |
| 12 | Low | Low | Decide whether to enable GitHub secret scanning non-provider patterns and validity checks. |

## Notes

- No secret values were viewed or recorded.
- No repository settings were changed.
- No workflow files were changed.
- No application or runtime behavior was changed.
- Offline runtime requirements remain untouched.
