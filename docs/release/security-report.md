# AssetTrack Security Report

## Purpose

This release security report summarizes the Trivy validation completed for the MVP release and points to the full detailed readout.

## Source of record

The detailed Trivy report for the remediation work is here:

- [trivy-readable.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/security/trivy-readable.md)

That document is the source of record for the exact findings, commands, and verification notes from the security cleanup.

## What was scanned

The release scan covered the repository filesystem from the project root using Trivy with:

- vulnerability scanning
- secret scanning
- Dockerfile misconfiguration scanning

The scan covered:

- Python dependencies in `requirements.txt`
- Docker configuration in `Dockerfile`
- repository contents for committed secrets

## What was found

The initial Trivy run found:

- 4 medium-severity vulnerabilities in `pypdf==6.7.2`
- 2 Dockerfile misconfigurations
- 0 secrets

The Dockerfile findings were:

- container ran as root
- no health check was defined

## What was fixed

The remediation was intentionally narrow:

- `pypdf` was updated from `6.7.2` to `6.8.0`
- the Docker image was changed to run as a dedicated non-root user
- a Docker health check was added

No application behavior, schema, or business logic was changed as part of that security cleanup.

## Final release status

The final required Trivy release gate is clean.

Final release result:

- `requirements.txt`: 0 vulnerabilities
- `Dockerfile`: 0 misconfigurations
- secrets: 0 findings

The required high/critical gate command passed with exit status `0`.

## Why this matters for release

This release demonstrates that:

- dependencies were checked for known vulnerabilities
- repository contents were checked for committed secrets
- container hardening findings were addressed
- the final release scan is clean

## Related documents

- [release-notes.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/release/release-notes.md)
- [deployment.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/release/deployment.md)
- [trivy-readable.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/security/trivy-readable.md)
