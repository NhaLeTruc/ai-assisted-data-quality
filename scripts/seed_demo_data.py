#!/usr/bin/env python3
"""Seed ChromaDB with demo data for the Data Quality Intelligence Platform.

Usage (Chroma running locally via docker compose up -d chroma):
    OPENAI_API_KEY=sk-... CHROMA_HOST=localhost CHROMA_PORT=8001 \\
        python scripts/seed_demo_data.py

Expected output:
    anomaly_patterns: 20
    remediation_playbooks: 10
    business_context: 10
    dq_rules: 12
"""

import json
import os
import sys
from pathlib import Path

# Ensure project root is importable as 'src' package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHROMA_HOST: str = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT: int = int(os.environ.get("CHROMA_PORT", "8001"))
DEMO_DATA_DIR = Path(os.environ.get("DEMO_DATA_DIR", "demo-data"))

_COLLECTIONS = ["anomaly_patterns", "dq_rules", "remediation_playbooks", "business_context"]

# ---------------------------------------------------------------------------
# Programmatically generated DQ rules (≥10 required by spec T-28)
# ---------------------------------------------------------------------------

DQ_RULES = [
    {
        "id": "DQR-ORDERS-001",
        "content": (
            "orders table completeness: customer_id must not be null on any row. "
            "customer_id links each order to the customer entity. "
            "A null spike indicates upstream API failure or a broken ingestion pipeline step. "
            "Baseline null rate: < 0.01%. Threshold: 0 nulls permitted."
        ),
        "metadata": {
            "rule_id": "DQR-ORDERS-001",
            "rule_type": "completeness",
            "applies_to": "orders",
            "column": "customer_id",
            "expectation": "expect_column_values_to_not_be_null",
            "severity": "critical",
            "threshold": "0.0",
        },
    },
    {
        "id": "DQR-ORDERS-002",
        "content": (
            "orders table validity: amount must be between 0.01 and 5000.00 USD. "
            "Values outside this range indicate data entry errors or currency conversion bugs. "
            "Threshold: 100% of rows must fall within [0.01, 5000.00]."
        ),
        "metadata": {
            "rule_id": "DQR-ORDERS-002",
            "rule_type": "validity",
            "applies_to": "orders",
            "column": "amount",
            "expectation": "expect_column_values_to_be_between",
            "severity": "high",
            "threshold": "1.0",
        },
    },
    {
        "id": "DQR-ORDERS-003",
        "content": (
            "orders table validity: status must be one of "
            "(shipped, delivered, pending, cancelled, returned). "
            "Any other value indicates an unmapped status from the order management system. "
            "Threshold: 100% of rows must have a valid status value."
        ),
        "metadata": {
            "rule_id": "DQR-ORDERS-003",
            "rule_type": "validity",
            "applies_to": "orders",
            "column": "status",
            "expectation": "expect_column_values_to_be_in_set",
            "severity": "high",
            "threshold": "1.0",
        },
    },
    {
        "id": "DQR-ORDERS-004",
        "content": (
            "orders table uniqueness: order_id must be unique across all rows. "
            "Duplicate order_ids indicate a replication bug or idempotency failure. "
            "Threshold: 0 duplicates permitted."
        ),
        "metadata": {
            "rule_id": "DQR-ORDERS-004",
            "rule_type": "uniqueness",
            "applies_to": "orders",
            "column": "order_id",
            "expectation": "expect_column_values_to_be_unique",
            "severity": "critical",
            "threshold": "0.0",
        },
    },
    {
        "id": "DQR-ORDERS-005",
        "content": (
            "orders table timeliness: order_date must fall within the past 365 days. "
            "Future dates indicate clock skew. Dates older than 365 days indicate pipeline replay. "
            "Threshold: 99.9% of rows must have order_date in acceptable range."
        ),
        "metadata": {
            "rule_id": "DQR-ORDERS-005",
            "rule_type": "timeliness",
            "applies_to": "orders",
            "column": "order_date",
            "expectation": "expect_column_values_to_be_between",
            "severity": "medium",
            "threshold": "0.999",
        },
    },
    {
        "id": "DQR-CUSTOMERS-001",
        "content": (
            "customers table completeness: customer_id and email must not be null. "
            "These are primary identity fields. Nulls break CRM integration and compliance reporting. "
            "Threshold: 0 nulls for customer_id; email null rate < 0.1%."
        ),
        "metadata": {
            "rule_id": "DQR-CUSTOMERS-001",
            "rule_type": "completeness",
            "applies_to": "customers",
            "column": "customer_id,email",
            "expectation": "expect_column_values_to_not_be_null",
            "severity": "critical",
            "threshold": "0.0",
        },
    },
    {
        "id": "DQR-CUSTOMERS-002",
        "content": (
            "customers table schema consistency: phone must have consistent length. "
            "Accepted: 10-digit domestic (5551234567) or 15-char international (+15551234567890). "
            "Mixed formats indicate schema drift from registration service changes. "
            "Threshold: length coefficient of variation < 0.2."
        ),
        "metadata": {
            "rule_id": "DQR-CUSTOMERS-002",
            "rule_type": "consistency",
            "applies_to": "customers",
            "column": "phone",
            "expectation": "expect_column_value_lengths_to_be_consistent",
            "severity": "warning",
            "threshold": "0.2",
        },
    },
    {
        "id": "DQR-PRODUCTS-001",
        "content": (
            "products table completeness: all columns must be non-null. "
            "The products table is clean reference data. Any null indicates supplier integration failure. "
            "Threshold: 0 nulls permitted in any column."
        ),
        "metadata": {
            "rule_id": "DQR-PRODUCTS-001",
            "rule_type": "completeness",
            "applies_to": "products",
            "column": "*",
            "expectation": "expect_column_values_to_not_be_null",
            "severity": "medium",
            "threshold": "0.0",
        },
    },
    {
        "id": "DQR-PRODUCTS-002",
        "content": (
            "products table validity: price must be > 0 and inventory_count must be >= 0. "
            "Negative prices indicate data corruption. Negative inventory counts are physically impossible. "
            "Threshold: 100% of rows must pass both conditions."
        ),
        "metadata": {
            "rule_id": "DQR-PRODUCTS-002",
            "rule_type": "validity",
            "applies_to": "products",
            "column": "price,inventory_count",
            "expectation": "expect_column_values_to_be_between",
            "severity": "high",
            "threshold": "1.0",
        },
    },
    {
        "id": "DQR-GLOBAL-001",
        "content": (
            "Global freshness rule: all production tables must have data fresher than their SLA. "
            "Detection: compare max(ingested_at) against current UTC time. "
            "SLAs: orders 2h, customers 4h, products 12h, revenue_report 2h, finance_dashboard 2h. "
            "Breaches trigger P1 escalation."
        ),
        "metadata": {
            "rule_id": "DQR-GLOBAL-001",
            "rule_type": "timeliness",
            "applies_to": "*",
            "column": "ingested_at",
            "expectation": "expect_table_row_count_to_be_between",
            "severity": "critical",
            "threshold": "varies_by_table",
        },
    },
    {
        "id": "DQR-GLOBAL-002",
        "content": (
            "Global volume rule: row count must not drop more than 20% vs the 7-day rolling average. "
            "A volume drop > 20% indicates pipeline failure, accidental deletes, or upstream data loss. "
            "Threshold: volume_change_pct > -0.20 for all production tables."
        ),
        "metadata": {
            "rule_id": "DQR-GLOBAL-002",
            "rule_type": "volume",
            "applies_to": "*",
            "column": "row_count",
            "expectation": "expect_table_row_count_to_be_between",
            "severity": "high",
            "threshold": "-0.20",
        },
    },
    {
        "id": "DQR-GLOBAL-003",
        "content": (
            "Global uniqueness rule: primary key columns must be unique in all production tables. "
            "Duplicate PKs cause downstream aggregation errors and incorrect joins. "
            "Applies to: orders.order_id, customers.customer_id, products.product_id. "
            "Threshold: 0 duplicates in any primary key column."
        ),
        "metadata": {
            "rule_id": "DQR-GLOBAL-003",
            "rule_type": "uniqueness",
            "applies_to": "*",
            "column": "primary_key",
            "expectation": "expect_column_values_to_be_unique",
            "severity": "critical",
            "threshold": "0.0",
        },
    },
]


