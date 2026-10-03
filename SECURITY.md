# Security policy

## Supported version

Security fixes are applied to the latest release on the `main` branch.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability involving code execution, file handling, dependency compromise, or disclosure of customer data. Email [code.modular578@passmail.net](mailto:code.modular578@passmail.net) with the subject `[SegmentSignal security]`. If GitHub private vulnerability reporting is enabled for the public repository, you may instead use its [private security advisory form](https://github.com/UlrikErlingsen/customer-segmentation/security/advisories/new). Include the affected version, reproduction steps, impact, and any suggested mitigation.

## Scope and operating advice

Segment Signal accepts tabular CSV, Excel and JSON files. Run locally it sets no size limit of its own (Streamlit's upload cap defaults to 10,000 MB via `SEGMENTSIGNAL_MAX_UPLOAD_MB`); a public deployment should set `SIGNAL_PUBLIC=1`, which enforces upload, expanded-workbook, row, cell and customer caps (`src/segmentsignal/limits.py`). It does not accept serialized Python models or execute spreadsheet macros. This reduces risk but does not make an internet deployment safe by itself. Hosted operators remain responsible for authentication, TLS, patching, access logging, isolation, backups, and data retention, and may choose a lower upload limit.
