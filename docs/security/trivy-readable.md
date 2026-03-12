# AssetTrack Trivy Security Readout

**Issue:** 23-4  
**Scan date (UTC):** 2026-03-12 19:55:52 UTC  
**Scan scope:** repository filesystem from the project root  
**Scanner:** Trivy filesystem scan (`vuln`, `secret`, `misconfig`)

## What was scanned

The scan was run from the AssetTrack project root against the checked-in repository contents, using the required commands:

```bash
trivy fs --scanners vuln,secret,misconfig .
trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 .
```

This covered:

- Python dependencies declared in `requirements.txt`
- Docker configuration in `Dockerfile`
- Repository contents for committed secrets

## Initial findings

Baseline scan results before remediation:

- `requirements.txt`: 4 medium vulnerabilities
- `Dockerfile`: 2 misconfigurations
- Secret scan: 0 findings

Details:

### Vulnerabilities

`pypdf==6.7.2` was flagged for four fixed medium-severity CVEs:

- `CVE-2026-27888`
- `CVE-2026-28351`
- `CVE-2026-28804`
- `CVE-2026-31826`

All four findings were denial-of-service issues in crafted PDF handling and had fixed versions available upstream.

### Misconfigurations

The Dockerfile was flagged for:

- `DS-0002` (HIGH): container ran as root because no `USER` was specified
- `DS-0026` (LOW): no `HEALTHCHECK` instruction

### Secrets

- No secrets were detected by Trivy in the repository scan.

## What was fixed

Two narrowly scoped remediations were applied:

1. `requirements.txt`
   - bumped `pypdf` from `6.7.2` to `6.8.0`
   - this is the first version that clears all four reported CVEs

2. `Dockerfile`
   - added a dedicated non-root runtime user: `assettrack`
   - ensured `/app` and `/app/data` are owned by that runtime user inside the image
   - added a lightweight Python-based `HEALTHCHECK` against `http://127.0.0.1:8000/`
   - kept the existing container contract intact: same image base, same workdir, same command, same `/app/data` persistence path

## Why the fixes are safe

These changes stay within the issue scope and preserve system invariants:

- No schema changes were made.
- No auth or role enforcement logic was weakened.
- No event, audit, or append-only behavior changed.
- SQLite persistence still uses `/app/data/assettrack.db`.
- The runtime command and offline-first local operation were preserved.
- The dependency change was a targeted security patch, not broad dependency churn.

## Verification performed

### Automated

- `pytest`: **79 passed**

### Docker runtime

- `docker compose up -d --build`: passed
- container served the app successfully on port `8000`
- `curl http://localhost:8000`: returned `HTTP/1.1 200 OK`
- login check with existing local credentials `admin / admin123`: returned `302` redirect to `/dashboard`
- `docker compose down`: passed

### Manual workflow note

Container startup and login were verified after the Docker hardening change. A deeper issue/preview/commit/queue-clear run was not executed against the mounted local database because that would have mutated real persisted state. Existing automated tests still cover those flows, and all tests passed after the remediation.

## Final status

Final Trivy results after remediation:

```text
requirements.txt: 0 vulnerabilities
Dockerfile: 0 misconfigurations
Secrets: 0 findings
```

Required gate command result:

- `trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 .`
- exit status: **0**

## Residual risk

No Trivy findings remained at the end of this issue.

Operational note:

- the app still runs on the Flask development server inside Docker, which is not a Trivy finding and was not changed in this issue because replacing the serving model would be a broader runtime change outside scope

## Conclusion

AssetTrack is **clean on the required Trivy filesystem release scan** as of 2026-03-12 19:55:52 UTC, with tests passing and the Dockerized app still starting and authenticating successfully after remediation.
