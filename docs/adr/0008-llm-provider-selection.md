# ADR-0008: LLM Provider and Model Selection

## Status

Accepted

## Date

2026-03-01

## Context

The multi-agent system requires LLM capabilities for:

1. **Reasoning**: Root cause analysis, impact assessment
2. **Tool use**: MCP tool invocation, structured output
3. **Embeddings**: RAG document indexing and retrieval
4. **Classification**: Severity determination, anomaly categorization

Considerations:

- Cost management for demo (avoid runaway API costs)
- Latency requirements (agents should respond quickly)
- Quality of reasoning for complex analysis
- Consistency of structured outputs

## Decision

**Use OpenAI as the primary provider with model tiering by agent complexity.**

### Model Tiering Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                     Model Tiering Strategy                       │
├─────────────────────────────────────────────────────────────────┤
│  Tier 1: Complex Reasoning (gpt-4o)                             │
│  - Diagnosis Agent: Root cause analysis                         │
│  - Business Impact Agent: Contextual business analysis          │
│  - Orchestration Agent: Complex routing decisions               │
│                                                                  │
│  Tier 2: Structured Tasks (gpt-4o-mini)                         │
│  - Detection Agent: Pattern matching, anomaly classification    │
│  - Lineage Agent: Graph traversal, impact propagation           │
│  - Repair Agent: Remediation plan generation                    │
│                                                                  │
│  Tier 3: Simple Tasks (gpt-4o-mini)                             │
│  - Validation Agent: Schema checks, rule evaluation             │
│                                                                  │
│  Embeddings: text-embedding-3-large                             │
│  - All RAG indexing and retrieval                               │
└─────────────────────────────────────────────────────────────────┘
```

### Configuration

```python
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# Model configurations
MODELS = {
    "tier1_reasoning": ChatOpenAI(
        model="gpt-4o",
        temperature=0.1,  # Low temp for consistency
        max_tokens=4096,
        timeout=60
    ),
    "tier2_structured": ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.0,  # Zero temp for structured output
        max_tokens=2048,
        timeout=30
    ),
    "tier3_simple": ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=1024,
        timeout=15
    ),
    "embeddings": OpenAIEmbeddings(
        model="text-embedding-3-large",
        dimensions=3072  # Full dimensionality
    )
}

# Agent to model mapping
AGENT_MODELS = {
    "orchestration": MODELS["tier1_reasoning"],
    "diagnosis": MODELS["tier1_reasoning"],
    "business_impact": MODELS["tier1_reasoning"],
    "detection": MODELS["tier2_structured"],
    "lineage": MODELS["tier2_structured"],
    "repair": MODELS["tier2_structured"],
    "validation": MODELS["tier3_simple"],
}
```

### Cost Estimation

```
Scenario: 100 anomaly investigations per demo session

Per Investigation (approximate tokens):
┌─────────────────────┬─────────┬─────────┬─────────┐
│ Agent               │ Input   │ Output  │ Calls   │
├─────────────────────┼─────────┼─────────┼─────────┤
│ Orchestration       │ 2,000   │ 500     │ 3       │
│ Diagnosis           │ 3,000   │ 1,000   │ 1       │
│ Business Impact     │ 2,500   │ 800     │ 1       │
│ Detection           │ 1,500   │ 300     │ 1       │
│ Lineage             │ 1,000   │ 500     │ 1       │
│ Repair              │ 2,000   │ 600     │ 1       │
│ Validation          │ 500     │ 200     │ 1       │
│ Embeddings          │ 500     │ -       │ 10      │
└─────────────────────┴─────────┴─────────┴─────────┘

Cost per Investigation:
- GPT-4o (Tier 1): ~$0.08
- GPT-4o-mini (Tier 2/3): ~$0.01
- Embeddings: ~$0.002
- Total: ~$0.10

