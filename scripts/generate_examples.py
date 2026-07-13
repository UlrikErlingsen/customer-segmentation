"""Generate deterministic fictional data for onboarding and tests."""

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"


def clipped_normal(rng, mean, std, size, low=0, high=None):
    values = rng.normal(mean, std, size)
    return np.clip(values, low, high if high is not None else np.inf)


def generate_customers(seed: int = 2026) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    specs = [
        ("Loyal regulars", 180, 18, 13, 15, 3, 1050, 260, 8.0, 1.2, 0.18, 0.08, 8.5),
        ("Deal explorers", 150, 55, 25, 6, 2, 380, 135, 7.2, 1.5, 0.72, 0.14, 7.1),
        ("Dormant buyers", 150, 235, 75, 2, 1, 125, 65, 1.8, 0.9, 0.32, 0.10, 5.8),
        ("Premium occasionals", 120, 72, 35, 3, 1, 1280, 340, 4.2, 1.2, 0.09, 0.05, 8.0),
    ]
    rows: list[pd.DataFrame] = []
    customer_number = 1
    regions = np.array(["North", "South", "East", "West"])
    channels = np.array(["Email", "Paid social", "Organic", "Store"])
    sources = np.array(["Search", "Referral", "Social", "Retail", "Partner"])
    for latent, n, rec_m, rec_s, freq_m, freq_s, mon_m, mon_s, eng_m, eng_s, disc_m, ret_m, sat_m in specs:
        frame = pd.DataFrame(
            {
                "customer_id": [f"C{number:05d}" for number in range(customer_number, customer_number + n)],
                "recency_days": clipped_normal(rng, rec_m, rec_s, n, 0).round(),
                "purchase_frequency": clipped_normal(rng, freq_m, freq_s, n, 1).round(),
                "annual_spend": clipped_normal(rng, mon_m, mon_s, n, 20).round(2),
                "engagement_score": clipped_normal(rng, eng_m, eng_s, n, 0, 10).round(2),
                "discount_share": np.clip(rng.beta(max(disc_m * 10, 0.5), max((1 - disc_m) * 10, 0.5), n), 0, 1).round(3),
                "return_rate": np.clip(rng.beta(max(ret_m * 20, 0.5), max((1 - ret_m) * 20, 0.5), n), 0, 1).round(3),
                "satisfaction_score": clipped_normal(rng, sat_m, 0.8, n, 1, 10).round(1),
                "age": clipped_normal(rng, 41 if latent != "Deal explorers" else 32, 11, n, 18, 78).round(),
                "region": rng.choice(regions, n, p=[0.28, 0.23, 0.27, 0.22]),
                "preferred_channel": rng.choice(
                    channels,
                    n,
                    p=(
                        [0.48, 0.14, 0.23, 0.15]
                        if latent == "Loyal regulars"
                        else [0.22, 0.47, 0.23, 0.08]
                        if latent == "Deal explorers"
                        else [0.31, 0.17, 0.31, 0.21]
                    ),
                ),
                "acquisition_source": rng.choice(sources, n),
                "demo_truth": latent,
            }
        )
        rows.append(frame)
        customer_number += n
    customers = pd.concat(rows, ignore_index=True)
    customers.loc[rng.choice(len(customers), 18, replace=False), "engagement_score"] = np.nan
    customers.loc[rng.choice(len(customers), 12, replace=False), "preferred_channel"] = None
    return customers.sample(frac=1, random_state=seed).reset_index(drop=True)


def generate_transactions(customers: pd.DataFrame, seed: int = 2027) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = pd.Timestamp("2026-06-30")
    rows: list[dict[str, object]] = []
    order = 1
    for customer in customers.itertuples(index=False):
        count = max(1, int(customer.purchase_frequency))
        typical_amount = max(8, float(customer.annual_spend) / count)
        most_recent = max(0, int(customer.recency_days))
        older_offsets = most_recent + np.sort(rng.integers(0, 365, count))[::-1]
        older_offsets[-1] = most_recent
        for offset in older_offsets:
            rows.append(
                {
                    "customer_id": customer.customer_id,
                    "order_id": f"O{order:07d}",
                    "order_date": (end - pd.Timedelta(days=int(offset))).date().isoformat(),
                    "order_value": round(max(2, rng.lognormal(np.log(typical_amount), 0.28)), 2),
                    "channel": customer.preferred_channel or "Unknown",
                }
            )
            order += 1
    return pd.DataFrame(rows).sample(frac=1, random_state=seed).reset_index(drop=True)


def generate_needs_survey(seed: int = 2028) -> pd.DataFrame:
    """Create fictional, non-RFM customer survey and profile data."""
    rng = np.random.default_rng(seed)
    specs = [
        ("Convenience seekers", 160, 8.6, 6.2, 3.8, 8.1, 7.8, 36),
        ("Quality enthusiasts", 150, 6.4, 9.0, 3.1, 7.2, 6.3, 44),
        ("Budget pragmatists", 140, 6.8, 6.0, 8.8, 4.7, 5.4, 49),
    ]
    regions = np.array(["North", "South", "East", "West"])
    channels = np.array(["Email", "Paid social", "Organic search", "Store"])
    rows: list[pd.DataFrame] = []
    customer_number = 1
    for truth, n, convenience, quality, price, digital, novelty, age in specs:
        rows.append(
            pd.DataFrame(
                {
                    "customer_id": [f"S{number:05d}" for number in range(customer_number, customer_number + n)],
                    "need_convenience": clipped_normal(rng, convenience, 0.9, n, 1, 10).round(1),
                    "need_quality": clipped_normal(rng, quality, 0.8, n, 1, 10).round(1),
                    "price_sensitivity": clipped_normal(rng, price, 1.0, n, 1, 10).round(1),
                    "digital_comfort": clipped_normal(rng, digital, 1.1, n, 1, 10).round(1),
                    "interest_in_new_products": clipped_normal(rng, novelty, 1.1, n, 1, 10).round(1),
                    "age": clipped_normal(rng, age, 10, n, 18, 78).round(),
                    "household_size": np.clip(rng.poisson(2.1, n) + 1, 1, 7),
                    "region": rng.choice(regions, n),
                    "preferred_channel": rng.choice(channels, n),
                    "demo_truth": truth,
                }
            )
        )
        customer_number += n
    survey = pd.concat(rows, ignore_index=True)
    survey.loc[rng.choice(len(survey), 15, replace=False), "digital_comfort"] = np.nan
    return survey.sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    customers = generate_customers()
    transactions = generate_transactions(customers)
    survey = generate_needs_survey()
    customers.to_csv(EXAMPLES / "demo_customers.csv", index=False)
    transactions.to_csv(EXAMPLES / "demo_transactions.csv", index=False)
    survey.to_csv(EXAMPLES / "demo_needs_survey.csv", index=False)
    customers.drop(columns="demo_truth").head(20).to_excel(EXAMPLES / "customer_template.xlsx", index=False)
    print(f"Wrote {len(customers)} customers, {len(transactions)} transactions, and {len(survey)} survey rows")
