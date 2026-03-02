#!/usr/bin/env python3
"""Generate demo CSV datasets for the Data Quality Intelligence Platform.

Run from the project root:
    python scripts/generate_demo_data.py

Produces three files in demo-data/sample_datasets/ (gitignored):
  - orders.csv      10,000 rows; ~500 null customer_ids (null-spike demo)
  - customers.csv    5,000 rows; mixed 10/15-char phone format (schema-drift demo)
  - products.csv     1,000 rows; clean reference data

Files are deterministic (seed=42) so re-runs produce identical output.
"""

import csv
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

SEED = 42
TODAY = date(2026, 3, 2)
OUT_DIR = Path("demo-data/sample_datasets")


def _uuid() -> str:
    return str(uuid.UUID(int=random.getrandbits(128)))


def generate_orders(path: Path) -> None:
    statuses = (
        ["shipped"] * 35
        + ["delivered"] * 35
        + ["pending"] * 15
        + ["processing"] * 10
        + ["cancelled"] * 5
    )
    regions = ["US"] * 40 + ["EU"] * 30 + ["APAC"] * 20 + ["LATAM"] * 10
    null_positions = set(random.sample(range(10_000), 500))

    with open(path, "w", newline="\n") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "order_id",
                "customer_id",
                "product_id",
                "order_date",
                "amount",
                "status",
                "region",
            ],
            lineterminator="\n",
        )
        w.writeheader()
        for i in range(10_000):
            w.writerow(
                {
                    "order_id": _uuid(),
                    "customer_id": "" if i in null_positions else _uuid(),
                    "product_id": _uuid(),
                    "order_date": (TODAY - timedelta(days=random.randint(0, 89))).isoformat(),
                    "amount": f"{random.uniform(0.01, 5000.00):.2f}",
                    "status": random.choice(statuses),
                    "region": random.choice(regions),
                }
            )
    print(f"  orders.csv       → {path}  ({10_000:,} rows, 500 null customer_ids)")


def generate_customers(path: Path) -> None:
    first_names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank", "Iris", "Jack"]
    last_names = [
        "Smith",
        "Jones",
        "Williams",
        "Brown",
        "Davis",
        "Miller",
        "Wilson",
        "Moore",
        "Taylor",
        "Anderson",
    ]
    domains = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "example.com"]
    countries = ["US", "CA", "GB", "DE", "FR", "AU", "JP", "BR"]

    def phone_10() -> str:
        return f"{random.randint(200, 999)}{random.randint(1_000_000, 9_999_999)}"

    def phone_15() -> str:
        return f"+1{random.randint(200, 999)}{random.randint(1_000_000_000, 9_999_999_999)}"

    with open(path, "w", newline="\n") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "customer_id",
                "first_name",
                "last_name",
                "email",
                "phone",
                "country",
                "created_at",
            ],
            lineterminator="\n",
        )
        w.writeheader()
        for i in range(5_000):
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            w.writerow(
                {
                    "customer_id": _uuid(),
                    "first_name": fn,
                    "last_name": ln,
                    "email": f"{fn.lower()}.{ln.lower()}{i}@{random.choice(domains)}",
                    "phone": phone_10() if random.random() < 0.60 else phone_15(),
                    "country": random.choice(countries),
                    "created_at": (TODAY - timedelta(days=random.randint(0, 730))).isoformat(),
                }
            )
    print(f"  customers.csv    → {path}  ({5_000:,} rows, 60% 10-char / 40% 15-char phone)")


def generate_products(path: Path) -> None:
    categories = ["Electronics", "Clothing", "Food", "Books", "Sports", "Home", "Beauty", "Toys"]
    adjectives = ["Premium", "Essential", "Classic", "Modern", "Deluxe", "Ultra", "Basic", "Pro"]
    nouns = ["Widget", "Gadget", "Kit", "Set", "Pack", "Bundle", "Item", "Unit"]

    with open(path, "w", newline="\n") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "product_id",
                "name",
                "category",
                "price",
                "inventory_count",
                "last_updated",
            ],
            lineterminator="\n",
        )
        w.writeheader()
        for i in range(1_000):
            w.writerow(
                {
                    "product_id": _uuid(),
                    "name": f"{random.choice(adjectives)} {random.choice(nouns)} {i + 1:04d}",
                    "category": random.choice(categories),
                    "price": f"{random.uniform(0.99, 999.99):.2f}",
                    "inventory_count": random.randint(0, 10_000),
                    "last_updated": (TODAY - timedelta(days=random.randint(0, 30))).isoformat(),
                }
            )
    print(f"  products.csv     → {path}  ({1_000:,} rows, clean reference data)")


def main() -> None:
    random.seed(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating demo datasets …")
    generate_orders(OUT_DIR / "orders.csv")
    generate_customers(OUT_DIR / "customers.csv")
    generate_products(OUT_DIR / "products.csv")
    print("Done.")


if __name__ == "__main__":
    main()
