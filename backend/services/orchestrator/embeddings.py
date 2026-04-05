from __future__ import annotations

import atexit
import json
import math
import multiprocessing
import os
import threading
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from core.env import env_float, env_int

DEFAULT_BEDROCK_EMBED_MODEL = "amazon.titan-embed-text-v2:0"

# ---------------------------------------------------------------------------
# Shared embedding configuration resolvers
# Reads the canonical EMBED_* env vars only.
# ---------------------------------------------------------------------------


def resolve_embed_provider(llm_provider: str | None = None) -> str:
    """Return the embedding provider name.

    Resolution order:
    1. EMBED_PROVIDER env var
    2. Hard default: ``"local"``
    """
    _ = llm_provider
    raw = os.getenv("EMBED_PROVIDER")
    if raw and raw.strip():
        return raw.strip().lower()
    return "local"


def resolve_embed_model(provider: str) -> str:
    raw = os.getenv("BEDROCK_EMBED_MODEL") if provider == "bedrock" else os.getenv("EMBED_MODEL")
    if raw and raw.strip():
        return raw.strip()
    if provider == "bedrock":
        return DEFAULT_BEDROCK_EMBED_MODEL
    if provider in {"local", "sentence-transformers", "bge"}:
        return "BAAI/bge-m3"
    return "text-embedding-3-small"


def resolve_bedrock_embed_region_name() -> str | None:
    raw = os.getenv("AWS_REGION")
    if raw and raw.strip():
        return raw.strip()
    return None


def resolve_bedrock_embed_batch_size() -> int:
    return env_int("BEDROCK_EMBED_BATCH_SIZE", 8, min_value=1)


def resolve_bedrock_embed_concurrency() -> int:
    return env_int("BEDROCK_EMBED_CONCURRENCY", 4, min_value=1)


def resolve_bedrock_embed_timeout_seconds() -> float:
    return env_float("BEDROCK_EMBED_TIMEOUT_SECONDS", 60.0, min_value=1.0)


def resolve_embed_device() -> str:
    raw = os.getenv("EMBED_DEVICE")
    if raw and raw.strip():
        return raw.strip()
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def resolve_embed_dtype(device: str) -> str | None:
    raw = os.getenv("EMBED_DTYPE")
    if raw and raw.strip():
        return raw.strip().lower()
    if device.startswith("cuda"):
        return "float16"
    return None


def resolve_embed_normalize() -> bool:
    raw = os.getenv("EMBED_NORMALIZE")
    if not raw:
        return True
    return raw.strip().lower() not in {"0", "false", "no"}


def resolve_embed_trust_remote_code(model_name: str) -> bool:
    raw = os.getenv("EMBED_TRUST_REMOTE_CODE")
    if raw and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes"}
    return "bge-m3" in model_name.lower()


def resolve_embed_max_seq_len() -> int | None:
    raw = os.getenv("EMBED_MAX_SEQ_LEN")
    if not raw or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def resolve_embed_workers() -> int:
    """Return the configured hard cap on embedding pool workers (default 3)."""
    raw = os.getenv("EMBED_WORKERS")
    if raw and raw.strip():
        try:
            value = int(raw)
            return max(1, value)
        except ValueError:
            pass
    return 3


_EMBED_CLIENTS: dict[tuple, SentenceTransformerEmbedClient] = {}
_EMBED_MODEL_CONFIGS: dict[str, set[tuple]] = {}
_HF_CLIENTS: dict[tuple, HuggingFaceEmbedClient] = {}
_BEDROCK_CLIENTS: dict[tuple, BedrockEmbedClient] = {}


@dataclass
class SentenceTransformerEmbedClient:
    model_name: str
    device: str
    normalize_embeddings: bool
    max_seq_length: int | None
    dtype: str | None
    trust_remote_code: bool

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(
                "sentence-transformers is required for local embeddings. Install it via pip."
            ) from exc

        model_kwargs = {}
        dtype = None
        if self.dtype:
            try:
                import torch

                dtype = getattr(torch, self.dtype)
                model_kwargs["dtype"] = dtype
            except Exception:
                pass

        init_kwargs = {"device": self.device}
        if model_kwargs:
            init_kwargs["model_kwargs"] = model_kwargs
        if self.trust_remote_code:
            init_kwargs["trust_remote_code"] = True
        try:
            self._model = SentenceTransformer(self.model_name, **init_kwargs)
        except TypeError:
            init_kwargs.pop("model_kwargs", None)
            init_kwargs.pop("trust_remote_code", None)
            self._model = SentenceTransformer(self.model_name, **init_kwargs)
            if dtype is not None:
                self._model = self._model.to(dtype=dtype)
        if self.max_seq_length:
            self._model.max_seq_length = self.max_seq_length

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Restore to configured device if the model was offloaded to CPU between runs.
        try:
            current = str(next(self._model.parameters()).device)
            if not current.startswith(self.device):
                self._model.to(self.device)
        except Exception:
            pass
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()


