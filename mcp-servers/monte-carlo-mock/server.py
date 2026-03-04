import json
import logging
import os
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

DEMO_DATA_DIR = os.environ.get("DEMO_DATA_DIR", "/demo-data")

mcp = FastMCP("monte-carlo-mock")

# Load anomaly seed data at startup for deterministic responses
_anomalies: list = []
_anomalies_path = os.path.join(DEMO_DATA_DIR, "seed_data", "anomalies.json")
try:
    with open(_anomalies_path) as _f:
        _anomalies = json.load(_f)
    logger.info("Loaded %d anomalies from %s", len(_anomalies), _anomalies_path)
except Exception as _e:
    logger.warning("Could not load anomalies.json: %s", _e)

_CATALOG = [
    {
        "id": "orders",
        "type": "table",
        "description": "Order transaction fact table",
        "owner": "data-engineering",
    },
    {
        "id": "customers",
        "type": "table",
        "description": "Customer profile data",
        "owner": "identity-platform",
    },
    {
        "id": "products",
        "type": "table",
        "description": "Product catalogue reference data",
        "owner": "catalogue-engineering",
    },
    {
        "id": "revenue_report",
        "type": "table",
        "description": "Pre-aggregated revenue summaries",
        "owner": "data-analytics",
    },
    {
        "id": "customer_segment_model",
        "type": "table",
        "description": "ML-derived customer segmentation scores",
        "owner": "ml-platform",
    },
    {
        "id": "marketing_pipeline",
        "type": "table",
        "description": "Campaign events, ad spend, and attribution data",
        "owner": "growth-engineering",
    },
    {
        "id": "finance_dashboard",
        "type": "table",
        "description": "Near-real-time financial KPIs",
        "owner": "data-analytics",
    },
    {
        "id": "inventory_tracker",
        "type": "table",
        "description": "Real-time stock levels and reorder triggers",
        "owner": "operations-engineering",
    },
    {
        "id": "orders_archive",
        "type": "table",
        "description": "Historical order records partitioned by month",
        "owner": "data-engineering",
    },
    {
        "id": "user_activity_log",
        "type": "table",
        "description": "User interaction events from web and mobile",
        "owner": "product-engineering",
    },
]

_LINEAGE: dict = {
    "orders": {
        "upstream": ["api_gateway", "user_service", "product_service"],
        "downstream": [
            "revenue_report",
            "customer_segment_model",
            "marketing_pipeline",
            "finance_dashboard",
        ],
    },
    "customers": {
        "upstream": ["registration_service", "auth_service"],
        "downstream": [
            "customer_segment_model",
            "marketing_pipeline",
            "finance_dashboard",
            "crm_platform",
        ],
    },
    "products": {
        "upstream": ["supplier_integration_service"],
        "downstream": ["orders", "inventory_tracker", "ecommerce_storefront"],
    },
    "revenue_report": {
        "upstream": ["orders"],
        "downstream": ["finance_dashboard", "executive_reporting", "investor_portal"],
    },
    "customer_segment_model": {
        "upstream": ["orders", "customers"],
        "downstream": [
            "marketing_pipeline",
            "recommendation_engine",
            "customer_success_dashboard",
        ],
    },
}


@mcp.tool()
def get_table_health(table_name: str) -> dict:
    """Get health metrics for a table from the Monte Carlo data observability platform."""
    if table_name == "orders":
        return {
            "table": "orders",
            "freshness_hours": 1.2,
            "row_count": 10000,
            "volume_change_pct": -0.2,
            "status": "degraded",
        }
    return {
        "table": table_name,
        "freshness_hours": 0.5,
        "row_count": 50000,
        "volume_change_pct": 0.0,
        "status": "healthy",
    }


@mcp.tool()
def get_anomalies(table_name: str, hours_lookback: int = 24) -> list:
    """Get anomalies detected for a table within the lookback window."""
    if table_name != "orders":
        return []
    detected_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    return [
        {
            "anomaly_id": "DQ-2026-0001",
            "type": "null_spike",
            "severity": "critical",
            "detected_at": detected_at,
            "metric": 0.05,
            "baseline": 0.001,
        }
    ]


@mcp.tool()
def get_lineage(table_name: str, depth: int = 2) -> dict:
    """Get the data lineage graph for a table (upstream sources and downstream consumers)."""
    entry = _LINEAGE.get(
        table_name,
        {"upstream": ["source_system"], "downstream": ["analytics_warehouse"]},
    )
    upstream = entry["upstream"]
    downstream = entry["downstream"]
    return {
        "upstream": upstream,
        "downstream": downstream,
        "graph": {
            "nodes": [table_name, *upstream, *downstream],
            "edges": (
                [[src, table_name] for src in upstream] + [[table_name, dst] for dst in downstream]
            ),
        },
    }


@mcp.tool()
def query_catalog(search_term: str, limit: int = 10) -> list:
    """Search the data catalog for tables and datasets matching the search term."""
    term_lower = search_term.lower()
    results = [
        entry
        for entry in _CATALOG
        if term_lower in entry["id"].lower()
        or term_lower in entry["description"].lower()
        or term_lower in entry["owner"].lower()
    ]
    return (results or _CATALOG)[:limit]


_mcp_http_app = mcp.http_app()
app = FastAPI(title="Monte Carlo Mock MCP Server", lifespan=_mcp_http_app.lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "server": "monte-carlo-mock"}


app.mount("/", _mcp_http_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8082)
