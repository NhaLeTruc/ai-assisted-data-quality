FROM python:3.11-slim

WORKDIR /app

ARG STREAMLIT_VERSION=1.55.0
ARG HTTPX_VERSION=0.28.1

RUN pip install --no-cache-dir \
    streamlit==${STREAMLIT_VERSION} \
    httpx==${HTTPX_VERSION}

COPY app.py .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
