FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app/apps/api/src:/app/apps/orchestrator/src:/app/apps/workers/src:/app/packages/core/src:/app/packages/observability/src:/app/packages/citations/src:/app/packages/connectors/src:/app/packages/ingestion/src:/app/packages/retrieval/src:/app/packages/llm/src:/app/db

CMD ["python", "-m", "researchops_workers.main"]
