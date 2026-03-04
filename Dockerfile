FROM python:3.11-slim

WORKDIR /app

# Install torch (CPU-only) and sentence-transformers together so pip satisfies
# the torch dependency in one pass — avoids a second ~1 GB download when
# sentence-transformers is processed from requirements.txt.
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu \
    sentence-transformers

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY demo-data/ ./demo-data/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
