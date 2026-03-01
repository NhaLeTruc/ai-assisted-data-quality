# ADR-0003: MCP Integration Strategy

## Status

Accepted

## Date

2026-03-01

## Context

The Model Context Protocol (MCP) provides a standardized way to connect LLMs with external tools and data sources. For this platform, we need to integrate:

1. **Great Expectations** - Data validation and expectation suites
2. **Monte Carlo** - Data observability and anomaly detection
3. **Custom tools** - Platform-specific operations (lineage queries, remediation actions)

Key MCP considerations:

- **Transport**: stdio (local process) vs Streamable HTTP (remote)
- **Authentication**: OAuth 2.0 support in Streamable HTTP
- **Tool design**: Single-call workflows vs multi-round-trip patterns

Existing MCP integrations:

- `@davidf9999/gx-mcp-server` - Great Expectations MCP server (available on Smithery)
- Monte Carlo MCP - Currently in preview (March 2026)

## Decision

**Use Streamable HTTP transport with single-call tool design patterns.**

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph Agent Workflow                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │Detection │→ │Diagnosis │→ │ Impact   │→ │ Repair   │        │
│  │  Agent   │  │  Agent   │  │  Agent   │  │  Agent   │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       └─────────────┴─────────────┴─────────────┘                │
│                           │                                      │
│                    MCP Client Layer                              │
└───────────────────────────┬──────────────────────────────────────┘
                            │ Streamable HTTP
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │ Great Expect. │ │ Monte Carlo   │ │ Custom Tools  │
    │  MCP Server   │ │  MCP Server   │ │  MCP Server   │
    │    :8081      │ │    :8082      │ │    :8083      │
    └───────────────┘ └───────────────┘ └───────────────┘
```

### MCP Server Configuration

```json
{
  "mcpServers": {
    "great-expectations": {
      "transport": "streamable-http",
      "url": "http://localhost:8081/mcp",
      "auth": {
        "type": "bearer",
        "token_env": "GX_MCP_TOKEN"
      }
    },
    "monte-carlo": {
      "transport": "streamable-http",
      "url": "http://localhost:8082/mcp",
      "auth": {
        "type": "oauth2",
        "client_id_env": "MC_CLIENT_ID",
        "client_secret_env": "MC_CLIENT_SECRET"
      }
    },
    "custom-tools": {
      "transport": "streamable-http",
      "url": "http://localhost:8083/mcp"
    }
  }
}
```

### Tool Design: Single-Call Pattern

**Preferred - Complete operation in one call:**

```python
@mcp_tool
async def validate_dataset_quality(
    dataset_id: str,
    expectation_suite: str,
    return_failures_only: bool = True
) -> ValidationResult:
    """
    Validates dataset against expectation suite and returns
    complete results in a single call.
    """
    gx_context = get_gx_context()
    results = gx_context.run_checkpoint(
        checkpoint_name=f"{dataset_id}_{expectation_suite}",
        batch_request={"dataset_id": dataset_id}
    )
    return format_results(results, return_failures_only)
```

**Avoid - Multi-round-trip patterns:**

```python
# DON'T DO THIS - requires multiple calls and state management
@mcp_tool
def start_validation(dataset_id: str) -> str:
    return validation_job_id  # Requires follow-up calls

@mcp_tool
def check_validation_status(job_id: str) -> dict:
    return {"status": "running"}  # Polling pattern - inefficient
```

## Consequences

### Positive

- Remote deployment capability (not tied to local process)
- OAuth 2.0 support for production-grade authentication
- Stateless servers enable horizontal scaling
- Single-call design reduces latency and complexity
- Compatible with serverless deployment (Lambda, Cloud Run)
- Clear separation between agent logic and tool implementation

### Negative

- HTTP overhead vs stdio for local-only scenarios
- Need to manage MCP server infrastructure
- Great Expectations MCP server may need customization for our use case

### Neutral

- MCP specification is evolving; may need updates
- Monte Carlo MCP still in preview

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **stdio transport** | Simpler setup; No network overhead; Good for single-machine demo | Can't scale independently; No auth support; Tied to process lifecycle | Doesn't demonstrate production-ready architecture |
| **Direct API integration** | No MCP layer; Simpler debugging | No standardization; Each tool needs custom integration; Harder to swap implementations | MCP provides valuable abstraction; easier to add new tools |
| **SSE transport** | Server-push for real-time updates | One-way communication; Less suitable for request-response patterns | Most tool calls are request-response; SSE adds complexity |

## Implementation Notes

### LangChain MCP Integration

```python
from langchain_mcp import MCPToolkit

# Initialize MCP toolkit with multiple servers
toolkit = MCPToolkit(
    servers={
        "gx": "http://localhost:8081/mcp",
        "mc": "http://localhost:8082/mcp",
        "custom": "http://localhost:8083/mcp"
    }
)

# Get tools for agent
gx_tools = toolkit.get_tools(server="gx")
mc_tools = toolkit.get_tools(server="mc")
all_tools = toolkit.get_all_tools()
```

### Custom MCP Server Template (FastAPI)

```python
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

app = FastAPI()
mcp = FastMCP("custom-tools")

@mcp.tool()
async def analyze_data_lineage(
    table_name: str,
    depth: int = 3
) -> dict:
    """Trace data lineage upstream and downstream."""
    # Query lineage graph
    upstream = await get_upstream_dependencies(table_name, depth)
    downstream = await get_downstream_consumers(table_name, depth)
    return {
        "table": table_name,
        "upstream": upstream,
        "downstream": downstream,
        "impact_radius": len(downstream)
    }

@mcp.tool()
async def apply_remediation(
    anomaly_id: str,
    action: str,
    dry_run: bool = True
) -> dict:
    """Apply a remediation action for an anomaly."""
    if dry_run:
        return {"status": "dry_run", "would_apply": action}
    result = await execute_remediation(anomaly_id, action)
    return {"status": "applied", "result": result}

# Mount MCP server
app.mount("/mcp", mcp.get_app())
```

### MCP Tools Available

**Great Expectations MCP Server:**
- `load_dataset` - Load data from CSV, URL, or local file
- `create_expectation_suite` - Create validation suite
- `add_expectation` - Add validation rules
- `run_checkpoint` - Execute validation
- `get_validation_results` - Retrieve results

**Monte Carlo MCP Server (Preview):**
- `get_table_health` - Table freshness and volume metrics
- `get_anomalies` - Recent anomalies for a table
- `get_lineage` - Data lineage graph
- `query_catalog` - Search data catalog

**Custom MCP Server:**
- `analyze_data_lineage` - Deep lineage analysis
- `assess_business_impact` - SLA and consumer impact
- `apply_remediation` - Execute fixes (with dry-run)
- `get_similar_anomalies` - RAG-powered similarity search

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Deployment | Docker Compose (local) | Cloud Run / Lambda |
| Authentication | Bearer tokens | OAuth 2.0 + API Gateway |
| Scaling | Single instance | Auto-scaling per server |
| Monitoring | Docker logs | OpenTelemetry + cloud monitoring |
| Secrets | .env file | Secrets Manager / Vault |

## References

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [MCP Transports Documentation](https://modelcontextprotocol.info/docs/concepts/transports/)
- [Great Expectations MCP Server](https://smithery.ai/server/@davidf9999/gx-mcp-server)
- [Monte Carlo MCP Announcement](https://www.montecarlodata.com/blog-mcp-data-ai-observability/)
- Related: [ADR-0002](0002-multi-agent-framework.md), [ADR-0009](0009-deployment-architecture.md)
