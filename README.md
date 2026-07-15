<p align="center">
  <img src="assets/segmentsignal-banner.svg" alt="SegmentSignal — Find the groups worth understanding" width="100%">
</p>

<p align="center">
  <a href="https://github.com/UlrikErlingsen/customer-segmentation/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/UlrikErlingsen/customer-segmentation/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-173C3A?logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/Streamlit-app-D95B40?logo=streamlit&logoColor=white">
  <a href="LICENSE"><img alt="License: AGPL-3.0-or-later" src="https://img.shields.io/badge/License-AGPL--3.0--or--later-36534E"></a>
</p>

<p align="center"><strong>Open B2C customer segmentation for marketers — guided methods, stability checks, local-first data.</strong></p>

**SegmentSignal** turns a customer table or transaction log into testable customer segments through a point-and-click Streamlit app. Choose what should form the groups, compare several algorithms and segment counts, see whether customer memberships survive resampling, profile the chosen solution, edit the names, and download the customer-to-segment map. No account or statistics software is required.

## Read this first

> **Treat segments as decision support, not discovered truth.** Clusters are patterns in a particular sample. They depend on the business question, customers, variables, preprocessing, and model choices. A useful market can have no reliable cluster structure, and statistical separation does not prove that a segment is reachable, fair, or profitable.

SegmentSignal is deliberately able to say **“no reliable segmentation found.”** That is often a better result than polished but unstable personas.

## Why SegmentSignal

- **Made for marketers:** business-question framing, plain-language controls, fictional demos, original-unit profiles, and portable exports.
- **Compare rather than guess:** K-means and Ward hierarchical clustering for numeric or mixed bases, Gaussian mixtures for numeric-only bases, and graph-based spectral clustering for smaller files with irregular group shapes — over several candidate segment counts.
- **Validation that means something:** separation, resampling stability, cross-method agreement, segment size, balance, and simplicity are shown together.
- **Bases stay separate from descriptors:** needs, preferences, values, and behavior can form segments; demographics and channel fields can profile them without silently driving the clusters.
- **Local-first:** no account, telemetry, advertising, external AI calls, or built-in customer-data storage.
- **Explainable and reproducible:** preparation choices, the random seed, diagnostics, customer memberships, and profiles travel with the export.

## Get the app

You need Python 3.10 or newer. Download this project from GitHub and unzip it, or clone it:

```bash
git clone https://github.com/UlrikErlingsen/customer-segmentation.git
cd customer-segmentation
```

**Mac:** double-click `run_app.command`. The browser opens automatically after the local server is ready.

**Windows:** double-click `run_app.bat`.

The first start creates a private `.venv` folder and installs the required packages, which can take a few minutes. Later starts reuse it without requiring a network connection. The launcher automatically notices dependency changes after an update.

Or use a terminal:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

With Docker:

```bash
docker build -t segmentsignal .
docker run --rm -p 8501:8501 segmentsignal
```

Then open `http://localhost:8501`.

## No install? Give this file to an AI

Don't want to install anything? [AI_ANALYST.md](AI_ANALYST.md) is a single copy-paste file that turns a capable AI assistant (Claude, ChatGPT, Gemini, …) into this analysis. Copy the file into a chat, add your data, and the AI follows the same published methods and honesty rules as the app. The app is still the more private option: local mode keeps your data on your computer, while a cloud AI sees whatever you paste.

## Try it in two minutes

1. Start the app and click **Demo · behavior table** in the sidebar.
2. Open **1 · Data & purpose**. Review the automatically separated basis variables and descriptors, then save the setup.
3. Open **2 · Compare solutions**, keep the defaults, and run the comparison.
4. Carry the leading four-segment solution forward.
5. Open **3 · Profiles & export** to inspect the map, snake profile, membership uncertainty, names, and downloads.

All demos are fictional. **Behavior table** has one ready-made row per customer. **Purchase log** has repeated orders that are aggregated into optional RFM variables. **Needs survey** contains attitudes, needs, demographics, and no RFM fields, demonstrating that the app is not tied to customer-value data. `examples/customer_template.xlsx` and `examples/customer_template.csv` show the customer-level shape.

## The workflow

1. **Define the purpose.** Choose the decision that the segmentation should support.
2. **Audit the data.** Review missingness, duplicates, likely IDs, PII, sensitive fields, and low-variation columns.
3. **Assign roles.** Choose one customer ID, segmentation bases, descriptors, and exclusions.
4. **Prepare transparently.** Median-impute numerics, preserve missing categories, optionally limit extremes and log strong skew, standardize numeric scales, and one-hot encode categorical bases.
5. **Compare candidates.** Use the guided range or test exact counts from 2 up to 50 (and below the customer count), then compare separation, stability, size, agreement, and parsimony.
6. **Make the decision.** Select a candidate—or accept that the data do not support a reliable segmentation.
7. **Profile and export.** Review original-unit means, indexed category patterns, editable names, customer memberships, uncertainty, and a reproducibility trail.

