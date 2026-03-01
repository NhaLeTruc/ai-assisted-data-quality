# ADR-0006: Agent Orchestration Pattern

## Status

Accepted

## Date

2026-03-01

## Context

With 7 specialized agents (Validation, Detection, Diagnosis, Lineage, Business Impact, Orchestration, Repair), we need a pattern for:

- Coordinating agent execution order
- Handling conditional flows based on analysis results
- Managing parallel execution where possible
- Ensuring fault tolerance and graceful degradation

Common orchestration patterns:

1. **Manager Pattern**: Central orchestrator delegates to workers
2. **Hub-and-Spoke**: Central hub with bidirectional communication
3. **Pipeline**: Linear sequential processing
4. **Hierarchical**: Multi-level delegation tree
5. **Peer-to-Peer**: Agents communicate directly with each other

## Decision

**Use a hybrid Manager + Pipeline pattern with the Orchestration Agent as the central coordinator.**

### Pattern Overview

```
                            ┌─────────────────────┐
                            │  Orchestration      │
                            │      Agent          │
                            │  (Manager/Router)   │
                            └──────────┬──────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
              ▼                        ▼                        ▼
    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
    │   DETECTION     │    │   DIAGNOSIS     │    │   REMEDIATION   │
    │   PIPELINE      │    │   PIPELINE      │    │   PIPELINE      │
    └────────┬────────┘    └────────┬────────┘    └────────┬────────┘
             │                      │                      │
     ┌───────┴───────┐      ┌───────┴───────┐      ┌───────┴───────┐
     │               │      │               │      │               │
     ▼               ▼      ▼               ▼      ▼               ▼
┌─────────┐   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│Validation│   │Detection│ │Diagnosis│ │ Lineage │ │Business │ │ Repair  │
│  Agent   │   │  Agent  │ │  Agent  │ │  Agent  │ │ Impact  │ │  Agent  │
└─────────┘   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### Workflow Phases

| Phase | Pipeline | Agents | Trigger |
|-------|----------|--------|---------|
| 1 | Detection | Validation → Detection | Initial alert or scheduled check |
| 2 | Diagnosis | Diagnosis → Lineage | Anomaly detected (severity > info) |
| 3 | Remediation | Business Impact → Repair | Critical/High severity confirmed |

### LangGraph Implementation

```python
from langgraph.graph import StateGraph, END
from typing import Literal

class WorkflowState(TypedDict):
    # Input
    trigger: dict

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


def create_orchestration_graph() -> StateGraph:
    graph = StateGraph(WorkflowState)

    # Add nodes
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("validation", validation_node)
    graph.add_node("detection", detection_node)
    graph.add_node("diagnosis", diagnosis_node)
    graph.add_node("lineage", lineage_node)
    graph.add_node("business_impact", business_impact_node)
    graph.add_node("repair", repair_node)

    # Entry point
    graph.set_entry_point("orchestrator")

    # Orchestrator routes to appropriate pipeline
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "detection_pipeline": "validation",
            "diagnosis_pipeline": "diagnosis",
            "remediation_pipeline": "business_impact",
            "complete": END
        }
    )

    # Detection pipeline (sequential)
    graph.add_edge("validation", "detection")
    graph.add_conditional_edges(
        "detection",
        check_detection_result,
        {
            "anomaly_found": "orchestrator",
            "no_anomaly": "orchestrator"
        }
    )

    # Diagnosis pipeline
    graph.add_edge("diagnosis", "lineage")
    graph.add_edge("lineage", "orchestrator")

    # Remediation pipeline
    graph.add_edge("business_impact", "repair")
    graph.add_conditional_edges(
        "repair",
        check_repair_result,
        {
            "success": "orchestrator",
            "failure": "orchestrator",
            "needs_approval": "orchestrator"
        }
    )

    return graph.compile()
