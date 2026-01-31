FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install CUDA-enabled PyTorch for GPU embedding support.
# Torch >= 2.6 is required by transformers when loading non-safetensors checkpoints.
ARG TORCH_CUDA_INDEX_URL=https://download.pytorch.org/whl/cu124
ARG TORCH_VERSION=2.6.0
RUN pip uninstall -y torch torchvision torchaudio && \
    (pip install --no-cache-dir --index-url ${TORCH_CUDA_INDEX_URL} torch==${TORCH_VERSION} \
     || pip install --no-cache-dir torch==${TORCH_VERSION}) && \
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

COPY . /app

ENV PYTHONPATH=/app/apps/api/src:/app/apps/orchestrator/src:/app/apps/workers/src:/app/packages/core/src:/app/packages/observability/src:/app/packages/citations/src:/app/packages/connectors/src:/app/packages/ingestion/src:/app/packages/retrieval/src:/app/packages/llm/src:/app/db

CMD ["python", "-m", "researchops_workers.main"]
