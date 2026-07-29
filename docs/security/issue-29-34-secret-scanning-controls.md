# Issue 29-34: GitHub Secret-Scanning Control Review

Date: 2026-07-29

Scope: review and recommendation only. No repository setting, workflow, dependency, application, Docker, authentication, schema, persistence, event, or custody behavior was changed.

Why it matters: AssetTrack should catch accidental secret exposure before it reaches the public repository without creating noisy controls that operators bypass.

## Evidence Reviewed

Local files reviewed:

- `.github/workflows/ci.yml`
- `.github/workflows/security-baseline.yml`
- `docs/ci-cd-security-audit.md`
- `docs/security/ci-baseline.md`

GitHub checks used:

- `gh api repos/gacurl/AssetTrack --jq '.security_and_analysis'`
- `gh api repos/gacurl/AssetTrack/secret-scanning/alerts --paginate --jq 'length'`
- `gh api repos/gacurl/AssetTrack/actions/permissions --jq '{enabled,allowed_actions,sha_pinning_required}'`
- GitHub repository metadata through the connected GitHub app

No secret values were viewed or recorded.

## Current Controls

GitHub API reported:

| Control | Current state |
|---|---|
| Repository visibility | Public |
| Secret scanning | Enabled |
| Secret scanning push protection | Enabled |
| Secret scanning non-provider patterns | Disabled |
| Secret scanning validity checks | Disabled |
| Default secret-scanning alert query | 0 returned |
| Actions policy | Enabled, selected actions only, SHA pinning required |

Preserve push protection. It is the strongest current secret-control guard because it can stop supported secret patterns before they are pushed.

## Availability

AssetTrack is a user-owned public repository.

GitHub documents non-provider secret patterns and validity checks as organization-owned repository features. Those controls are unavailable for this repository and remain disabled.

## Recommendation

Recommended decision:

1. Leave secret scanning non-provider patterns disabled because the control is unavailable here.
2. Keep push protection enabled.
3. Keep validity checks disabled because the control is unavailable here.
4. Do not add another scanner, external secrets service, CI gate, or application runtime dependency for this issue.

Why this is the smallest safe decision:

- AssetTrack already expects runtime secrets to stay outside the repository
- GitHub secret scanning and Trivy secret scanning complement each other without changing offline runtime behavior
- secret scanning and push protection remain enabled
- non-provider patterns and validity checks are not available for this user-owned repository

## False-Positive And Operator Impact

Expected operator impact is low if rollout is deliberate.

Possible false-positive sources:

- documentation examples
- demo token placeholders
- fixture text
- command snippets
- sample `.env` references

Operator handling rule:

- do not disable push protection to get around a block
- do not rewrite real secrets into a different tracked file
- rotate any real credential before closing the alert
- document false positives narrowly in the related issue or security record
- avoid broad allow-lists unless the pattern is understood and reviewed

If future GitHub plan or ownership changes make expanded controls available, review false-positive impact before enabling either control.

## Manual GitHub Settings Action Required

No manual enablement action is recommended for this user-owned public repository.

Final state:

| Control | Expected state |
|---|---|
| Secret scanning | Enabled |
| Secret scanning push protection | Enabled |
| Secret scanning non-provider patterns | Disabled; unavailable here |
| Secret scanning validity checks | Disabled |

## Stop Conditions

Stop before changing settings if:

- GitHub requires a plan change or organization-policy exception
- enabling a control would disable or weaken push protection
- the only path requires workflow, dependency, or application behavior changes
- secret values must be viewed to complete the review
- false-positive handling would require broad suppression before the control can operate