```

### Orchestrator Decision Logic

```python
def route_from_orchestrator(state: WorkflowState) -> str:
    """Central routing logic for the orchestrator."""

    # Initial trigger - start detection
    if state["current_phase"] == "initial":
        return "detection_pipeline"

    # After detection - check if anomaly found
    if state["current_phase"] == "detection_complete":
        if state["detection_result"] and state["detection_result"].get("anomaly_detected"):
            return "diagnosis_pipeline"
        return "complete"

    # After diagnosis - proceed to remediation based on severity
    if state["current_phase"] == "diagnosis_complete":
        if state["severity"] in ["critical", "high"]:
            return "remediation_pipeline"
        return "complete"  # Low severity - just log

    # After remediation - workflow complete
    if state["current_phase"] == "remediation_complete":
        return "complete"

    return "complete"
```

## Consequences

### Positive

- Central orchestrator provides clear control flow visibility
- Pipelines allow optimization of related agent sequences
- Easy to add new agents to existing pipelines
- LangGraph visualization shows complete workflow
- Supports both conditional branching and parallel execution
- Clear audit trail of decisions

### Negative

- Orchestrator can become a bottleneck for complex workflows
- More routing logic than pure pipeline approach
- Need to carefully manage state transitions

### Neutral

- Requires clear phase/state definitions
- Testing requires mocking multiple agents

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **Pure Pipeline** | Simpler; Linear flow | No conditional branching; Wasteful for info-only alerts | Severity-based routing is essential |
| **Pure Hub-and-Spoke** | Maximum flexibility; Any agent can talk to any other | Harder to reason about; Potential for cycles | Over-complicated for our use case |
| **Hierarchical** | Good for large agent teams; Clear delegation | Overkill for 7 agents; More latency from multi-level routing | Would add unnecessary complexity |
| **Peer-to-Peer** | Decentralized; Resilient | No central visibility; Debugging nightmare | Need clear audit trail for data quality |

## Implementation Notes

### Error Handling and Graceful Degradation

```python
def safe_agent_node(agent_fn):
    """Wrapper for graceful degradation."""
    async def wrapped(state: WorkflowState) -> dict:
        try:
            return await agent_fn(state)
        except Exception as e:
            return {
                "errors": state.get("errors", []) + [str(e)],
                f"{agent_fn.__name__}_result": {
                    "error": str(e),
                    "degraded": True
                }
            }
    return wrapped


# Apply to all agent nodes
validation_node = safe_agent_node(validation_agent)
detection_node = safe_agent_node(detection_agent)
# ... etc
```

### Parallel Execution (Future Optimization)

```python
# LangGraph supports parallel branches
from langgraph.graph import Branch

# Diagnosis and Lineage could run in parallel
graph.add_node("diagnosis_start", lambda s: s)  # Fork point

graph.add_conditional_edges(
    "diagnosis_start",
    lambda s: ["diagnosis", "lineage"],  # Return list for parallel
    {
        "diagnosis": "diagnosis",
        "lineage": "lineage"
    }
)

# Join after both complete
graph.add_node("diagnosis_join", join_results)
graph.add_edge("diagnosis", "diagnosis_join")
graph.add_edge("lineage", "diagnosis_join")
```

### Workflow Visualization

```python
# Generate workflow diagram
from langgraph.graph import StateGraph

graph = create_orchestration_graph()

# Export as Mermaid diagram
print(graph.get_graph().draw_mermaid())

# Or view in LangGraph Studio
# langgraph dev --port 8000
```

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Execution | Single-process, synchronous | Distributed, async |
| State | In-memory + SQLite checkpoint | Redis/PostgreSQL |
| Parallelism | Sequential within pipelines | Parallel where possible |
| Timeouts | None | Per-agent timeouts |
| Retries | None | Exponential backoff |
| Dead Letter | None | Queue for failed tasks |

## References

- [LangGraph Conditional Edges](https://langchain-ai.github.io/langgraph/how-tos/branching/)
- [Multi-Agent Orchestration Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- Related: [ADR-0002](0002-multi-agent-framework.md), [ADR-0007](0007-agent-memory-architecture.md)
