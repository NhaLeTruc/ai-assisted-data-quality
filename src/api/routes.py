import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from src.agents.orchestrator import InvestigationTrigger
from src.agents.workflow import DataQualityState

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


async def _run_investigation(workflow, state: DataQualityState, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    async for _ in workflow.astream(state, config=config):
        pass


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    was_resolved: bool
    resolution_notes: str = ""


class RAGQueryRequest(BaseModel):
    query: str
    collection: str  # "anomaly_patterns"|"dq_rules"|"remediation_playbooks"|"business_context"
    anomaly_type: str | None = None
    severity: str | None = None
    table_name: str | None = None
    limit: int = 5


class RAGIndexRequest(BaseModel):
    collection: str
    documents: list[dict]  # Each: {"id", "content", "metadata"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/investigations", status_code=202)
async def start_investigation(
    trigger: InvestigationTrigger,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    investigation_id = str(uuid4())
    triggered_at = datetime.now(tz=UTC).isoformat()

    initial_state: DataQualityState = {
        "investigation_id": investigation_id,
        "triggered_at": triggered_at,
        "trigger": trigger.model_dump(),
        "validation_result": None,
        "detection_result": None,
        "diagnosis_result": None,
        "lineage_result": None,
        "business_impact": None,
        "remediation_plan": None,
        "remediation_result": None,
        "current_phase": "initial",
        "severity": None,
        "should_auto_remediate": False,
        "workflow_complete": False,
        "errors": [],
        "agent_latencies": {},
    }

    background_tasks.add_task(
        _run_investigation,
        request.app.state.workflow,
        initial_state,
        investigation_id,
    )

    return {
        "investigation_id": investigation_id,
        "status": "started",
        "triggered_at": triggered_at,
    }


@router.get("/investigations")
async def list_investigations(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    severity: str | None = None,
) -> list[dict]:
    db_path: str = request.app.state.long_term_memory._db_path
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT investigation_id FROM agent_decisions
            GROUP BY investigation_id
            ORDER BY MIN(created_at) DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    finally:
        conn.close()

    return [{"investigation_id": row[0]} for row in rows]


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str, request: Request) -> dict:
    workflow = request.app.state.workflow
    config = {"configurable": {"thread_id": investigation_id}}
    try:
        snapshot = workflow.get_state(config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc

    if snapshot is None or not snapshot.values:
        raise HTTPException(status_code=404, detail="Investigation not found")

    return snapshot.values


@router.post("/investigations/{investigation_id}/feedback")
async def submit_feedback(
    investigation_id: str,
    body: FeedbackRequest,
    request: Request,
) -> dict:
    updated = request.app.state.long_term_memory.record_feedback(
        investigation_id,
        body.was_resolved,
        body.resolution_notes,
    )
    return {"updated": True, "decisions_updated": updated}


@router.post("/rag/query")
async def rag_query(body: RAGQueryRequest, request: Request) -> dict:
    retriever = request.app.state.retriever
    collection = body.collection

    if collection == "anomaly_patterns":
        docs = retriever.retrieve_similar_anomalies(
            body.query,
            anomaly_type=body.anomaly_type,
            severity=body.severity,
        )
    elif collection == "dq_rules":
        docs = retriever.retrieve_dq_rules(
            table_name=body.table_name or "",
        )
    elif collection == "remediation_playbooks":
        docs = retriever.retrieve_playbook(
            body.query,
            anomaly_type=body.anomaly_type or "",
        )
    elif collection == "business_context":
        docs = retriever.retrieve_business_context(
            table_name=body.table_name or body.query,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown collection: {collection}")

    results = []
    for doc in docs[: body.limit]:
        results.append(
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": doc.metadata.get("relevance_score", 1.0),
            }
        )

    return {"results": results}


@router.post("/rag/index")
async def rag_index(body: RAGIndexRequest, request: Request) -> dict:
    indexer = request.app.state.indexer
    count = indexer.index_documents(body.collection, body.documents)
    return {"indexed": count}
