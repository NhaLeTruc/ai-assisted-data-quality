# ADR-0009: Deployment Architecture

## Status

Accepted

## Date

2026-03-01

## Context

The tech demo needs to be:

1. Easy to set up and run locally
2. Reproducible across different machines
3. Self-contained (minimal external dependencies)
4. Demonstrable in presentation settings

Components to deploy:

- LangGraph agent workflow (FastAPI)
- MCP servers (Great Expectations, Monte Carlo mock, Custom)
- Chroma vector database
- SQLite for structured storage
- Demo UI (Streamlit)

## Decision

**Use Docker Compose for local deployment with a single-command startup.**

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    demo-network (bridge)                     ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   app        │  │   mcp-gx     │  │   mcp-mc     │           │
│  │  (FastAPI)   │  │  (MCP:8081)  │  │  (MCP:8082)  │           │
│  │   :8000      │  │              │  │              │           │
│  │              │  │ Great        │  │ Monte Carlo  │           │
│  │ - LangGraph  │  │ Expectations │  │ (mock)       │           │
│  │ - REST API   │  │ (mock)       │  │              │           │
│  └──────┬───────┘  └──────────────┘  └──────────────┘           │
│         │                                                        │
│  ┌──────┴───────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   chroma     │  │   mcp-custom │  │   demo-ui    │           │
│  │   :8001      │  │  (MCP:8083)  │  │   :3000      │           │
│  │              │  │              │  │              │           │
│  │ Vector DB    │  │ Custom tools │  │ Streamlit    │           │
│  │              │  │              │  │ Dashboard    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                  │
│  Volumes:                                                        │
│  - ./data/chroma -> /data (Chroma persistence)                  │
│  - ./data/sqlite -> /data (SQLite databases)                    │
│  - ./demo-data   -> /demo-data (Sample datasets)                │
└─────────────────────────────────────────────────────────────────┘
```

### Docker Compose Configuration

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - MCP_GX_URL=http://mcp-gx:8081/mcp
      - MCP_MC_URL=http://mcp-mc:8082/mcp
      - MCP_CUSTOM_URL=http://mcp-custom:8083/mcp
    volumes:
      - ./data/sqlite:/data
      - ./demo-data:/demo-data
    depends_on:
      - chroma
      - mcp-gx
      - mcp-mc
      - mcp-custom
    networks:
      - demo-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - ./data/chroma:/chroma/chroma
    environment:
      - ANONYMIZED_TELEMETRY=false
    networks:
      - demo-network

  mcp-gx:
    build:
      context: ./mcp-servers/great-expectations
      dockerfile: Dockerfile
    ports:
      - "8081:8081"
    environment:
      - GX_DATA_DIR=/demo-data
    volumes:
      - ./demo-data:/demo-data
    networks:
      - demo-network

  mcp-mc:
    build:
      context: ./mcp-servers/monte-carlo-mock
      dockerfile: Dockerfile
    ports:
      - "8082:8082"
    networks:
      - demo-network

  mcp-custom:
    build:
      context: ./mcp-servers/custom
      dockerfile: Dockerfile
    ports:
      - "8083:8083"
    environment:
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
    networks:
      - demo-network

  demo-ui:
    build:
      context: ./ui
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - API_URL=http://app:8000
    depends_on:
      - app
    networks:
      - demo-network

networks:
  demo-network:
    driver: bridge

volumes:
  chroma-data:
  sqlite-data:
```

### Directory Structure

```
/home/bob/WORK/AI-assisted-data-quality/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI entrypoint
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── workflow.py      # LangGraph workflow
│   │   ├── orchestrator.py
│   │   ├── detection.py
│   │   ├── diagnosis.py
│   │   ├── lineage.py
│   │   ├── business_impact.py
│   │   ├── repair.py
│   │   └── validation.py
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── short_term.py
│   │   └── long_term.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── indexer.py
│   │   └── retriever.py
│   └── api/
│       ├── __init__.py
│       ├── routes.py
│       └── health.py
├── mcp-servers/
│   ├── great-expectations/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py
│   ├── monte-carlo-mock/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py
│   └── custom/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── server.py
├── ui/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── demo-data/
│   ├── sample_datasets/
│   │   ├── orders.csv
│   │   ├── customers.csv
│   │   └── products.csv
│   └── seed_data/
│       ├── anomalies.json
│       ├── playbooks.json
│       └── business_context.json
├── data/                     # Persisted data (gitignored)
│   ├── chroma/
│   └── sqlite/
├── scripts/
│   ├── seed_demo_data.py
│   └── reset_demo.sh
├── tests/
│   └── ...
└── docs/
    └── adr/
        └── ...
```

