FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    npm install -g @futurelab-studio/latest-science-mcp && \
    npm cache clean --force && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

FROM base AS prod-deps
COPY requirements.prod.txt .
RUN pip install --no-cache-dir -r requirements.prod.txt

FROM prod-deps AS dev-deps
COPY requirements.dev.txt .
RUN pip install --no-cache-dir -r requirements.dev.txt

FROM prod-deps AS production
COPY backend/. /app
ENV PYTHONPATH=/app/services/api:/app/services/orchestrator:/app/services/workers:/app/libs:/app/libs/research_rules:/app/data
EXPOSE 8000
CMD ["python", "-m", "main"]

FROM dev-deps AS dev
COPY backend/. /app
ENV PYTHONPATH=/app/services/api:/app/services/orchestrator:/app/services/workers:/app/libs:/app/libs/research_rules:/app/data
EXPOSE 8000
CMD ["python", "-m", "main"]