100 Investigations = ~$10 per demo session
```

## Consequences

### Positive

- Model tiering optimizes cost/quality tradeoff
- OpenAI has best tool use and structured output support
- Single provider simplifies credential management
- Consistent API across all agents
- Excellent documentation and community support

### Negative

- OpenAI dependency (no fallback in demo)
- GPT-4o cost could add up with heavy demo usage
- Rate limits could impact parallel agent execution

### Neutral

- Need to manage API key securely
- Pricing may change; estimates are approximations

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **Anthropic Claude** | Excellent reasoning; Long context | Less mature tool use; Different API patterns | OpenAI tool use more reliable for structured output |
| **Local models (Ollama)** | Free; No API dependency; Privacy | Weaker reasoning; Slower; More setup | Quality insufficient for complex analysis agents |
| **Multi-provider** | Redundancy; Best model per task | Complex credential management; Inconsistent APIs | Over-engineered for demo |
| **Azure OpenAI** | Enterprise features; SLAs | More setup; Same models as OpenAI | Direct OpenAI simpler for demo |

## Implementation Notes

### Structured Output for Agents

```python
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional

class DetectionResult(BaseModel):
    """Structured output for Detection Agent."""
    anomaly_detected: bool = Field(description="Whether an anomaly was detected")
    anomaly_type: Optional[str] = Field(description="Type of anomaly if detected")
    confidence: float = Field(description="Confidence score 0-1")
    affected_tables: List[str] = Field(description="Tables affected by the anomaly")
    summary: str = Field(description="Brief summary of findings")


parser = PydanticOutputParser(pydantic_object=DetectionResult)

detection_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a data quality anomaly detector.
    Analyze the provided signals and determine if an anomaly exists.

    {format_instructions}"""),
    ("human", "Analyze these signals: {signals}")
]).partial(format_instructions=parser.get_format_instructions())
```

### Rate Limit Handling

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60)
)
async def invoke_with_retry(model, prompt):
    """Invoke model with exponential backoff on rate limits."""
    return await model.ainvoke(prompt)
```

### Cost Tracking Utility

```python
import tiktoken

class CostTracker:
    """Track API costs during demo sessions."""

    PRICING = {
        "gpt-4o": {"input": 0.005, "output": 0.015},  # per 1K tokens
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "text-embedding-3-large": {"input": 0.00013}
    }

    def __init__(self):
        self.total_cost = 0.0
        self.by_model = {}
        self.by_agent = {}

    def track(self, model: str, agent: str, input_tokens: int, output_tokens: int = 0):
        pricing = self.PRICING.get(model, {"input": 0, "output": 0})
        cost = (input_tokens / 1000 * pricing["input"] +
                output_tokens / 1000 * pricing.get("output", 0))

        self.total_cost += cost
        self.by_model[model] = self.by_model.get(model, 0) + cost
        self.by_agent[agent] = self.by_agent.get(agent, 0) + cost

    def report(self) -> dict:
        return {
            "total_cost": f"${self.total_cost:.4f}",
            "by_model": {k: f"${v:.4f}" for k, v in self.by_model.items()},
            "by_agent": {k: f"${v:.4f}" for k, v in self.by_agent.items()}
        }
```

### Environment Configuration

```python
# config.py
import os

class LLMConfig:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # Model settings
    TIER1_MODEL = "gpt-4o"
    TIER2_MODEL = "gpt-4o-mini"
    EMBEDDING_MODEL = "text-embedding-3-large"

    # Safety limits
    MAX_TOKENS_PER_REQUEST = 4096
    MAX_REQUESTS_PER_MINUTE = 60
    COST_ALERT_THRESHOLD = 5.00  # Alert if session exceeds $5
```

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Provider | Direct OpenAI API | LiteLLM proxy for fallback |
| Auth | Single API key | Per-tenant keys |
| Rate Limits | Basic retry | Token bucket + queueing |
| Cost Control | Tracking only | Hard limits + alerts |
| Caching | None | Redis response cache |
| Monitoring | Console logs | OpenTelemetry + dashboards |

## References

- [OpenAI Pricing](https://openai.com/pricing)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [LangChain OpenAI Integration](https://python.langchain.com/docs/integrations/chat/openai)
- Related: [ADR-0002](0002-multi-agent-framework.md)
