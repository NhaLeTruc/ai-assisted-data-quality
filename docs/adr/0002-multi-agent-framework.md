# ADR-0002: Multi-Agent Framework Selection

## Status

Accepted

## Date

2026-03-01

## Context

The platform requires a multi-agent system with 7 specialized agents:

1. **Validation Agent** - Rule-based checks and schema validation
2. **Detection Agent** - Pattern analysis for anomaly detection
3. **Diagnosis Agent** - Root cause analysis and severity classification
4. **Lineage Agent** - Data provenance and impact propagation
5. **Business Impact Agent** - Contextual analysis and business impact
6. **Orchestration Agent** - Workflow coordination and task routing
7. **Repair Agent** - Automated remediation with verification

These agents need to:

- Collaborate on complex data quality investigations
- Maintain state across multi-step workflows
- Support branching logic (e.g., different analysis paths based on anomaly severity)
- Share context and findings efficiently

## Decision

**Use LangGraph as the primary multi-agent framework.**

Key implementation choices:

- **State Management**: TypedDict-based state with explicit schema
- **Graph Structure**: Directed graph with conditional edges
- **Agent Definition**: Each agent as a node with typed inputs/outputs
- **Checkpointing**: SQLite-based checkpointing for demo persistence

### State Definition

```python
from typing import TypedDict, List, Optional

class DataQualityState(TypedDict):
    # Investigation identity
    investigation_id: str

    # Input
    trigger: dict  # The incoming alert or check request

    # Detection pipeline results
    validation_result: Optional[dict]
    detection_result: Optional[dict]

    # Diagnosis pipeline results
    diagnosis_result: Optional[dict]
    lineage_result: Optional[dict]

    # Remediation pipeline results
    business_impact: Optional[dict]
    remediation_plan: Optional[dict]
    remediation_result: Optional[dict]

    # Control flow
    current_phase: str
    severity: Optional[str]
    should_auto_remediate: bool
    workflow_complete: bool
    errors: List[str]
```

### Graph Construction

```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(DataQualityState)

# Add agent nodes
workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("validation", validation_node)
workflow.add_node("detection", detection_node)
workflow.add_node("diagnosis", diagnosis_node)
workflow.add_node("lineage", lineage_node)
workflow.add_node("business_impact", business_impact_node)
workflow.add_node("repair", repair_node)

# Entry point
workflow.set_entry_point("orchestrator")

# Conditional routing based on severity
workflow.add_conditional_edges(
    "detection",
    route_by_severity,
    {
        "critical": "diagnosis",
        "warning": "business_impact",
        "info": END
    }
)
```

## Consequences

### Positive

- Explicit control over complex branching workflows
- Visual debugging via LangGraph Studio
- Strong typing with TypedDict prevents state corruption
- Native support for human-in-the-loop patterns
- Persistence and replay capability for debugging
- Clear audit trail of agent decisions

### Negative

- Steeper learning curve than CrewAI
- More boilerplate code for simple agent interactions
- Requires explicit state schema design upfront

### Neutral

- Python-native (TypeScript version available but less mature)
- Active development with frequent updates

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **CrewAI** | 40% faster time-to-production; Role-based patterns intuitive; Good for demo speed | Less control over complex branching; Implicit state management; Harder to debug complex flows | Our workflow has significant branching (severity-based routing, conditional remediation) that benefits from explicit graph structure |
| **AutoGen** | Best for conversational multi-agent; Good for debugging/testing dialogues | Optimized for chat, not workflow orchestration; Less suitable for structured data quality pipelines | Our agents don't primarily converse; they execute specialized tasks in a pipeline |
| **Custom Implementation** | Full control; No framework dependencies | High development cost; Reinventing solved problems | Not appropriate for demo timeline |

## Implementation Notes

### Agent Node Template

```python
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

def create_specialized_agent(name: str, tools: list, system_prompt: str):
    """Factory for creating specialized agents as graph nodes."""
    agent = create_react_agent(
        model=llm,
        tools=tools,
        state_modifier=system_prompt
    )

    async def node_fn(state: DataQualityState) -> dict:
        # Build context from state
        context = f"Investigation {state['investigation_id']}: {state['trigger']}"
        result = await agent.ainvoke({"messages": [HumanMessage(content=context)]})
        return {f"{name}_result": result}

    return node_fn
```

### Checkpointing for Persistence

```python
from langgraph.checkpoint.sqlite import SqliteSaver

# Enable persistence
memory = SqliteSaver.from_conn_string("./data/checkpoints.db")
app = workflow.compile(checkpointer=memory)

# Resume from checkpoint
config = {"configurable": {"thread_id": investigation_id}}
result = await app.ainvoke(state, config)
```

### Dependencies

```
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
```

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Execution | Single-process, synchronous | Distributed, async with Celery/Temporal |
| Checkpointing | SQLite | PostgreSQL or Redis |
| Scaling | Single instance | Kubernetes with agent replicas |
| Monitoring | LangGraph Studio | OpenTelemetry + Grafana |

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph Multi-Agent Workflows](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- Related: [ADR-0006](0006-agent-orchestration-pattern.md), [ADR-0007](0007-agent-memory-architecture.md)
