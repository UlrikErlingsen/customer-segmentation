# Data guide

SegmentSignal accepts customer-level tables and transaction logs. It never modifies the uploaded file.

## Customer-level table

Use one row per customer and one unique, nonblank customer ID.

You do not need recency, frequency, monetary value, or CLV columns. Needs surveys, attitude scales, demographics, product usage, boolean flags, and low-cardinality business categories can all be used. The question is whether the selected fields define differences that your marketing decision should respond to.

| Role | What belongs here | Examples | What to avoid |
|---|---|---|---|
| Customer ID | A stable pseudonymous key | `C00412`, loyalty ID | Name, email, phone number |
| Segmentation basis | Variables that express the differences the strategy should respond to | Needs, benefits sought, usage, recency, frequency, spend, engagement, price sensitivity | Randomly available fields, direct identifiers, downstream outcomes you do not want defining the groups |
| Descriptor | Variables used after clustering to explain, identify, or reach groups | Region, age band, channel, media use, acquisition source | Treating demographics as proof of needs |
| Excluded | Fields irrelevant or unsafe for this decision | Notes, free text, exact address, internal timestamps | “Everything just in case” |

The current release allows up to 30 basis variables. With only a small number of customers, use far fewer.

### Numeric variables

Numeric basis variables are converted to numbers, median-imputed when missing, optionally clipped at the 1st and 99th percentiles, optionally transformed with `log1p` when non-negative and strongly right-skewed, then standardized to mean 0 and variance 1. Standardization prevents a euro-valued spend column from dominating a 1–10 rating only because of its units.

### Categorical variables

Categorical missing values become an explicit `Missing` level. Values are one-hot encoded and infrequent values are grouped. One-hot encoding gives each categorical field a constant active-row norm regardless of how many levels it has; the optional field weight then multiplies the full block. Distance in one-hot space is still a modeling choice, so use categorical bases only when their categories genuinely express the intended segmentation basis.

### Survey batteries and correlated variables

Several survey questions may measure the same underlying construct. Including all of them can double-count that construct. Inspect correlations, use a validated scale, or reduce a large battery with factor/PCA methods before upload. Automated survey-scale validation is outside v0.1.

### Outliers

Extreme values may be errors, isolated customers, or early signs of an emerging need. SegmentSignal never silently deletes rows. The default clipping option limits their leverage while preserving every customer. Compare results with and without clipping and investigate consequential cases in the source system.

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
- Maximum local upload: 200 MB. JSON is limited to 50 MB.

Excel content may expand to at most 400 MB. A raw table may contain at most 1 million rows, a workbook at most 10 million cells, and the final customer-level analysis at most 25,000 customers by 200 prepared model columns. These are engineering limits, not promises that every maximum-size file will be fast on every computer.

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
