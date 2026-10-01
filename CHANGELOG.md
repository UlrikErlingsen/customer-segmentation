# Changelog

All notable changes to Segment Signal are documented here.

## 1.2.0 - 2026-10-02

Signal brand refresh and Signal Hub entry point. The analysis, statistics, data formats and exports are unchanged.

### Brand

- Display name written **Segment Signal** (with a space) in the app, README, docs, launchers and metadata, including the `product` field of the export manifest. Package, dist, file and environment-variable names stay `segmentsignal` / `customer-segmentation` / `SEGMENTSIGNAL_*`.
- The app uses the shared `signal_theme` module (Organic Signal design, Customer family colour `#aa5d83`, Figtree): sidebar lockup, masthead, hero, step cards, caution note, footer, per-app Plotly template and the mark as favicon replace the pasted styles. Chart colours come from the theme; the dendrogram ink and the snake-profile zero line use theme tokens.
- New banner, social preview and marks in `assets/`; the old banner SVG is removed. `.streamlit/config.toml` uses the family colours.
- README follows the Signal template; bug-report and feature-request issue templates added.

### Signal Hub contract

- `segmentsignal.ui` exposes `APP_INFO` and `render()`, so Signal Hub can embed the app; `app.py` is now a thin standalone entry point.
- All session-state and widget keys are namespaced `segment:` (including the page selector, buttons, downloads and charts). Programmatic navigation applies a pending page before the selector is drawn.
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