## Which data works?

SegmentSignal reads `.csv`, `.xlsx`, `.xls`, `.xlsm`, and `.json` up to 200 MB in the local app. JSON remains capped at 50 MB because it must be expanded in memory before validation.

**Customer-level data:** one row per customer, one unique ID, and any relevant structured variables: needs ratings, survey scores, demographics, categories, benefits sought, product usage, purchase behavior, engagement, price sensitivity, or channel preferences. RFM and CLV fields are optional.

**Transaction data:** repeated rows with customer ID, purchase date, amount, and optional order ID. The app creates recency, frequency, monetary value, average order value, and tenure before clustering.

Structured numeric, categorical, and boolean fields are supported. Raw text, images, arbitrary model files, geospatial modeling, survey weighting, and time-series sequence clustering are outside this first release. See [the data guide](docs/data_guide.md).

Safety limits for this release are 200 MB per local upload, 400 MB uncompressed Excel content, 1 million rows per raw table, 10 million loaded cells, 25,000 analyzed customers, and 200 prepared model columns. These bounds keep local and hosted sessions responsive; they are not statistical recommendations. A 1 GB path would require out-of-core transaction aggregation rather than merely raising Streamlit’s upload setting.

## Methods and accuracy

The default candidate range is 3–6 because a segmentation must remain manageable. An exact-count mode allows any selected count from 2 to 50 and below the customer count; warnings remain visible, but unusual choices are not blocked. After a comparison you can also fit any method-and-count combination directly, including combinations that were not compared, clearly marked as untested custom fits. SegmentSignal reports:

- silhouette score;
- Calinski–Harabasz score;
- Davies–Bouldin index;
- repeated 80% subsample stability using adjusted Rand agreement;
- agreement between algorithms at the same segment count;
- smallest and largest segment share;
- a transparent balanced evidence score with a modest simplicity preference;
- GMM AIC/BIC in the detailed diagnostics;
- row-level relative membership confidence.

The balanced score is a navigation aid, not a hypothesis test. The app shows every component so a user can disagree. Thresholds are documented as cautious heuristics, not universal laws. See [methods and references](docs/methods.md).

Run the independent statistical and app tests with:

```bash
python -m pytest
```

## B2C focus and relationship to WorthSignal

SegmentSignal is designed first for B2C markets, where there are usually enough individual customers for quantitative grouping and macro-targeting. Smaller B2B customer bases often require account-specific research, buying-center roles, firmographic context, and qualitative judgment that generic clustering cannot replace.

This project does not duplicate its siblings. [WorthSignal](https://github.com/UlrikErlingsen/customer-value-analytics) covers customer value, RFM targeting, CLV, retention, and marketing ROI; [ChoiceSignal](https://github.com/UlrikErlingsen/conjoint-analysis) covers conjoint analysis — what customers value in a product. [AdoptSignal](https://github.com/UlrikErlingsen/adoption-forecasting) forecasts when a new product gets adopted. [PositionSignal](https://github.com/UlrikErlingsen/brand-positioning) maps how brands are perceived against competitors. [DriverSignal](https://github.com/UlrikErlingsen/survey-driver-analysis) finds which survey factors drive satisfaction. [AllocSignal](https://github.com/UlrikErlingsen/marketing-mix-allocation) turns response assumptions into a budget allocation. SegmentSignal focuses on multi-variable segment discovery, validation, profiling, and export. Regression predicts an outcome; clustering forms groups; conjoint measures preferences. They are different jobs.

The recommended product architecture is to keep both analytical engines separate and later add a small shared **CustomerSignal Hub** that launches or links to them. Shared branding and carefully extracted upload/UI components can live in a small common package; the statistical modules should not be merged into one large `app.py`.

## Privacy and responsible use

Local mode keeps the file in the running process on your computer. Hosted mode sends it to the chosen host, so the operator is responsible for access control, logs, retention, and legal compliance. Read [PRIVACY.md](PRIVACY.md) before using personal or confidential data.

Remove names and contact details, use pseudonymous IDs, minimize variables, and review sensitive attributes and proxies. A cluster does not prove causality or justify discrimination. Macro-targeting will inevitably include some nonmembers and miss some true members.

## About this project

The product name is **SegmentSignal**; the repository keeps the clear `customer-segmentation` name. It is a visual sibling to WorthSignal and is intended to fit a future portfolio of open customer-analytics tools.

This app was built with AI assistance and reviewed against established market-segmentation and cluster-validation methods. All example customer records are synthetic. The workflow follows the published segmentation and cluster-validation literature cited in [docs/methods.md](docs/methods.md); no licensed third-party materials are included.

Contributions are welcome—see [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

AGPL-3.0-or-later. Commercial use is allowed, while distribution and modified network services carry source-sharing obligations described in the full [LICENSE](LICENSE). This summary is not legal advice; the license text controls.
