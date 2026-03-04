"""Minimal Anthropic Messages API mock for integration tests.

Serves POST /v1/messages and returns tier-appropriate canned JSON responses.
Responses rotate per model tier so sequential calls within a workflow get the
right payload for each agent.
"""

import json
import socket
import threading
import time
from collections import deque

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Canned agent payloads (bare JSON strings — PydanticOutputParser accepts these)
# ---------------------------------------------------------------------------

VALIDATION_JSON = json.dumps(
    {
        "passed": False,
        "failed_expectations": ["expect_column_values_to_not_be_null"],
        "total_expectations": 5,
        "failure_count": 1,
        "details": {"evaluated": 5, "successful": 4},
        "summary": "Orders table has 1 null violation in customer_id column",
    }
)

DETECTION_JSON = json.dumps(
    {
        "anomaly_detected": True,
        "anomaly_type": "null_spike",
        "confidence": 0.91,
        "affected_tables": ["orders"],
        "affected_columns": ["customer_id"],
        "baseline_metric": None,
        "observed_metric": None,
        "deviation_percent": None,
        "similar_past_anomalies": [],
        "summary": "Null spike detected in orders.customer_id",
    }
)

DIAGNOSIS_JSON = json.dumps(
    {
        "severity": "high",
        "root_cause": "Upstream API deployment returning null customer_id values",
        "root_cause_category": "upstream_failure",
        "confidence": 0.87,
        "supporting_evidence": ["ETL job failure logs", "Null spike at 02:00 UTC"],
        "recommended_next_steps": ["Rollback API v2.3.1", "Trigger backfill"],
        "estimated_impact_records": None,
        "summary": "Upstream API deployment caused null spike in orders",
    }
)

LINEAGE_JSON = json.dumps(
    {
        "upstream_tables": ["api_gateway", "user_service"],
        "downstream_tables": [
            "revenue_report",
            "customer_segment_model",
            "marketing_pipeline",
            "finance_dashboard",
        ],
        "upstream_pipelines": ["etl_orders"],
        "downstream_consumers": ["analytics_team", "finance_team"],
        "impact_radius": 7,
        "critical_path_breached": True,
        "lineage_summary": "7 nodes affected; revenue_report SLA at risk",
    }
)

BUSINESS_IMPACT_JSON = json.dumps(
    {
        "affected_slas": [{"table": "orders", "sla_hours": 2.0, "breached": True}],
        "business_criticality": "critical",
        "estimated_financial_impact": "$50K/hour revenue at risk",
        "affected_teams": ["data_engineering", "finance"],
        "escalation_required": True,
        "escalation_contacts": ["oncall@company.com"],
        "business_summary": "Critical SLA breach affecting revenue reporting pipeline",
    }
)

REMEDIATION_JSON = json.dumps(
    {
        "recommended_action": "Rollback API deployment and backfill null customer_id rows",
        "action_type": "rollback",
        "steps": [
            "Rollback API to v2.3.0",
            "Identify affected rows (null customer_id)",
            "Backfill from source system",
            "Validate null rate returns to baseline",
            "Notify downstream consumers",
            "Close incident",
        ],
        "dry_run_safe": True,
        "estimated_duration_minutes": 90,
        "risk_level": "low",
        "playbook_reference": "PB-ROLLBACK-001",
        "alternative_actions": ["quarantine", "notify"],
    }
)

# ---------------------------------------------------------------------------
# Response queues — one deque per model tier; rotates on each call
# ---------------------------------------------------------------------------

TIER_QUEUES: dict[str, deque] = {
    "haiku": deque([VALIDATION_JSON]),
    "sonnet": deque([DETECTION_JSON, LINEAGE_JSON, REMEDIATION_JSON]),
    "opus": deque([DIAGNOSIS_JSON, BUSINESS_IMPACT_JSON]),
}


def reset_queues() -> None:
    """Reset response queues to initial state. Call between integration tests."""
    TIER_QUEUES["haiku"] = deque([VALIDATION_JSON])
    TIER_QUEUES["sonnet"] = deque([DETECTION_JSON, LINEAGE_JSON, REMEDIATION_JSON])
    TIER_QUEUES["opus"] = deque([DIAGNOSIS_JSON, BUSINESS_IMPACT_JSON])


# ---------------------------------------------------------------------------
# FastAPI mock app
# ---------------------------------------------------------------------------

mock_app = FastAPI(title="Anthropic API Mock")


@mock_app.post("/v1/messages")
async def messages(request: Request) -> JSONResponse:
    body = await request.json()
    model_id: str = body.get("model", "")

    if "haiku" in model_id:
        tier = "haiku"
    elif "sonnet" in model_id:
        tier = "sonnet"
    else:
        tier = "opus"

    queue = TIER_QUEUES[tier]
    payload = queue[0]
    queue.rotate(-1)  # advance: next call for this tier gets the next payload

    response_body = {
        "id": "msg_mock_001",
        "type": "message",
        "role": "assistant",
        "model": model_id,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 200},
        "content": [{"type": "text", "text": payload}],
    }
    return JSONResponse(response_body)


# ---------------------------------------------------------------------------
# Server lifecycle helpers
# ---------------------------------------------------------------------------

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 19876


def start_mock_server() -> None:
    """Start uvicorn in the current thread (blocking). Run in a daemon thread."""
    uvicorn.run(mock_app, host=MOCK_HOST, port=MOCK_PORT, log_level="error")


def wait_for_mock_server(timeout: float = 10.0) -> bool:
    """Block until the mock server accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((MOCK_HOST, MOCK_PORT), timeout=0.5)
            s.close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


_server_thread: threading.Thread | None = None


def ensure_mock_server_running() -> None:
    """Start the mock server once per process if not already running."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return
    _server_thread = threading.Thread(target=start_mock_server, daemon=True)
    _server_thread.start()
    if not wait_for_mock_server():
        raise RuntimeError("Mock Anthropic server did not start in time")
