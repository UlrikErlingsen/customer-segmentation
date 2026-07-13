# Changelog

All notable changes to SegmentSignal are documented here.

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

