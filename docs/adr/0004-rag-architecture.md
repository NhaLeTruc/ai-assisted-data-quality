# ADR-0004: RAG Architecture Design

## Status

Accepted

## Date

2026-03-01

## Context

The platform needs RAG (Retrieval-Augmented Generation) for:

1. **Historical anomaly patterns** - Similar past issues and their resolutions
2. **Data quality rules** - Organization-specific validation knowledge
3. **Remediation playbooks** - Step-by-step fix procedures
4. **Business context** - Table ownership, SLAs, downstream dependencies

Requirements:

- Fast retrieval for real-time anomaly investigation
- High accuracy for matching similar patterns
- Support for structured metadata filtering
- Ability to rank by recency and relevance
- Integration with LangGraph agents

## Decision

**Use a hybrid RAG architecture combining LlamaIndex for indexing and LangChain for retrieval chains.**

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Document Sources                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Anomaly  │  │ DQ Rules │  │Playbooks │  │ Business │        │
│  │ History  │  │   Docs   │  │   Docs   │  │ Context  │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
└───────┼─────────────┼─────────────┼─────────────┼───────────────┘
        │             │             │             │
        ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LlamaIndex Ingestion Pipeline                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Document   │→ │  Semantic   │→ │  Embedding  │              │
│  │   Loader    │  │  Chunking   │  │  Generation │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Chroma Vector Database                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Collection: anomaly_patterns                                 ││
│  │ Collection: dq_rules                                         ││
│  │ Collection: remediation_playbooks                            ││
│  │ Collection: business_context                                 ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  LangChain Retrieval Chain                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Hybrid    │→ │Cross-Encoder│→ │  Context    │              │
│  │   Search    │  │  Re-ranking │  │  Assembly   │              │
│  │(Vector+BM25)│  │             │  │             │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### Chunking Strategy

**Semantic Chunking with Max-Min Strategy:**

- Target chunk size: 500-700 tokens
- Overlap: 50 tokens (for context continuity)
- Split on semantic boundaries (paragraphs, sections)
- Preserve metadata linkage to source documents

```python
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.openai import OpenAIEmbedding

embed_model = OpenAIEmbedding(model="text-embedding-3-large")

splitter = SemanticSplitterNodeParser(
    buffer_size=1,  # sentences to group
    breakpoint_percentile_threshold=95,
    embed_model=embed_model
)

nodes = splitter.get_nodes_from_documents(documents)
```

### Hybrid Search Configuration

```python
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_chroma import Chroma

# Vector retriever (semantic similarity)
vector_store = Chroma(
    collection_name="anomaly_patterns",
    embedding_function=OpenAIEmbeddings(model="text-embedding-3-large")
)
vector_retriever = vector_store.as_retriever(search_kwargs={"k": 10})

# BM25 retriever (keyword matching)
bm25_retriever = BM25Retriever.from_documents(documents)
bm25_retriever.k = 10

# Ensemble with weights (favor semantic similarity)
ensemble_retriever = EnsembleRetriever(
    retrievers=[vector_retriever, bm25_retriever],
    weights=[0.7, 0.3]
)
```

### Cross-Encoder Re-ranking

```python
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain.retrievers.document_compressors import CrossEncoderReranker

# Cross-encoder for precision
cross_encoder = HuggingFaceCrossEncoder(
    model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"
)
reranker = CrossEncoderReranker(model=cross_encoder, top_n=5)

# Final retriever with re-ranking
compression_retriever = ContextualCompressionRetriever(
    base_compressor=reranker,
    base_retriever=ensemble_retriever
)
```

## Consequences

### Positive

- Hybrid search captures both semantic similarity and keyword matches
- Cross-encoder re-ranking significantly improves precision
- LlamaIndex excels at document processing; LangChain excels at chains
- Semantic chunking preserves meaning better than fixed-size chunks
- Metadata filtering enables precise queries by anomaly type, severity, date

