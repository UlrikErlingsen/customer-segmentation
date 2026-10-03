# Data guide

Segment Signal accepts customer-level tables and transaction logs. It never modifies the uploaded file.

## Customer-level table

Use one row per customer and one unique, nonblank customer ID.

You do not need recency, frequency, monetary value, or CLV columns. Needs surveys, attitude scales, demographics, product usage, boolean flags, and low-cardinality business categories can all be used. The question is whether the selected fields define differences that your marketing decision should respond to.

| Role | What belongs here | Examples | What to avoid |
|---|---|---|---|
| Customer ID | A stable pseudonymous key | `C00412`, loyalty ID | Name, email, phone number |
| Segmentation basis | Variables that express the differences the strategy should respond to | Needs, benefits sought, usage, recency, frequency, spend, engagement, price sensitivity | Randomly available fields, direct identifiers, downstream outcomes you do not want defining the groups |
| Descriptor | Variables used after clustering to explain, identify, or reach groups | Region, age band, channel, media use, acquisition source | Treating demographics as proof of needs |
| Excluded | Fields irrelevant or unsafe for this decision | Notes, free text, exact address, internal timestamps | “Everything just in case” |

There is no fixed maximum of basis variables (the public demo allows 30). With only a small number of customers, use far fewer.

### Numeric variables

Numeric basis variables are converted to numbers, median-imputed when missing, optionally clipped at the 1st and 99th percentiles, optionally transformed with `log1p` when non-negative and strongly right-skewed, then standardized to mean 0 and variance 1. Standardization prevents a euro-valued spend column from dominating a 1–10 rating only because of its units.

### Categorical variables

Categorical missing values become an explicit `Missing` level. Values are one-hot encoded and infrequent values are grouped. One-hot encoding gives each categorical field a constant active-row norm regardless of how many levels it has; the optional field weight then multiplies the full block. Distance in one-hot space is still a modeling choice, so use categorical bases only when their categories genuinely express the intended segmentation basis.

### Survey batteries and correlated variables

Several survey questions may measure the same underlying construct. Including all of them can double-count that construct. Inspect correlations, use a validated scale, or reduce a large battery with factor/PCA methods before upload. Automated survey-scale validation is outside v0.1.

### Outliers

Extreme values may be errors, isolated customers, or early signs of an emerging need. Segment Signal never silently deletes rows. The default clipping option limits their leverage while preserving every customer. Compare results with and without clipping and investigate consequential cases in the source system.

## Transaction log

Required columns:

- customer ID;
- purchase or event date;
- purchase amount.

An order ID is optional. When supplied, frequency counts unique orders and line items are summed before average order value is calculated; otherwise each row is treated as one order. The analysis reference date defaults to one day after the latest valid transaction.

The generated customer table contains:

- `recency_days`: days since the latest purchase (lower means more recent);
- `frequency`: number of unique orders or rows;
- `monetary_value`: total amount, including negative refunds if present;
- `average_order_value`: mean order total when order ID is supplied, otherwise mean row amount;
- `customer_tenure_days`: time from first to latest purchase.

Rows missing customer ID, date, or amount are excluded from RFM aggregation. If an order ID is selected, its remaining values must all be present; otherwise choose “count rows.” The app reports a failure if no usable rows remain. Clean refunds, cancellations, currencies, taxes, and date coverage according to your business definition before analysis.

## File formats

- CSV: one table; delimiters are detected.
- Excel: every nonempty sheet is available in the sidebar.
- JSON: either a list of row objects or an object whose values are named lists of rows.
- No built-in size limit when run locally; Streamlit's upload cap defaults to 10,000 MB (`SEGMENTSIGNAL_MAX_UPLOAD_MB`, or `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` in Docker).

Run locally, rows, cells and customers are limited only by the computer's memory; a file that does not fit produces a plain "not enough memory" message. Above 200 prepared model columns the app warns that distances between customers lose meaning. Above 25,000 customers, candidate comparison, stability checks and the final fit use a seeded random sample (25,000 by default, adjustable up to every customer), and every other customer is assigned to the nearest segment; preparation statistics, profiles and the customer-to-segment map always cover every customer. The Excel pack carries the map when it fits on one sheet; CSV and JSON always carry every customer. CSV is the fastest format for very large tables.

The public online demo (`SIGNAL_PUBLIC=1`) caps uploads at 200 MB (JSON 50 MB), expanded Excel content at 400 MB, files at 1 million rows and 10 million cells, and the analysis at 25,000 customers.

Executable files, archives, Parquet, database connections, and serialized Python models are not accepted.

## Minimum sample size

The software minimum is 30 customers, which is only enough for a small exploratory analysis. Reliable segmentation generally needs substantially more observations, especially with many variables, categories, or candidate groups. Sample coverage matters as much as raw count: a large convenience sample can still misrepresent the market.

## Privacy checklist

Before upload:

1. replace direct customer identity with a pseudonymous key;
2. remove names, email, phone, street address, and free text;
3. keep only variables necessary for the stated decision;
4. decide whether protected or sensitive attributes and proxies should be excluded;
5. confirm that the local or hosted deployment meets your organization’s requirements;
6. treat the exported customer-to-segment map as customer data.
