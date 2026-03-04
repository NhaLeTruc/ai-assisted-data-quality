FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Dependency versions — override via .env → docker-compose build args
ARG TORCH_VERSION=2.10.0
ARG SENTENCE_TRANSFORMERS_VERSION=5.2.3
ARG LANGGRAPH_VERSION=0.2.55
ARG LANGGRAPH_CHECKPOINT_VERSION=2.1.2
ARG LANGGRAPH_CHECKPOINT_SQLITE_VERSION=2.0.11
ARG LANGCHAIN_CORE_VERSION=0.3.83
ARG LANGCHAIN_VERSION=0.3.27
ARG LANGCHAIN_ANTHROPIC_VERSION=0.3.4
ARG LANGCHAIN_CHROMA_VERSION=0.2.6
ARG LANGCHAIN_COMMUNITY_VERSION=0.3.31
ARG LLAMA_INDEX_CORE_VERSION=0.14.15
ARG LLAMA_INDEX_EMBEDDINGS_HF_VERSION=0.6.1
ARG CHROMADB_VERSION=1.5.2
ARG RANK_BM25_VERSION=0.2.2
ARG FASTMCP_VERSION=3.1.0
ARG FASTAPI_VERSION=0.135.1
ARG UVICORN_VERSION=0.41.0
ARG HTTPX_VERSION=0.28.1
ARG PYDANTIC_VERSION=2.12.5
ARG TENACITY_VERSION=9.1.4
ARG PYTHON_DOTENV_VERSION=1.2.2

# Pre-downloaded wheels (populated by: pip download --dest docker-wheels/ --extra-index-url ...)
# If wheels are present pip installs from them; missing packages are fetched from the internet.
COPY docker-wheels/ ./wheels/

RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --find-links ./wheels \
    torch==${TORCH_VERSION} \
    sentence-transformers==${SENTENCE_TRANSFORMERS_VERSION} \
    langgraph==${LANGGRAPH_VERSION} \
    langgraph-checkpoint==${LANGGRAPH_CHECKPOINT_VERSION} \
    langgraph-checkpoint-sqlite==${LANGGRAPH_CHECKPOINT_SQLITE_VERSION} \
    langchain-core==${LANGCHAIN_CORE_VERSION} \
    langchain==${LANGCHAIN_VERSION} \
    langchain-anthropic==${LANGCHAIN_ANTHROPIC_VERSION} \
    langchain-chroma==${LANGCHAIN_CHROMA_VERSION} \
    langchain-community==${LANGCHAIN_COMMUNITY_VERSION} \
    llama-index-core==${LLAMA_INDEX_CORE_VERSION} \
    llama-index-embeddings-huggingface==${LLAMA_INDEX_EMBEDDINGS_HF_VERSION} \
    chromadb==${CHROMADB_VERSION} \
    rank-bm25==${RANK_BM25_VERSION} \
    fastmcp==${FASTMCP_VERSION} \
    fastapi==${FASTAPI_VERSION} \
    "uvicorn[standard]==${UVICORN_VERSION}" \
    httpx==${HTTPX_VERSION} \
    pydantic==${PYDANTIC_VERSION} \
    tenacity==${TENACITY_VERSION} \
    python-dotenv==${PYTHON_DOTENV_VERSION}

RUN rm -rf ./wheels

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY demo-data/ ./demo-data/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
