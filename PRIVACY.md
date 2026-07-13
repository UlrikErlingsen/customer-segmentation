# Privacy

SegmentSignal has no accounts, analytics, advertising, telemetry, or built-in database. It does not intentionally persist uploaded customer data.

## Local use

When you run the app on your own computer, uploaded files are read into that running Python process. SegmentSignal does not send them to the project author or to a third-party API. Closing the process clears the in-memory session; the app does not save the upload unless you explicitly download an export.

## Hosted use

If someone deploys SegmentSignal on Streamlit Community Cloud or another server, uploads travel to and are processed by that host. The deployment operator—not this repository—controls server access, logs, backups, retention, jurisdiction, and authentication. Do not upload personal or confidential data until the operator has documented those controls.

## Data minimization

Use pseudonymous customer IDs and remove names, email addresses, phone numbers, street addresses, free text, and any columns that are not needed for the decision. The interface flags several likely direct and sensitive identifiers, but automated detection is incomplete.

## Exports

Exports are created in memory and downloaded at your request. They can contain customer IDs and customer-to-segment mappings. Store and share them according to your organization’s access, retention, and deletion policies.
