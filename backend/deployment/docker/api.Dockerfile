FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app/services/api/src:/app/services/orchestrator/src:/app/services/workers/src:/app/libs/core/src:/app/libs/observability/src:/app/libs/citations/src:/app/libs/connectors/src:/app/libs/ingestion/src:/app/libs/retrieval/src:/app/libs/llm/src:/app/libs/research_rules:/app/data

EXPOSE 8000

CMD ["python", "-m", "researchops_api.main"]