def load_json(path: Path) -> list:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    import chromadb  # deferred: not installed in dev venv

    from src.rag.indexer import DataQualityIndexer  # deferred: same reason

    # Step 1: connect and verify Chroma is reachable
    print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    client.heartbeat()
    print("Connected.")

    # Step 2: delete and recreate all 4 collections (clean slate)
    print("\nResetting collections...")
    for name in _COLLECTIONS:
        try:
            client.delete_collection(name)
            print(f"  Deleted: {name}")
        except Exception:
            pass
        client.create_collection(name)
        print(f"  Created: {name}")

    indexer = DataQualityIndexer(CHROMA_HOST, CHROMA_PORT)

    # Step 3: anomalies.json → anomaly_patterns
    print("\nIndexing anomalies.json → anomaly_patterns...")
    anomalies = load_json(DEMO_DATA_DIR / "seed_data" / "anomalies.json")
    n = indexer.index_documents("anomaly_patterns", anomalies)
    print(f"  Indexed {n} documents")

    # Step 4: playbooks.json → remediation_playbooks
    print("Indexing playbooks.json → remediation_playbooks...")
    playbooks = load_json(DEMO_DATA_DIR / "seed_data" / "playbooks.json")
    n = indexer.index_documents("remediation_playbooks", playbooks)
    print(f"  Indexed {n} documents")

    # Step 5: business_context.json → business_context
    print("Indexing business_context.json → business_context...")
    biz = load_json(DEMO_DATA_DIR / "seed_data" / "business_context.json")
    n = indexer.index_documents("business_context", biz)
    print(f"  Indexed {n} documents")

    # Step 6: programmatic DQ rules → dq_rules
    print(f"Generating {len(DQ_RULES)} DQ rules → dq_rules...")
    n = indexer.index_documents("dq_rules", DQ_RULES)
    print(f"  Indexed {n} documents")

    # Step 7: print collection document counts
    print("\nCollection document counts:")
    stats = indexer.get_collection_stats()
    for collection_name, count in stats.items():
        print(f"  {collection_name}: {count}")

    print("\nSeeding complete.")


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
