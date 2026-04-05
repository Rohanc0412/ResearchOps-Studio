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

# Install CUDA-enabled PyTorch for GPU embedding support.
# Torch >= 2.6 is required by transformers when loading non-safetensors checkpoints.
# Installed separately (not in requirements.prod.txt) so the CUDA build is used directly.
FROM prod-deps AS torch-deps
ARG TORCH_CUDA_INDEX_URL=https://download.pytorch.org/whl/cu124
ARG TORCH_VERSION=2.6.0
RUN (pip install --no-cache-dir --index-url ${TORCH_CUDA_INDEX_URL} torch==${TORCH_VERSION} \
     || pip install --no-cache-dir torch==${TORCH_VERSION}) && \
    pip install --no-cache-dir sentence-transformers>=2.7.0 && \
    python - <<'PY'
import sys
import torch

version = torch.__version__.split("+", 1)[0]
parts = version.split(".")
major = int(parts[0]) if parts else 0
minor = int(parts[1]) if len(parts) > 1 else 0
if (major, minor) < (2, 6):
    sys.exit(f"Expected torch>=2.6, got {torch.__version__}")
PY

FROM torch-deps AS dev-deps
COPY requirements.dev.txt .
RUN pip install --no-cache-dir -r requirements.dev.txt

FROM torch-deps AS production
COPY backend/. /app
ENV PYTHONPATH=/app/services/workers:/app/services/orchestrator:/app/services/api:/app/libs:/app/data
CMD ["python", "/app/services/workers/main.py"]

FROM dev-deps AS dev
COPY backend/. /app
ENV PYTHONPATH=/app/services/workers:/app/services/orchestrator:/app/services/api:/app/libs:/app/data
CMD ["python", "/app/services/workers/main.py"]
