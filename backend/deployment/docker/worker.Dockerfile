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

ENV PYTHONPATH=/app/services/api/src:/app/services/orchestrator/src:/app/services/workers/src:/app/libs/core/src:/app/libs/observability/src:/app/libs/citations/src:/app/libs/connectors/src:/app/libs/ingestion/src:/app/libs/retrieval/src:/app/libs/llm/src:/app/libs/research_rules:/app/data

CMD ["python", "-m", "researchops_workers.main"]
