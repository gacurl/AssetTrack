<!-- docs/security/trivy-full-scan.md -->

# Trivy full container scan (informational)

Date: 2026-02-09  
Image: assettrack:local  
Base image: Alpine 3.23.3  
Scanner: Trivy  
Scan mode: Full (all scanners, all severities)

## Purpose

This document records a **full Trivy scan** of the AssetTrack container image.
It is intended to provide **maximum visibility** into the container’s security surface
and to avoid surprises during later reviews or audits.

This scan is **informational only** and is **not used as a release gate**.

The authoritative security baseline remains documented in `docs/security/trivy.md`.

---

## Summary

- CRITICAL: 0  
- HIGH: 0  
- MEDIUM: 1  
- LOW: 1  

No operating system vulnerabilities were detected in the base image.
No application-level Python package vulnerabilities were detected.

---

## Findings detail

### Python tooling (pip)

Two vulnerabilities were identified in the `pip` package bundled in the image:

| CVE | Severity | Installed | Fixed Version | Notes |
|----|--------|-----------|--------------|------|
| CVE-2025-8869 | MEDIUM | 25.0.1 | 25.3 | Missing checks on symbolic link extraction |
| CVE-2026-1703 | LOW | 25.0.1 | 26.0 | Information disclosure via crafted wheel archives |

### Interpretation

- These vulnerabilities affect **pip as an installer tool**, not the AssetTrack application itself.
- The container does **not** install untrusted packages at runtime.
- The attack surface for these CVEs is therefore **not exposed** in the AssetTrack threat model.

Upgrading `pip` is possible but not required for this milestone.

---

## Remediation stance

- No immediate remediation is required.
- The findings are recorded for visibility.
- A future base image rebuild may naturally resolve these as `pip` is updated upstream.

---

## Raw report

The complete Trivy output is preserved here:

`docs/security/trivy-image-full-report.txt`