# AssetTrack — Container Security Report

**Scan Date (UTC):** 2026-02-26 23:24:08 UTC
**Image:** assettrack-assettrack:latest
**Scanner:** Trivy
**Scanners Enabled:** vuln

**Command Used:**

```
trivy image --scanners vuln --format table assettrack-assettrack:latest
```

---

## Security Status

As of the scan date above, the container image `assettrack-assettrack:latest`
contains **zero detected vulnerabilities** across all severities.

This includes:
- OS packages (Alpine base image)
- Python dependencies
- Application-installed libraries

This report establishes the current security baseline for Issue 13-2.

---

Report Summary

┌──────────────────────────────────────────────────────────────────────────────────┬────────────┬─────────────────┐
│                                      Target                                      │    Type    │ Vulnerabilities │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ assettrack-assettrack:latest (alpine 3.23.3)                                     │   alpine   │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/blinker-1.9.0.dist-info/METADATA          │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/charset_normalizer-3.4.4.dist-info/METAD- │ python-pkg │        0        │
│ ATA                                                                              │            │                 │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/click-8.3.1.dist-info/METADATA            │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/et_xmlfile-2.0.0.dist-info/METADATA       │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/flask-3.1.3.dist-info/METADATA            │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/itsdangerous-2.2.0.dist-info/METADATA     │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/jinja2-3.1.6.dist-info/METADATA           │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/markupsafe-3.0.3.dist-info/METADATA       │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/numpy-2.4.1.dist-info/METADATA            │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/openpyxl-3.1.5.dist-info/METADATA         │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/pandas-3.0.0.dist-info/METADATA           │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/pillow-12.1.1.dist-info/METADATA          │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/pip-26.0.dist-info/METADATA               │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/pypdf-6.7.2.dist-info/METADATA            │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/python_dateutil-2.9.0.post0.dist-info/ME- │ python-pkg │        0        │
│ TADATA                                                                           │            │                 │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/reportlab-4.4.9.dist-info/METADATA        │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/six-1.17.0.dist-info/METADATA             │ python-pkg │        0        │
├──────────────────────────────────────────────────────────────────────────────────┼────────────┼─────────────────┤
│ usr/local/lib/python3.12/site-packages/werkzeug-3.1.6.dist-info/METADATA         │ python-pkg │        0        │
└──────────────────────────────────────────────────────────────────────────────────┴────────────┴─────────────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)

