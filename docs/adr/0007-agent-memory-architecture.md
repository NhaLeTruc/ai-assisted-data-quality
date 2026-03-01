# ADR-0007: Agent Memory Architecture

## Status

Accepted

## Date

2026-03-01

## Context

Agents need memory at multiple levels:

1. **Session memory**: Context within a single investigation workflow
2. **Persistent memory**: Historical patterns, learnings across sessions
3. **Shared memory**: Information exchange between agents in a workflow

Requirements:

- Agents should learn from past investigations
- Context should flow between agents without re-computation
- Memory should be queryable and filterable
- Performance must not degrade with growing history

## Decision

**Implement a two-layer memory architecture with explicit short-term and long-term stores.**

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Workflow Execution                      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Short-Term Memory (Session)                  │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │ WorkflowState (TypedDict in LangGraph)               │ │   │
│  │  │ - Current investigation context                      │ │   │
│  │  │ - Inter-agent messages and results                   │ │   │
│  │  │ - Decision rationale for audit trail                 │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              │ Checkpointing                     │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Long-Term Memory (Persistent)                │   │
│  │  ┌────────────────┐  ┌────────────────┐                  │   │
│  │  │  RAG Store     │  │  SQLite Store  │                  │   │
│  │  │  (Chroma)      │  │  (Structured)  │                  │   │
│  │  │                │  │                │                  │   │
│  │  │ - Anomaly      │  │ - Agent        │                  │   │
│  │  │   patterns     │  │   decisions    │                  │   │
│  │  │ - Resolutions  │  │ - Workflow     │                  │   │
│  │  │ - Playbooks    │  │   outcomes     │                  │   │
│  │  └────────────────┘  └────────────────┘                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Short-Term Memory (Session)

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict, List, Optional
from datetime import datetime

class WorkflowMemory(TypedDict):
    # Investigation context
    investigation_id: str
    started_at: str

    # Shared context between agents
    shared_context: dict  # Accumulated findings
    agent_messages: List[dict]  # Inter-agent communication

    # Decision audit trail
    decisions: List[dict]  # Each agent's decision with rationale

    # Performance tracking
    agent_latencies: dict  # {agent_name: ms}


# Checkpointing for session persistence
memory = SqliteSaver.from_conn_string("./data/checkpoints.db")
app = workflow.compile(checkpointer=memory)

# Resume from checkpoint
config = {"configurable": {"thread_id": investigation_id}}
result = await app.ainvoke(state, config)
```

### Long-Term Memory (Persistent)

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
import sqlite3
from uuid import uuid4

@dataclass
class AgentDecision:
    """Structured record of agent decision for learning."""
    decision_id: str
    investigation_id: str
    agent_name: str
    decision_type: str  # "detection", "diagnosis", "remediation"
    input_summary: str
    output_summary: str
    confidence: float
    was_correct: Optional[bool]  # Feedback after resolution
    created_at: datetime


class LongTermMemory:
    def __init__(self, db_path: str, rag_store):
        self.db = sqlite3.connect(db_path)
        self.rag = rag_store
        self._init_schema()

    def _init_schema(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                decision_id TEXT PRIMARY KEY,
                investigation_id TEXT,
                agent_name TEXT,
                decision_type TEXT,
                input_summary TEXT,
                output_summary TEXT,
                confidence REAL,
                was_correct INTEGER,
                created_at TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_agent
            ON agent_decisions(agent_name, decision_type)
        """)
        self.db.commit()

    def record_decision(self, decision: AgentDecision):
        """Store decision in structured store."""
        self.db.execute(
            "INSERT INTO agent_decisions VALUES (?,?,?,?,?,?,?,?,?)",
            (decision.decision_id, decision.investigation_id,
             decision.agent_name, decision.decision_type,
             decision.input_summary, decision.output_summary,
             decision.confidence, decision.was_correct,
             decision.created_at)
        )
        self.db.commit()

    def get_similar_decisions(
        self,
        agent_name: str,
        decision_type: str,
        input_description: str,
        k: int = 5
    ) -> List[dict]:
        """Retrieve similar past decisions using RAG."""
        results = self.rag.similarity_search(
            query=input_description,
            k=k * 2,  # Over-fetch for filtering
            filter={
                "agent_name": agent_name,
                "decision_type": decision_type
            }
        )

        # Enrich with structured data
        enriched = []
        for r in results[:k]:
            decision_id = r.metadata.get("decision_id")
            if decision_id:
                row = self.db.execute(
                    "SELECT * FROM agent_decisions WHERE decision_id = ?",
                    (decision_id,)
                ).fetchone()
                if row:
                    enriched.append({
                        "content": r.page_content,
                        "metadata": r.metadata,
                        "decision_record": row
                    })

        return enriched
```

### Memory-Aware Agent Template