### Negative

- Two framework dependencies (LlamaIndex + LangChain)
- Cross-encoder adds latency (~100-200ms per query)
- More complex than single-framework approach

### Neutral

- Requires careful metadata schema design
- Index updates need to be managed (not real-time)

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **LangChain only** | Single framework; Simpler dependency management | Weaker document processing; Less sophisticated chunking | LlamaIndex's semantic chunking is significantly better |
| **LlamaIndex only** | Single framework; Strong indexing | Less flexible retrieval chains; Weaker integration with LangGraph | LangChain retriever integrates better with our agent framework |
| **Vector-only search** | Simpler; Lower latency | Misses keyword-based matches; Worse for technical terms | Hybrid search improves recall for data quality terminology |
| **No re-ranking** | Lower latency; Simpler | Lower precision in top results | Re-ranking is critical for actionable retrieval |

## Implementation Notes

### Document Schema for Anomaly Patterns

```python
anomaly_document_schema = {
    "content": str,  # Description of the anomaly
    "metadata": {
        "anomaly_id": str,
        "anomaly_type": str,  # "null_spike", "schema_drift", "volume_drop"
        "severity": str,  # "critical", "warning", "info"
        "affected_tables": List[str],
        "root_cause": str,
        "resolution": str,
        "detected_at": datetime,
        "resolved_at": datetime,
        "resolution_time_hours": float,
        "tags": List[str]
    }
}
```

### Query-Time Metadata Filtering

```python
def retrieve_similar_anomalies(
    query: str,
    anomaly_type: Optional[str] = None,
    severity: Optional[str] = None,
    days_lookback: int = 90
) -> List[Document]:
    """Retrieve similar anomalies with metadata filtering."""
    filters = {}
    if anomaly_type:
        filters["anomaly_type"] = anomaly_type
    if severity:
        filters["severity"] = severity
    filters["detected_at"] = {
        "$gte": (datetime.now() - timedelta(days=days_lookback)).isoformat()
    }

    return compression_retriever.invoke(
        query,
        filter=filters
    )
```

### Collection Schemas

```python
collections = {
    "anomaly_patterns": {
        "description": "Historical anomaly records with resolutions",
        "metadata_fields": ["anomaly_type", "severity", "affected_tables",
                           "detected_at", "resolution_time_hours"]
    },
    "dq_rules": {
        "description": "Data quality rules and expectations",
        "metadata_fields": ["rule_type", "applies_to", "owner_team", "created_at"]
    },
    "remediation_playbooks": {
        "description": "Step-by-step remediation procedures",
        "metadata_fields": ["playbook_type", "automation_level",
                           "estimated_duration_minutes"]
    },
    "business_context": {
        "description": "Business metadata for tables and pipelines",
        "metadata_fields": ["table_name", "owner_team", "sla_hours",
                           "downstream_consumers", "business_criticality"]
    }
}
```

### Dependencies

```
llama-index>=0.11.0
llama-index-embeddings-openai>=0.2.0
langchain>=0.3.0
langchain-chroma>=0.1.0
langchain-community>=0.3.0
sentence-transformers>=3.0.0  # For cross-encoder
```

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Vector DB | Chroma (local) | Weaviate (knowledge graphs) |
| Embedding | OpenAI API | Fine-tuned model or OpenAI |
| Chunking | Pre-computed | Real-time ingestion pipeline |
| Re-ranking | HuggingFace local | Cohere Rerank or fine-tuned |
| Caching | None | Redis query cache |

## References

- [LlamaIndex Semantic Chunking](https://docs.llamaindex.ai/)
- [LangChain Ensemble Retriever](https://python.langchain.com/docs/modules/data_connection/retrievers/)
- [Hybrid Search Explained](https://weaviate.io/blog/hybrid-search-explained)
- Related: [ADR-0005](0005-vector-database-selection.md), [ADR-0007](0007-agent-memory-architecture.md)
