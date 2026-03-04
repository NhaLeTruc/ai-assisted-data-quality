FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

ARG FASTMCP_VERSION=3.1.0
ARG GREAT_EXPECTATIONS_VERSION=1.13.0
ARG PANDAS_VERSION=2.3.3
ARG FASTAPI_VERSION=0.135.1
ARG UVICORN_VERSION=0.41.0
ARG PYDANTIC_VERSION=2.12.5

RUN pip install --no-cache-dir \
    fastmcp==${FASTMCP_VERSION} \
    great-expectations==${GREAT_EXPECTATIONS_VERSION} \
    pandas==${PANDAS_VERSION} \
    fastapi==${FASTAPI_VERSION} \
    uvicorn==${UVICORN_VERSION} \
    pydantic==${PYDANTIC_VERSION}

COPY server.py .

EXPOSE 8081

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -f http://localhost:8081/health || exit 1

CMD ["python", "server.py"]
