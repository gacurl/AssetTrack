<!-- docs/security/trivy.md -->

# Trivy container scan (baseline)

**Status:** Superseded

As of 2026-02-09, the authoritative Trivy security baseline for AssetTrack
has been updated and is documented here:

👉 `docs/security/trivy-full-scan.md`

This change reflects:
- a full-container Trivy scan
- remediation of previously identified pip vulnerabilities
- a clean baseline (0 CRITICAL / HIGH / MEDIUM / LOW)

The raw Trivy output supporting the baseline is preserved at:

`docs/security/trivy-image-full-report.txt`