@dataclass
class HuggingFaceEmbedClient:
    model_name: str
    base_url: str
    api_key: str
    timeout_seconds: float
    wait_for_model: bool

    def __post_init__(self) -> None:
        import httpx

        self._http = httpx.Client(timeout=self.timeout_seconds)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, Any] = {"inputs": texts}
        if self.wait_for_model:
            payload["options"] = {"wait_for_model": True}
        try:
            data = self._post_json(payload)
            return _coerce_hf_embeddings(data, expected=len(texts))
        except Exception as exc:
            try:
                import httpx

                is_timeout = isinstance(exc, httpx.ReadTimeout)
            except Exception:
                is_timeout = False
            if is_timeout and len(texts) > 1:
                mid = len(texts) // 2
                return self.embed_texts(texts[:mid]) + self.embed_texts(texts[mid:])
            raise

    def _post_json(self, payload: dict[str, Any]) -> Any:
        base = self.base_url.rstrip("/")
        url = f"{base}/{self.model_name}/pipeline/feature-extraction"
        headers = {"authorization": f"Bearer {self.api_key}"}
        resp = self._http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


@dataclass
class BedrockEmbedClient:
    model_name: str
    region_name: str
    batch_size: int
    max_concurrency: int
    timeout_seconds: float
    dimensions: int | None = None
    _runtime_client: Any | None = None

    def _get_runtime_client(self) -> Any:
        if self._runtime_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "Bedrock embeddings require boto3. Install backend dependencies with boto3>=1.34."
                ) from exc
            config = None
            try:
                from botocore.config import Config

                config = Config(
                    read_timeout=self.timeout_seconds,
                    connect_timeout=self.timeout_seconds,
                )
            except Exception:
                config = None
            kwargs: dict[str, Any] = {"region_name": self.region_name}
            if config is not None:
                kwargs["config"] = config
            self._runtime_client = boto3.client("bedrock-runtime", **kwargs)
        return self._runtime_client

    def _invoke_text(self, text: str) -> list[float]:
        payload = {"inputText": text}
        response = self._get_runtime_client().invoke_model(
            modelId=self.model_name,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        data = self._read_response_json(response)
        embedding = self._extract_embedding(data)
        if self.dimensions is None:
            self.dimensions = len(embedding)
        elif embedding and len(embedding) != self.dimensions:
            raise RuntimeError(
                "Bedrock embeddings dimension mismatch: "
                f"expected {self.dimensions} got {len(embedding)}"
            )
        return embedding

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = [self._invoke_text(text) for text in texts]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Bedrock embeddings count mismatch: expected {len(texts)} got {len(embeddings)}"
            )
        return embeddings

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = [
            texts[start : start + self.batch_size]
            for start in range(0, len(texts), self.batch_size)
        ]
        batch_results: list[list[list[float]] | None] = [None] * len(batches)
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            futures = {
                executor.submit(self._embed_batch, batch): batch_idx
                for batch_idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx = futures[future]
                embeddings = future.result()
                expected = len(batches[batch_idx])
                if len(embeddings) != expected:
                    raise RuntimeError(
                        f"Bedrock embeddings count mismatch: expected {expected} got {len(embeddings)}"
                    )
                batch_results[batch_idx] = embeddings

        ordered: list[list[float]] = []
        for embeddings in batch_results:
            if embeddings is None:
                raise RuntimeError(
                    "Bedrock embeddings request did not return all batch results."
                )
            ordered.extend(embeddings)
        if len(ordered) != len(texts):
            raise RuntimeError(
                f"Bedrock embeddings count mismatch: expected {len(texts)} got {len(ordered)}"
            )
        return ordered

    @staticmethod
    def _read_response_json(response: Any) -> dict[str, Any]:
        body = response.get("body") if isinstance(response, dict) else None
        if hasattr(body, "read"):
            payload = body.read()
        else:
            payload = body
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if not isinstance(payload, str):
            raise RuntimeError("Bedrock embeddings response body is missing.")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise RuntimeError("Bedrock embeddings response is invalid.")
        return data

    @staticmethod
    def _extract_embedding(data: dict[str, Any]) -> list[float]:
        embedding = data.get("embedding")
        if isinstance(embedding, list) and all(
            isinstance(val, (int, float)) for val in embedding
        ):
            return [float(val) for val in embedding]
        embeddings_by_type = data.get("embeddingsByType")
        if isinstance(embeddings_by_type, dict):
            values = embeddings_by_type.get("float")
            if isinstance(values, list) and all(
                isinstance(val, (int, float)) for val in values
            ):
                return [float(val) for val in values]
        raise RuntimeError("Bedrock embeddings response missing embedding.")


def _coerce_hf_embeddings(data: Any, *, expected: int) -> list[list[float]]:
    if not isinstance(data, list):
        raise RuntimeError("Hugging Face embeddings response invalid.")

    def is_vector(item: Any) -> bool:
        return isinstance(item, list) and (
            not item or isinstance(item[0], (int, float))
        )

    def mean_pool(matrix: Iterable[Iterable[float]]) -> list[float]:
        rows = [list(row) for row in matrix if isinstance(row, list)]
        if not rows:
            return []
        dims = len(rows[0])
        sums = [0.0] * dims
        count = 0
        for row in rows:
            if len(row) != dims:
                continue
            for idx, val in enumerate(row):
                sums[idx] += float(val)
            count += 1
        if count == 0:
            return []
        return [val / count for val in sums]

    if expected <= 1:
        if is_vector(data):
            return [data]
        if data and isinstance(data[0], list):
            return [mean_pool(data)]
        raise RuntimeError("Hugging Face embeddings response shape not recognized.")

    if len(data) == expected and all(isinstance(item, list) for item in data):
        if all(is_vector(item) for item in data):
            return data  # batch of vectors
        # batch of token matrices
        return [mean_pool(item) for item in data]

    # Fallback: treat as single token matrix.
    if data and isinstance(data[0], list):
        vector = mean_pool(data)
        if vector:
            return [vector] * expected
    raise RuntimeError("Hugging Face embeddings response shape not recognized.")


def get_sentence_transformer_client(
    *,
    model_name: str,
    device: str,
    normalize_embeddings: bool,
    max_seq_length: int | None,
    dtype: str | None,
    trust_remote_code: bool,
) -> SentenceTransformerEmbedClient:
    cache_key = (
        model_name,
        device,
        normalize_embeddings,
        max_seq_length,
        dtype,
        trust_remote_code,
    )
    config_key = (
        device,
        normalize_embeddings,
        max_seq_length,
        dtype,
        trust_remote_code,
    )
    known_configs = _EMBED_MODEL_CONFIGS.get(model_name)
    if known_configs is None:
        _EMBED_MODEL_CONFIGS[model_name] = {config_key}
    elif config_key not in known_configs:
        known_configs.add(config_key)
    cached = _EMBED_CLIENTS.get(cache_key)
    if cached is not None:
        return cached

    client = SentenceTransformerEmbedClient(
        model_name=model_name,
        device=device,
        normalize_embeddings=normalize_embeddings,
        max_seq_length=max_seq_length,
        dtype=dtype,
        trust_remote_code=trust_remote_code,
    )
    _EMBED_CLIENTS[cache_key] = client
    return client


def get_hf_client(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    wait_for_model: bool,
) -> HuggingFaceEmbedClient:
    cache_key = (model_name, base_url, api_key, timeout_seconds, wait_for_model)
    cached = _HF_CLIENTS.get(cache_key)
    if cached is not None:
        return cached
    client = HuggingFaceEmbedClient(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        wait_for_model=wait_for_model,
    )
    _HF_CLIENTS[cache_key] = client
    return client


def get_bedrock_client(
    *,
    model_name: str,
    region_name: str,
    batch_size: int,
    max_concurrency: int,
    timeout_seconds: float,
) -> BedrockEmbedClient:
    cache_key = (
        model_name,
        region_name,
        batch_size,
        max_concurrency,
        timeout_seconds,
    )
    cached = _BEDROCK_CLIENTS.get(cache_key)
    if cached is not None:
        return cached
    client = BedrockEmbedClient(
        model_name=model_name,
        region_name=region_name,
        batch_size=batch_size,
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
    )
    _BEDROCK_CLIENTS[cache_key] = client
    return client


# ── Free RAM detection (no psutil dependency) ─────────────────────────────────

# Approximate RAM consumed per bge-m3 worker process.
MODEL_EMBED_RAM_GB: float = 1.5


def get_free_ram_gb() -> float | None:
    """Return available system RAM in GiB using platform-specific APIs.

    Supports Windows (GlobalMemoryStatusEx) and Linux (/proc/meminfo).
    Returns None when the value cannot be determined so callers can fall back
    to the CPU-count cap instead.
    """
    import platform

    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            import ctypes.wintypes

            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.wintypes.DWORD),
                    ("dwMemoryLoad", ctypes.wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return stat.ullAvailPhys / (1024**3)
        if system == "Linux":
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        return kb / (1024**2)
    except Exception:
        pass
    return None


# ── Multiprocess embedding pool (local SentenceTransformer only) ──────────────

# Module-level state inside each worker process
_worker_model = None
_worker_normalize_embeddings: bool = True


def _worker_init(
    model_name: str,
    device: str,
    normalize_embeddings: bool,
    max_seq_length: int | None,
    dtype: str | None,
    trust_remote_code: bool,
) -> None:
    """Load the SentenceTransformer model inside the worker process."""
    global _worker_model, _worker_normalize_embeddings
    _worker_normalize_embeddings = normalize_embeddings
    from sentence_transformers import SentenceTransformer

    model_kwargs: dict = {}
    _dtype = None
    if dtype:
        try:
            import torch

            _dtype = getattr(torch, dtype)
            model_kwargs["dtype"] = _dtype
        except Exception:
            pass

    init_kwargs: dict = {"device": device}
    if model_kwargs:
        init_kwargs["model_kwargs"] = model_kwargs
    if trust_remote_code:
        init_kwargs["trust_remote_code"] = True
    # Try with both model_kwargs and trust_remote_code
    try:
        _worker_model = SentenceTransformer(model_name, **init_kwargs)
    except TypeError:
        import warnings

        # Older sentence-transformers may not support all kwargs; retry with minimal args
        init_kwargs.pop("model_kwargs", None)
        init_kwargs.pop("trust_remote_code", None)
        warnings.warn(
            f"SentenceTransformer({model_name!r}) raised TypeError; retrying without model_kwargs/trust_remote_code",
            stacklevel=2,
        )
        _worker_model = SentenceTransformer(model_name, **init_kwargs)
        if _dtype is not None:
            _worker_model = _worker_model.to(dtype=_dtype)
    if max_seq_length:
        _worker_model.max_seq_length = max_seq_length


def _worker_init_shared(
    model: Any,
    device: str,
    normalize_embeddings: bool,
    max_seq_length: int | None,
) -> None:
    """Fast-path worker init: receive shared-memory CPU model and move it to device.

    The model weights were loaded once in the main process (bfloat16, CPU) and
    pinned to OS shared memory via ``share_memory()``.  PyTorch's multiprocessing
    pickle protocol sends only a file-descriptor handle — no disk read, no data
    copy.  Each worker then calls ``.to(device)`` which allocates new CUDA tensors
    from those shared CPU pages, leaving the shared memory untouched for siblings.
    """
    global _worker_model, _worker_normalize_embeddings
    _worker_normalize_embeddings = normalize_embeddings
    _worker_model = model.to(device)
    if max_seq_length:
        _worker_model.max_seq_length = max_seq_length


def _worker_encode(texts: list[str]) -> list[list[float]]:
    """Encode texts in a worker process using the pre-loaded model."""
    return _worker_model.encode(
        texts,
        normalize_embeddings=_worker_normalize_embeddings,
        show_progress_bar=False,
        convert_to_numpy=True,
    ).tolist()


class EmbedWorkerPool:
    """
    Pool of worker processes each pre-loading a SentenceTransformer model.

    Splits text lists across workers and collects results in original order.
    Only useful for local (CPU/GPU) SentenceTransformer inference.
    """

    def __init__(
        self,
        model_name: str,
        device: str,
        normalize_embeddings: bool,
        max_seq_length: int | None,
        dtype: str | None,
        trust_remote_code: bool,
        n_workers: int,
        preloaded_model: Any = None,
    ) -> None:
        self._n_workers = n_workers
        if preloaded_model is not None:
            # Fast path: pin weights to OS shared memory once; workers receive a
            # file-descriptor handle (not a copy) and move them to the GPU device.
            preloaded_model.share_memory()
            self._executor = ProcessPoolExecutor(
                max_workers=n_workers,
                initializer=_worker_init_shared,
                initargs=(
                    preloaded_model,
                    device,
                    normalize_embeddings,
                    max_seq_length,
                ),
                mp_context=multiprocessing.get_context("spawn"),
            )
        else:
            # Slow path: each worker loads the full model from disk independently.
            self._executor = ProcessPoolExecutor(
                max_workers=n_workers,
                initializer=_worker_init,
                initargs=(
                    model_name,
                    device,
                    normalize_embeddings,
                    max_seq_length,
                    dtype,
                    trust_remote_code,
                ),
                mp_context=multiprocessing.get_context("spawn"),
            )
        atexit.register(self.shutdown)

    def encode(
        self, texts: list[str], *, n_chunks: int | None = None
    ) -> list[list[float]]:
        """Distribute texts across workers and return embeddings in original order.

        n_chunks controls how many pieces the text list is split into before being
        submitted to the pool. It can exceed the pool size — extra chunks simply queue
        behind the running ones, improving load balancing when chunk lengths vary.
        Defaults to the pool size when not specified.
        """
        if not texts:
            return []
        if self._n_workers <= 1 or len(texts) <= 1:
            return self._executor.submit(_worker_encode, texts).result()
        count = max(1, n_chunks if n_chunks is not None else self._n_workers)
        chunk_size = math.ceil(len(texts) / count)
        chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]
        futures = [self._executor.submit(_worker_encode, chunk) for chunk in chunks]
        result: list[list[float]] = []
        for f in futures:
            result.extend(f.result())
        return result

    def shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass


