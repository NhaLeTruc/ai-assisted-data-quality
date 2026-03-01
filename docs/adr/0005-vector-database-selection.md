# ADR-0005: Vector Database Selection

## Status

Accepted

## Date

2026-03-01

## Context

The RAG system (ADR-0004) requires a vector database for storing and querying embeddings. Requirements for the tech demo:

- Fast setup and minimal operational overhead
- Good developer experience for iteration
- Persistence across demo sessions
- Support for metadata filtering
- Integration with LangChain ecosystem

Future production requirements (not blocking demo):

- Horizontal scaling
- Knowledge graph capabilities for lineage
- Multi-tenancy support
- High availability

## Decision

**Use Chroma for the tech demo with a clear migration path to Weaviate for production.**

### Chroma Configuration

```python
import chromadb
from chromadb.config import Settings

# Persistent local storage for demo
client = chromadb.PersistentClient(
    path="./data/chroma",
    settings=Settings(
        anonymized_telemetry=False,
        allow_reset=True  # Enable reset for demo resets
    )
)

# Create collections with embedding function
from chromadb.utils import embedding_functions

openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.getenv("OPENAI_API_KEY"),
    model_name="text-embedding-3-large"
)

anomaly_collection = client.get_or_create_collection(
    name="anomaly_patterns",
    embedding_function=openai_ef,
    metadata={"hnsw:space": "cosine"}  # Cosine similarity
)
```

### Collection Structure

| Collection | Description | Key Metadata |
|------------|-------------|--------------|
| `anomaly_patterns` | Historical anomaly records | anomaly_type, severity, affected_tables |
| `dq_rules` | Data quality rules | rule_type, applies_to, owner_team |
| `remediation_playbooks` | Fix procedures | playbook_type, automation_level |
| `business_context` | Table/pipeline metadata | table_name, sla_hours, criticality |

### LangChain Integration

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

vector_store = Chroma(
    client=client,
    collection_name="anomaly_patterns",
    embedding_function=embeddings
)

# Add documents
vector_store.add_documents(documents)

# Similarity search with metadata filter
results = vector_store.similarity_search(
    query="null values in customer_id column",
    k=5,
    filter={"anomaly_type": "null_spike", "severity": "critical"}
)
```

## Consequences

### Positive

- Zero-config local setup (`pip install chromadb`)
- Built-in persistence with simple file-based storage
- Excellent LangChain integration
- Fast iteration during demo development
- Supports metadata filtering natively
- HNSW index provides good query performance

### Negative

- Not production-grade for scale (single-node only)
- No built-in knowledge graph capabilities
- Limited to ~10M vectors before performance degrades

### Neutral

- Embedding function tied to collection (consistent but inflexible)
- HNSW index is good default but not tunable

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **Weaviate** | Knowledge graphs; Production-ready; Multi-modal | Docker required; More complex setup; Overkill for demo | Production choice, but too heavy for demo iteration |
| **Pinecone** | Managed service; Highly scalable; Fast | Cloud dependency; Costs money; Network latency | Unnecessary for local demo; introduces cloud dependency |
| **pgvector** | Familiar PostgreSQL; Good for hybrid data | Requires PostgreSQL setup; Less optimized for vector search | Adds database dependency we don't otherwise need |
| **Qdrant** | Fast; Good filtering; Docker-friendly | Less mature ecosystem; Fewer integrations | Chroma has better LangChain integration |
| **FAISS** | Facebook's library; Very fast | No persistence built-in; No metadata filtering | Chroma wraps FAISS with better developer experience |

## Implementation Notes

### Demo Data Seeding

```python
def seed_demo_data():
    """Populate Chroma with sample data for demo."""
    sample_anomalies = [
        {
            "content": """Detected 45% null spike in orders.customer_id column.
            Normal null rate is 0.1%, observed 45.2% over 2 hours.
            Root cause: Upstream API returned nulls during deployment.
            Resolution: Rolled back API deployment, backfilled 12,000 records.""",
            "metadata": {
                "anomaly_id": "DQ-2026-0001",
                "anomaly_type": "null_spike",
                "severity": "critical",
                "affected_tables": ["orders"],
                "root_cause": "upstream_api_failure",
                "resolution": "rollback_and_backfill",
                "detected_at": "2026-02-15T10:30:00Z",
                "resolution_time_hours": 2.5
            }
        },
        {
            "content": """Schema drift detected in customers table.
            Column 'phone' changed from VARCHAR(20) to VARCHAR(15).
            Caused truncation of 847 international phone numbers.
            Resolution: Reverted schema, extended column to VARCHAR(25).""",
            "metadata": {
                "anomaly_id": "DQ-2026-0002",
                "anomaly_type": "schema_drift",
                "severity": "warning",
                "affected_tables": ["customers"],
                "root_cause": "uncoordinated_schema_change",
                "resolution": "schema_revert",
                "detected_at": "2026-02-20T14:15:00Z",
                "resolution_time_hours": 1.0
            }
        },
        # Additional samples...
    ]

    anomaly_collection.add(
        documents=[a["content"] for a in sample_anomalies],
        metadatas=[a["metadata"] for a in sample_anomalies],
        ids=[a["metadata"]["anomaly_id"] for a in sample_anomalies]
    )
```

### Migration Path to Weaviate

The LangChain abstraction allows swapping with minimal code changes:

```python
# Demo (Chroma)
from langchain_chroma import Chroma
vector_store = Chroma(
    collection_name="anomaly_patterns",
    embedding_function=embeddings
)

# Production (Weaviate) - same interface
from langchain_weaviate import Weaviate
vector_store = Weaviate(
    client=weaviate_client,
    index_name="AnomalyPatterns",
    text_key="content",
    embedding=embeddings
)
```

### Weaviate Production Benefits

| Feature | Chroma (Demo) | Weaviate (Production) |
|---------|---------------|----------------------|
| Knowledge Graphs | No | Yes - for lineage tracking |
| Horizontal Scaling | No | Yes - sharding support |
| Multi-tenancy | No | Yes - per-customer isolation |
| Hybrid Search | Via LangChain | Native BM25 + vector |
| GraphQL API | No | Yes |
| Backups | File copy | Snapshot API |

## Demo vs Production

| Aspect | Demo (Chroma) | Production (Weaviate) |
|--------|---------------|----------------------|
| Deployment | Local file | Kubernetes cluster |
| Scaling | Single node | Horizontal sharding |
| Features | Vector + metadata | + Knowledge graphs |
| Persistence | Local SQLite | Distributed storage |
| Backup | File copy | Snapshot API |
| Monitoring | None | Prometheus metrics |

## References

- [Chroma Documentation](https://docs.trychroma.com/)
- [LangChain Chroma Integration](https://python.langchain.com/docs/integrations/vectorstores/chroma)
- [Weaviate Documentation](https://weaviate.io/developers/weaviate)
- [Vector Database Comparison](https://www.datacamp.com/blog/the-top-5-vector-databases)
- Related: [ADR-0004](0004-rag-architecture.md)
