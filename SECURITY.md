# Security policy

## Supported version

Security fixes are applied to the latest release on the `main` branch.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability involving code execution, file handling, dependency compromise, or disclosure of customer data. Use GitHub’s private vulnerability reporting feature for this repository. Include the affected version, reproduction steps, impact, and any suggested mitigation.

## Scope and operating advice

SegmentSignal accepts tabular CSV and Excel files up to a configurable local limit of 200 MB; JSON is capped at 50 MB. It also enforces expanded-workbook, row, cell, customer, and model-column limits. It does not accept serialized Python models or execute spreadsheet macros. This reduces risk but does not make an internet deployment safe by itself. Hosted operators remain responsible for authentication, TLS, patching, access logging, isolation, backups, and data retention, and may choose a lower upload limit.
