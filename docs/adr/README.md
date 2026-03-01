# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the Data Quality & Observability Intelligence Platform tech demo.

## Overview

The platform provides AI-driven anomaly detection and root cause analysis for data quality, featuring:
- Multi-agent architecture with 7 specialized agents
- MCP integration for data quality tools (Great Expectations, Monte Carlo)
- RAG-powered knowledge base for historical patterns and resolutions
- Intelligent alerting with context-aware remediation

## ADR Index

| # | Title | Status | Date |
|---|-------|--------|------|
| [0001](0001-adr-process.md) | ADR Process and Conventions | Accepted | 2026-03-01 |
| [0002](0002-multi-agent-framework.md) | Multi-Agent Framework Selection | Accepted | 2026-03-01 |
| [0003](0003-mcp-integration-strategy.md) | MCP Integration Strategy | Accepted | 2026-03-01 |
| [0004](0004-rag-architecture.md) | RAG Architecture Design | Accepted | 2026-03-01 |
| [0005](0005-vector-database-selection.md) | Vector Database Selection | Accepted | 2026-03-01 |
| [0006](0006-agent-orchestration-pattern.md) | Agent Orchestration Pattern | Accepted | 2026-03-01 |
| [0007](0007-agent-memory-architecture.md) | Agent Memory Architecture | Accepted | 2026-03-01 |
| [0008](0008-llm-provider-selection.md) | LLM Provider and Model Selection | Accepted | 2026-03-01 |
| [0009](0009-deployment-architecture.md) | Deployment Architecture | Accepted | 2026-03-01 |

## Technology Stack Summary

| Component | Technology | Purpose |
|-----------|------------|---------|
| Multi-Agent Framework | LangGraph 0.2+ | Workflow orchestration |
| RAG Indexing | LlamaIndex 0.11+ | Document processing |
| RAG Retrieval | LangChain 0.3+ | Retrieval chains |
| Vector Database | Chroma 0.5+ | Embedding storage |
| LLM Provider | OpenAI (GPT-4o, GPT-4o-mini) | Reasoning, classification |
| Embeddings | text-embedding-3-large | Semantic search |
| MCP Transport | Streamable HTTP | Tool integration |
| API Framework | FastAPI | REST API |
| Deployment | Docker Compose | Local demo |

## Agent Architecture

```
7 Specialized Agents:
├── Validation Agent     - Rule-based checks, schema validation
├── Detection Agent      - Pattern analysis, anomaly classification
├── Diagnosis Agent      - Root cause analysis, severity assessment
├── Lineage Agent        - Data provenance, impact propagation
├── Business Impact Agent - Business context, SLA impact
├── Orchestration Agent  - Workflow coordination, routing
└── Repair Agent         - Remediation suggestions, automated fixes
```

## Creating New ADRs

1. Use the next sequential number
2. Follow the Michael Nygard format (see ADR-0001)
3. Use kebab-case for filename: `NNNN-short-description.md`
4. Update this index

## References

- [Michael Nygard's ADR article](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- [ADR GitHub organization](https://adr.github.io/)
