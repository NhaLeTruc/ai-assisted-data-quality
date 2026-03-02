import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class AgentDecision:
    decision_id: str  # UUID4
    investigation_id: str
    agent_name: str  # e.g. "detection_agent"
    decision_type: str  # "validation"|"detection"|"diagnosis"|"lineage"|"business_impact"|"repair"
    input_summary: str  # Max 500 chars
    output_summary: str  # Max 500 chars
    confidence: float  # 0.0 - 1.0
    was_correct: bool | None  # None until feedback; True/False after
    created_at: datetime


_DDL = """
CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id       TEXT PRIMARY KEY,
    investigation_id  TEXT NOT NULL,
    agent_name        TEXT NOT NULL,
    decision_type     TEXT NOT NULL,
    input_summary     TEXT,
    output_summary    TEXT,
    confidence        REAL DEFAULT 0.5,
    was_correct       INTEGER,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decisions_agent
    ON agent_decisions(agent_name, decision_type);

CREATE INDEX IF NOT EXISTS idx_decisions_investigation
    ON agent_decisions(investigation_id);
"""


class LongTermMemory:
    def __init__(self, db_path: str, rag_retriever: Any = None) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self.rag_retriever = rag_retriever
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_DDL)
        self._conn.commit()

    def record_decision(self, decision: AgentDecision) -> None:
        """Persist an AgentDecision to SQLite."""
        was_correct = None if decision.was_correct is None else int(decision.was_correct)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO agent_decisions
                (decision_id, investigation_id, agent_name, decision_type,
                 input_summary, output_summary, confidence, was_correct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                decision.investigation_id,
                decision.agent_name,
                decision.decision_type,
                decision.input_summary[:500],
                decision.output_summary[:500],
                decision.confidence,
                was_correct,
                decision.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_similar_decisions(
        self,
        agent_name: str,
        decision_type: str,
        input_description: str,
        k: int = 5,
    ) -> list[dict]:
        """Return up to k past decisions matching agent_name and decision_type.

        Returns [] if no rag_retriever is configured (Phase 1 behaviour).
        With a retriever, SQL-filters by agent/type then re-ranks by semantic similarity.
        """
        if self.rag_retriever is None:
            return []

        rows = self._conn.execute(
            """
            SELECT decision_id, investigation_id, agent_name, decision_type,
                   input_summary, output_summary, confidence, was_correct, created_at
            FROM agent_decisions
            WHERE agent_name = ? AND decision_type = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (agent_name, decision_type),
        ).fetchall()

        if not rows:
            return []

        # Re-rank candidates by semantic similarity via RAG retriever
        try:
            similar_docs = self.rag_retriever.retrieve_similar_anomalies(
                input_description, anomaly_type=None
            )
            similar_ids = {doc.metadata.get("anomaly_id") for doc in similar_docs}
        except Exception:
            similar_ids = set()

        results = []
        for row in rows:
            results.append(
                {
                    "decision_id": row[0],
                    "investigation_id": row[1],
                    "agent_name": row[2],
                    "decision_type": row[3],
                    "input_summary": row[4],
                    "output_summary": row[5],
                    "confidence": row[6],
                    "was_correct": bool(row[7]) if row[7] is not None else None,
                    "created_at": row[8],
                    "_in_rag": row[1] in similar_ids,
                }
            )

        # Prioritise decisions whose investigation ID appeared in the RAG results
        results.sort(key=lambda d: (not d.pop("_in_rag"), d["created_at"]), reverse=False)
        return results[:k]

    def record_feedback(
        self,
        investigation_id: str,
        was_resolved: bool,
        resolution_notes: str,
    ) -> int:
        """Mark all decisions for an investigation as correct or incorrect."""
        cursor = self._conn.execute(
            "UPDATE agent_decisions SET was_correct = ? WHERE investigation_id = ?",
            (int(was_resolved), investigation_id),
        )
        self._conn.commit()
        return cursor.rowcount

    def cleanup_old_memory(self, days_to_keep: int = 90) -> int:
        """Delete unresolved decisions older than days_to_keep. Returns deleted count."""
        cutoff = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=days_to_keep)
        cursor = self._conn.execute(
            "DELETE FROM agent_decisions WHERE created_at < ? AND (was_correct IS NULL OR was_correct != 1)",
            (cutoff.isoformat(),),
        )
        self._conn.commit()
        return cursor.rowcount
