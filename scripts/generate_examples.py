"""Generate deterministic fictional data for onboarding and tests.

The generators live in ``segmentsignal.examples`` so the in-app demos work without this folder.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from segmentsignal.examples import generate_customers, generate_needs_survey, generate_transactions  # noqa: E402

EXAMPLES = ROOT / "examples"


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
