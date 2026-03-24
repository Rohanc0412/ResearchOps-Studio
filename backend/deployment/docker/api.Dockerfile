FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    npm install -g @futurelab-studio/latest-science-mcp && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app/services/api:/app/services/orchestrator:/app/services/workers:/app/libs:/app/libs/research_rules:/app/data
ENV SCIENTIFIC_PAPERS_MCP_COMMAND=latest-science-mcp

EXPOSE 8000

CMD ["python", "-m", "main"]
