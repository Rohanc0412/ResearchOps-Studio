FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app/services/api/src:/app/services/orchestrator/src:/app/services/workers/src:/app/libraries/core/src:/app/libraries/observability/src:/app/libraries/citations/src:/app/libraries/connectors/src:/app/libraries/ingestion/src:/app/libraries/retrieval/src:/app/libraries/llm/src:/app/libraries/research_rules:/app/data

EXPOSE 8000

CMD ["python", "-m", "researchops_api.main"]