### Quick Start Commands

```bash
# Setup
cp .env.example .env
# Edit .env to add OPENAI_API_KEY

# Start everything
docker compose up -d

# View logs
docker compose logs -f app

# Access services
# - API: http://localhost:8000
# - API Docs: http://localhost:8000/docs
# - Demo UI: http://localhost:3000
# - Chroma: http://localhost:8001

# Reset demo (clear all data)
./scripts/reset_demo.sh

# Stop
docker compose down

# Stop and remove all data
docker compose down -v
```

## Consequences

### Positive

- One command to start entire stack
- Isolated environment prevents "works on my machine" issues
- Easy to reset demo state
- Portable across Mac, Linux, Windows (Docker Desktop)
- Services can be developed/tested independently

### Negative

- Docker Desktop required (licensing for some organizations)
- Resource usage (~4GB RAM for full stack)
- Initial image build takes time (~5-10 minutes first time)

### Neutral

- Need to manage OpenAI API key externally
- Logs consolidated but can be verbose

## Alternatives Considered

| Alternative | Pros | Cons | Why Not Chosen |
|-------------|------|------|----------------|
| **Local Python (no Docker)** | Simplest; No Docker needed | Environment inconsistency; Complex setup | Too many components to manage manually |
| **Kubernetes (local)** | Production-like; Scalable | Over-complex for demo; Steep learning curve | Minikube/Kind adds friction |
| **Cloud deployment** | No local resources needed | Costs money; Network dependency; Slower iteration | Local demo preferred for portability |
| **Dev containers** | VSCode integrated; Reproducible | VSCode-specific; Less portable | Docker Compose more universal |

## Implementation Notes

### Main Application Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Health Check Endpoint

```python
# src/api/health.py
from fastapi import APIRouter
import httpx

router = APIRouter()

@router.get("/health")
async def health_check():
    """Check health of all services."""
    checks = {
        "app": "healthy",
        "chroma": await check_service("http://chroma:8000/api/v1/heartbeat"),
        "mcp_gx": await check_service("http://mcp-gx:8081/health"),
        "mcp_mc": await check_service("http://mcp-mc:8082/health"),
        "mcp_custom": await check_service("http://mcp-custom:8083/health"),
    }

    all_healthy = all(v == "healthy" for v in checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "checks": checks
    }

async def check_service(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            return "healthy" if response.status_code == 200 else "unhealthy"
    except Exception:
        return "unreachable"
```

### Demo Reset Script

```bash
#!/bin/bash
# scripts/reset_demo.sh

set -e

echo "Stopping services..."
docker compose down

echo "Clearing persisted data..."
rm -rf ./data/chroma/*
rm -rf ./data/sqlite/*

echo "Starting services..."
docker compose up -d

echo "Waiting for services to be ready..."
sleep 10

echo "Seeding demo data..."
docker compose exec app python scripts/seed_demo_data.py

echo "Demo reset complete!"
echo "- API: http://localhost:8000"
echo "- UI: http://localhost:3000"
```

### Environment Variables

```bash
# .env.example

# Required
OPENAI_API_KEY=sk-...

# Optional (defaults shown)
CHROMA_HOST=chroma
CHROMA_PORT=8000
LOG_LEVEL=INFO
COST_TRACKING_ENABLED=true
```

## Demo vs Production

| Aspect | Demo (Docker Compose) | Production |
|--------|----------------------|------------|
| Orchestration | Docker Compose | Kubernetes |
| Scaling | Single instance each | Horizontal auto-scaling |
| Secrets | .env file | Vault / Secret Manager |
| Monitoring | Docker logs | Prometheus + Grafana |
| Networking | Bridge network | Service mesh (Istio) |
| Storage | Local volumes | Cloud storage + managed DB |
| CI/CD | None | GitHub Actions + ArgoCD |
| SSL | None | Cert-manager + ingress |

## References

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [FastAPI Docker Deployment](https://fastapi.tiangolo.com/deployment/docker/)
- [Streamlit Docker](https://docs.streamlit.io/deploy/tutorials/docker)
- Related: [ADR-0003](0003-mcp-integration-strategy.md)