# Singleton pool (one per process, created lazily)
_EMBED_WORKER_POOL: EmbedWorkerPool | None = None
_EMBED_WORKER_POOL_LOCK = threading.Lock()


def release_gpu_memory() -> None:
    """Free GPU memory after a run while keeping model weights in CPU shared memory.

    - Worker pool is shut down: the spawned processes (and their CUDA copies) are
      killed immediately, freeing VRAM.
    - Main-process model is moved to CPU and left in ``_EMBED_CLIENTS``.  Its
      weights are already in bfloat16, so they occupy ~2.2 GB of CPU RAM.
    - On the next run ``get_embed_worker_pool`` calls ``share_memory()`` on that
      CPU model and passes it to the new workers via a shared-memory handle.
      Workers call ``.to(device)`` which is a fast PCIe transfer (~1–2 s) rather
      than a disk read (~5–10 s).
    """
    import logging

    _log = logging.getLogger(__name__)
    global _EMBED_WORKER_POOL

    # Shut down worker pool — kills spawned processes and frees their CUDA copies.
    with _EMBED_WORKER_POOL_LOCK:
        if _EMBED_WORKER_POOL is not None:
            try:
                _EMBED_WORKER_POOL.shutdown()
            except Exception:
                pass
            _EMBED_WORKER_POOL = None
            _log.info("GPU offload: embedding worker pool shut down.")

    # Move main-process models from GPU to CPU.  Weights stay resident in RAM so
    # the next pool spawn can share them without a disk read.
    offloaded = 0
    for client in _EMBED_CLIENTS.values():
        model = getattr(client, "_model", None)
        if model is None:
            continue
        try:
            model.to("cpu")
            offloaded += 1
        except Exception:
            pass

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

    if offloaded:
        _log.info(
            "GPU offload: %d model(s) moved to CPU; CUDA cache cleared.", offloaded
        )


def get_embed_worker_pool(
    *,
    model_name: str,
    device: str,
    normalize_embeddings: bool,
    max_seq_length: int | None,
    dtype: str | None,
    trust_remote_code: bool,
    n_workers: int,
    preloaded_model: Any = None,
) -> EmbedWorkerPool:
    """Return the singleton EmbedWorkerPool, creating it on first call.

    Pass ``preloaded_model`` (a CPU-resident SentenceTransformer) to use the
    shared-memory fast path — workers receive the weights via an OS handle
    instead of each loading from disk.
    """
    global _EMBED_WORKER_POOL
    with _EMBED_WORKER_POOL_LOCK:
        if _EMBED_WORKER_POOL is None:
            _EMBED_WORKER_POOL = EmbedWorkerPool(
                model_name=model_name,
                device=device,
                normalize_embeddings=normalize_embeddings,
                max_seq_length=max_seq_length,
                dtype=dtype,
                trust_remote_code=trust_remote_code,
                n_workers=n_workers,
                preloaded_model=preloaded_model,
            )
        else:
            import logging

            _log = logging.getLogger(__name__)
            _log.debug(
                "get_embed_worker_pool: returning existing pool (new params ignored)"
            )
        return _EMBED_WORKER_POOL
