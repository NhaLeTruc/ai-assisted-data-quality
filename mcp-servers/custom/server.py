import logging
import os
from datetime import UTC, datetime

from fastapi import FastAPI
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

CHROMA_HOST = os.environ.get("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))

mcp = FastMCP("custom-tools")

# ChromaDB client — lazy init so startup succeeds even if Chroma is unavailable
_chroma_client = None


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        try:
            import chromadb

            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            client.heartbeat()
            _chroma_client = client
            logger.info("Connected to ChromaDB at %s:%s", CHROMA_HOST, CHROMA_PORT)
        except Exception as e:
            logger.warning("ChromaDB connection failed: %s", e)
    return _chroma_client


_BUSINESS_CONTEXT: dict = {
    "orders": {
        "sla_hours": 2.0,
        "criticality": "critical",
        "owner_team": "data-engineering",
        "downstream_consumers": [
            "revenue_report",
            "finance_dashboard",
            "customer_segment_model",
            "marketing_pipeline",
        ],
    },
    "customers": {
        "sla_hours": 4.0,
        "criticality": "high",
        "owner_team": "identity-platform",
        "downstream_consumers": [
            "customer_segment_model",
            "marketing_pipeline",
            "finance_dashboard",
            "crm_platform",
        ],
    },
    "products": {
        "sla_hours": 12.0,
        "criticality": "medium",
        "owner_team": "catalogue-engineering",
        "downstream_consumers": ["orders", "inventory_tracker", "ecommerce_storefront"],
    },
    "revenue_report": {
        "sla_hours": 2.0,
        "criticality": "critical",
        "owner_team": "data-analytics",
        "downstream_consumers": [
            "finance_dashboard",
            "executive_reporting",
            "investor_portal",
        ],
    },
    "finance_dashboard": {
        "sla_hours": 2.0,
        "criticality": "critical",
        "owner_team": "data-analytics",
        "downstream_consumers": [
            "executive_reporting",
            "investor_portal",
            "finance_close_batch",
        ],
    },
}

# Impact config: criticality → anomaly_type → impact details
_IMPACT: dict = {
    "critical": {
        "null_spike": {
            "estimated_delay_hours": 2.5,
            "escalation_required": True,
            "teams": ["data-engineering", "product", "finance"],
        },
        "schema_drift": {
            "estimated_delay_hours": 4.0,
            "escalation_required": True,
            "teams": ["data-engineering", "platform"],
        },
        "volume_drop": {
            "estimated_delay_hours": 3.0,
            "escalation_required": True,
            "teams": ["data-engineering", "operations"],
        },
        "freshness_lag": {
            "estimated_delay_hours": 2.0,
            "escalation_required": True,
            "teams": ["data-engineering"],
        },
        "duplicate_records": {
            "estimated_delay_hours": 1.5,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
    },
    "high": {
        "null_spike": {
            "estimated_delay_hours": 1.5,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "schema_drift": {
            "estimated_delay_hours": 2.0,
            "escalation_required": False,
            "teams": ["data-engineering", "platform"],
        },
        "volume_drop": {
            "estimated_delay_hours": 1.0,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "freshness_lag": {
            "estimated_delay_hours": 1.0,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "duplicate_records": {
            "estimated_delay_hours": 0.5,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
    },
    "medium": {
        "null_spike": {
            "estimated_delay_hours": 0.5,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "schema_drift": {
            "estimated_delay_hours": 1.0,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "volume_drop": {
            "estimated_delay_hours": 0.5,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "freshness_lag": {
            "estimated_delay_hours": 0.5,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
        "duplicate_records": {
            "estimated_delay_hours": 0.25,
            "escalation_required": False,
            "teams": ["data-engineering"],
        },
    },
}


@mcp.tool()
def analyze_data_lineage(table_name: str, depth: int = 3) -> dict:
    """Analyze data lineage for a table including upstream sources and downstream consumers."""
    if table_name == "orders":
        return {
            "table": "orders",
            "upstream": ["api_gateway", "user_service"],
            "downstream": [
                "revenue_report",
                "customer_segment_model",
                "marketing_pipeline",
                "finance_dashboard",
            ],
            "impact_radius": 7,
            "critical_consumers": ["revenue_report"],
        }
    ctx = _BUSINESS_CONTEXT.get(table_name, {})
    downstream = ctx.get("downstream_consumers", ["analytics_warehouse"])
    return {
        "table": table_name,
        "upstream": ["source_system"],
        "downstream": downstream,
        "impact_radius": len(downstream) + 1,
        "critical_consumers": downstream[:1] if downstream else [],
    }


@mcp.tool()
def assess_business_impact(table_name: str, anomaly_type: str, severity: str) -> dict:
    """Assess the business impact of a data quality anomaly on SLAs and downstream teams."""
    ctx = _BUSINESS_CONTEXT.get(
        table_name,
        {
            "sla_hours": 24.0,
            "criticality": "medium",
            "downstream_consumers": [],
        },
    )
    criticality = ctx.get("criticality", "medium")
    downstream = ctx.get("downstream_consumers", [])
    sla_hours = ctx.get("sla_hours", 24.0)

    impact_tier = _IMPACT.get(criticality, _IMPACT["medium"])
    impact = impact_tier.get(anomaly_type, impact_tier.get("null_spike", {}))
    delay = impact.get("estimated_delay_hours", 1.0)
    escalation_required = impact.get("escalation_required", False)
    teams = impact.get("teams", ["data-engineering"])

    affected_slas = []
    if delay >= sla_hours:
        affected_slas.append(f"{table_name} SLA ({sla_hours}h)")
    for consumer in downstream[:3]:
        affected_slas.append(f"{consumer} SLA")

    return {
        "affected_slas": affected_slas,
        "teams": teams,
        "estimated_delay_hours": delay,
        "escalation_required": escalation_required,
        "criticality": criticality,
        "downstream_affected": downstream,
    }


@mcp.tool()
def apply_remediation(anomaly_id: str, action: str, dry_run: bool = True) -> dict:
    """Apply a remediation action. Defaults to dry_run=True for safety."""
    if dry_run:
        return {
            "status": "dry_run",
            "action": action,
            "anomaly_id": anomaly_id,
            "records_affected": 500,
            "rollback_available": True,
            "estimated_duration_minutes": 15,
        }
    return {
        "status": "applied",
        "action": action,
        "anomaly_id": anomaly_id,
        "records_affected": 500,
        "rollback_available": True,
        "completed_at": datetime.now(UTC).isoformat(),
    }


@mcp.tool()
def get_similar_anomalies(description: str, anomaly_type: str, limit: int = 5) -> list:
    """Retrieve similar past anomalies from the ChromaDB vector store."""
    client = _get_chroma()
    if client is None:
        return []

    try:
        collection = client.get_collection("anomaly_patterns")
        query_kwargs: dict = {"query_texts": [description], "n_results": limit}
        if anomaly_type:
            query_kwargs["where"] = {"anomaly_type": {"$eq": anomaly_type}}
        results = collection.query(**query_kwargs)

        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        output = []
        for i, (doc_id, metadata) in enumerate(zip(ids, metadatas, strict=False)):
            dist = distances[i] if i < len(distances) else 1.0
            # Convert cosine distance (0-2) to similarity (0-1)
            similarity = max(0.0, 1.0 - dist / 2.0)
            output.append(
                {
                    "anomaly_id": doc_id,
                    "similarity": round(similarity, 4),
                    "resolution": metadata.get("resolution", ""),
                    "resolution_time_hours": metadata.get("resolution_time_hours", 0),
                }
            )
        return output
    except Exception as e:
        logger.warning("ChromaDB query failed: %s", e)
        return []


app = FastAPI(title="Custom Tools MCP Server")


@app.get("/health")
async def health():
    return {"status": "ok", "server": "custom-tools"}


app.mount("/mcp", mcp.http_app())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8083)
