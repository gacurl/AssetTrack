<!-- docs/security/trivy.md -->

# Trivy container scan

Date: 2026-02-07  
Image: assettrack:local  
Scanner: Trivy

## Result summary

- HIGH: 2
- CRITICAL: 0
- Python package vulnerabilities: 0

## What the findings are

The findings are in the OS layer (Debian / glibc):

- libc-bin / libc6: CVE-2026-0861 (HIGH)

No application-level Python package vulnerabilities were detected.

## What we’re doing about it

- We are recording this as the current baseline.
- If/when Debian publishes a fixed version, we’ll rebuild the image and re-scan.
- We are not chasing “zero CVEs” for this milestone. The goal is repeatable visibility and a documented baseline.

## Raw report

See the full Trivy report: [docs/security/trivy-image-report.txt](./trivy-image-report.txt