```python
class MemoryAwareAgent:
    """Base class for agents that learn from history."""

    def __init__(self, name: str, memory: LongTermMemory):
        self.name = name
        self.memory = memory
        self.decision_type = name.replace("_agent", "")

    async def invoke(self, state: WorkflowMemory) -> dict:
        # 1. Retrieve relevant historical decisions
        similar_decisions = self.memory.get_similar_decisions(
            agent_name=self.name,
            decision_type=self.decision_type,
            input_description=self._summarize_input(state)
        )

        # 2. Include history in prompt
        history_context = self._format_history(similar_decisions)
        prompt = self._build_prompt(state, history_context)

        # 3. Execute agent logic
        result = await self._execute(prompt, state)

        # 4. Record decision for future learning
        self.memory.record_decision(AgentDecision(
            decision_id=str(uuid4()),
            investigation_id=state["investigation_id"],
            agent_name=self.name,
            decision_type=self.decision_type,
            input_summary=self._summarize_input(state),
            output_summary=self._summarize_output(result),
            confidence=result.get("confidence", 0.5),
            was_correct=None,  # Set later via feedback
            created_at=datetime.now()
        ))

        return result

    def _format_history(self, decisions: List[dict]) -> str:
        """Format historical decisions for prompt context."""
        if not decisions:
            return "No similar past decisions found."

        lines = ["Similar past decisions:"]
        for d in decisions[:3]:
            record = d.get("decision_record")
            was_correct = "correct" if record[7] else "incorrect" if record[7] is not None else "unknown"
            lines.append(f"- {d['content'][:200]}... (outcome: {was_correct})")

        return "\n".join(lines)
```

## Consequences

### Positive

- Clear separation between session and historical memory
- Agents can learn from past decisions over time
- Audit trail for all agent decisions
- Memory retrieval is efficient with combined indexing
- Supports feedback loop for continuous improvement

### Negative

- Two storage systems to maintain (SQLite + Chroma)
- Need feedback loop to mark decisions as correct/incorrect
- Memory growth needs periodic cleanup

### Neutral

- Memory access adds latency (~50-100ms per lookup)
- Schema changes require migration planning

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **RAG only** | Simpler; Single store | No structured queries; Harder to aggregate metrics | Need structured queries for decision analytics |
| **SQL only** | Familiar; Strong querying | No semantic search; Limited to exact matches | Semantic similarity crucial for pattern matching |
| **In-memory only** | Fastest; Simplest | Lost on restart; No historical learning | Demo needs to show learning capability |
| **LangGraph memory only** | Built-in; Zero config | Limited query capability; No semantic search | Need richer memory semantics |

## Implementation Notes

### Feedback Loop for Learning

```python
async def record_feedback(
    investigation_id: str,
    was_resolved: bool,
    resolution_notes: str,
    memory: LongTermMemory
):
    """Mark investigation decisions as correct/incorrect."""

    # Get all decisions from this investigation
    decisions = memory.db.execute(
        "SELECT decision_id FROM agent_decisions WHERE investigation_id = ?",
        (investigation_id,)
    ).fetchall()

    # Update correctness
    for (decision_id,) in decisions:
        memory.db.execute(
            "UPDATE agent_decisions SET was_correct = ? WHERE decision_id = ?",
            (was_resolved, decision_id)
        )

    memory.db.commit()

    # If resolved, add to RAG for future retrieval
    if was_resolved:
        memory.rag.add_documents([
            Document(
                page_content=resolution_notes,
                metadata={
                    "investigation_id": investigation_id,
                    "type": "resolution",
                    "created_at": datetime.now().isoformat()
                }
            )
        ])
```

### Memory Cleanup (Maintenance)

```python
def cleanup_old_memory(memory: LongTermMemory, days_to_keep: int = 90):
    """Remove old decisions to prevent unbounded growth."""
    cutoff = datetime.now() - timedelta(days=days_to_keep)

    # Keep decisions marked as correct (they're valuable)
    memory.db.execute("""
        DELETE FROM agent_decisions
        WHERE created_at < ?
        AND (was_correct IS NULL OR was_correct = 0)
    """, (cutoff,))

    memory.db.commit()
```

### Context Flow Between Agents

```python
def update_shared_context(state: WorkflowMemory, agent_name: str, findings: dict):
    """Add agent findings to shared context for downstream agents."""
    return {
        "shared_context": {
            **state.get("shared_context", {}),
            agent_name: findings
        },
        "agent_messages": state.get("agent_messages", []) + [{
            "from": agent_name,
            "timestamp": datetime.now().isoformat(),
            "content": findings
        }]
    }
```

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Checkpoints | SQLite local | PostgreSQL / Redis |
| Decisions DB | SQLite local | PostgreSQL with replication |
| RAG Store | Chroma local | Weaviate cluster |
| Cleanup | Manual | Scheduled job |
| Feedback | API endpoint | Integration with ticketing |

## References

- [LangGraph Persistence](https://langchain-ai.github.io/langgraph/how-tos/persistence/)
- [Agent Memory Engineering](https://www.oreilly.com/radar/why-multi-agent-systems-need-memory-engineering/)
- [Amazon Bedrock AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)
- Related: [ADR-0002](0002-multi-agent-framework.md), [ADR-0004](0004-rag-architecture.md)
