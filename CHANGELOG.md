# Changelog

All notable changes to Segment Signal are documented here.

## 1.3.0 - 2026-10-03

### Larger datasets

- Larger datasets: run locally (standalone, a local Signal Hub or an internal deployment), Segment Signal no longer sets any limit on file size, rows, cells or customers; memory is the limit. The former 200 MB upload, 50 MB JSON, 400 MB expanded-Excel, 1-million-row, 10-million-cell, 25,000-customer, 30-basis-variable and 200-model-column limits now apply only in the public demo (more than 200 model columns now draws a warning locally) (`SIGNAL_PUBLIC=1`), where messages say they are demo limits. All caps live in the new `segmentsignal.limits` module.
- Streamlit's upload cap is 10,000 MB: `.streamlit/config.toml`, `SEGMENTSIGNAL_MAX_UPLOAD_MB` (default 10000) in `run_app.bat` as well as `run_app.command`, and `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=10000` in the Docker image.
- Running out of memory while loading or analyzing is reported as a plain "not enough memory on this computer" message.
- Above 25,000 customers, candidate comparison, stability refits and the final fit use a seeded random sample (25,000 by default, adjustable on page 2 up to every customer); preparation statistics use every customer, and every other customer is assigned to the nearest segment (or the most probable Gaussian-mixture component) with the same confidence measure. The app shows the sample and the export manifest records it as `model_sample`. Profiles, ANOVA, sizes and every export cover every customer.
- Ward and spectral clustering are no longer refused above 5,000 and 2,500 customers locally; the app explains that their memory grows with the square of the sample. Hierarchy views above 5,000 customers are built on request.
- Exports use the full data: the JSON download always holds every customer (large tables are embedded compactly), the CSV holds every customer, and the Excel pack holds the map whenever it fits on one sheet (1,048,575 rows). Large-table exports are built only when their button is clicked.
- Faster, leaner reading and checks: CSV uses pandas' C parser in 250,000-row chunks with the delimiter detected from the header (comma, semicolon, tab or pipe); loaded tables are no longer copied; preparation works one column at a time; schema checks, profiles and the dataset fingerprint run once per table instead of on every rerun; RFM aggregation groups on integer codes. A purchase-date column that does not look like dates fails fast on large logs instead of parsing value by value.
- Measured on a 24-thread desktop: a 5-million-customer CSV (305 MB) runs the whole workflow in about 1.5 minutes with a peak of about 2.1 GB; a 10-million-row purchase log (335 MB) aggregates to 1.5 million customers in about 17 seconds with a peak of about 3.1 GB.

### Suite

- Suite: Rival, Reach, Learn and Blueprint Signal added to the suite table.

## 1.2.0 - 2026-10-02

Signal brand refresh and Signal Hub entry point. The analysis, statistics, data formats and exports are unchanged.

### Brand

- Display name written **Segment Signal** (with a space) in the app, README, docs, launchers and metadata, including the `product` field of the export manifest. Package, dist, file and environment-variable names stay `segmentsignal` / `customer-segmentation` / `SEGMENTSIGNAL_*`.
- The app uses the shared `signal_theme` module (Organic Signal design, Customer family colour `#aa5d83`, Figtree): sidebar lockup, masthead, hero, step cards, caution note, footer, per-app Plotly template and the mark as favicon replace the pasted styles. Chart colours come from the theme; the dendrogram ink and the snake-profile zero line use theme tokens.
- New banner, social preview and marks in `assets/`; the old banner SVG is removed. `.streamlit/config.toml` uses the family colours.
- README follows the Signal template; bug-report and feature-request issue templates added.
- Embedded Figtree font, no Google Fonts request: the re-synced `signal_theme` loads Figtree from the bundled `signal_font.py`, and chart colours follow the per-family contrast order.

### Signal Hub contract

- `segmentsignal.ui` exposes `APP_INFO` and `render()`, so Signal Hub can embed the app; `app.py` is now a thin standalone entry point.
- All session-state and widget keys are namespaced `segment:` (including the page selector, buttons, downloads and charts). Programmatic navigation applies a pending page before the selector is drawn.
- Opens with the fictional demo preloaded: a new session loads the fictional **Behavior table** demo once, so every page works without an upload. The demo buttons restore it or switch demos, an upload replaces it, and **Clear session data** still empties the session.
- The demo generators moved into `segmentsignal.examples`, so the demo buttons work from an installed package; `scripts/generate_examples.py` still writes identical files to `examples/`.
- `streamlit` and `plotly` moved to a `ui` extra (also in `test`, with `build` and `ruff`); the analysis core installs without them. `requirements.txt` still lists everything. Added a Ruff configuration.
- New tests: no Streamlit/Plotly import outside `segmentsignal.ui`, `render()` runs from a script without a page config, every widget and state key is namespaced across the demo workflow, the demos work from a copy of the package outside the repository, and the README follows the Signal template.

## 1.1.2 - 2026-07-16

### Security

- Excel exports now neutralize formula-like column headers (not only cell values) and scrub and de-duplicate sheet names.
- The Docker image keeps application code root-owned and read-only, and defusedxml hardens workbook XML parsing.

## 1.1.1 - 2026-07-14

- The expert-statistics ANOVA now computes F directly from the sums of squares, handling constant and perfectly separated variables without scipy warnings (F = NaN and F = ∞ respectively).

## 1.1.0 - 2026-07-14

- Standardization of numeric bases can now be turned off for data that already shares one scale.
- ChoiceSignal part-worth exports are recognized on upload, with guidance and standardization off by default.
- The export page points to WorthSignal for per-segment value, retention, and CLV analysis.

## 1.0.0 - 2026-07-14

- First stable release. No functional changes since 0.3.0; the version now
  signals that the workflow, methods, exports, and file formats are stable.

## 0.3.0 - 2026-07-13

- Page 2 gained hierarchy views for files up to 5,000 customers: split boxes (icicle) showing the customer base dividing into smaller groups, and a truncated dendrogram — the classic hierarchical-clustering visuals.
- Page 3 gained an Expert statistics tab: a descriptive one-way ANOVA per numeric basis variable (F, df, p, eta squared) and distances between segment centers, with the standard caveat that cluster-derived F tests are not hypothesis tests.
- Removed the remaining course-material references from the README.

## 0.2.1 - 2026-07-13

- Fixed a crash on macOS where the app died with a "connection error" popup while showing tables (a segmentation fault inside pyarrow's bundled memory allocator). Arrow now uses the system allocator, set in the app and in every launcher.

## 0.2.0 - 2026-07-13

- Added graph-based spectral clustering (up to 2,500 customers) as a fourth method for stretched or curved group shapes.
- After a comparison, any method-and-count combination can now be fitted directly as a clearly marked custom solution.
- Fixed the sidebar navigation losing its place when a demo was loaded or a file was uploaded; loading data now opens page 1 automatically.
- Creating a segmentation now continues straight to Profiles & export, and page 1 gained a continue button after a saved setup.
- Page 3 gained an Explore two variables tab with an original-unit scatter plot and a per-segment distribution (box) view.
- Page 3 now states which solution is active, including whether it was a custom fit.

## 0.1.0 - 2026-07-13

- First public-ready MVP.
- Customer-table and transaction-log workflows.
- K-means, Gaussian mixture, and Ward hierarchical clustering.
- Multi-metric candidate comparison with resampling stability and cross-method agreement.
- Editable profiles, uncertainty signals, and Excel, CSV, and JSON exports.
- Local-first Streamlit UI, fictional examples, methods documentation, and automated tests.

