from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Iterable


_EMBED_CLIENTS: dict[tuple, "SentenceTransformerEmbedClient"] = {}
_EMBED_MODEL_CONFIGS: dict[str, set[tuple]] = {}
_OLLAMA_CLIENTS: dict[tuple, "OllamaEmbedClient"] = {}
_HF_CLIENTS: dict[tuple, "HuggingFaceEmbedClient"] = {}


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
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()


@dataclass
class OllamaEmbedClient:
    model_name: str
    base_url: str
    timeout_seconds: float

    def __post_init__(self) -> None:
        import httpx

        self._http = httpx.Client(timeout=self.timeout_seconds)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        max_chars = _env_optional_int("OLLAMA_EMBED_TEXT_MAX_CHARS", min_value=1)
        if max_chars is not None:
            texts = [text[:max_chars] if len(text) > max_chars else text for text in texts]
        try:
            data = self._post_json("/api/embed", {"model": self.model_name, "input": texts})
            embeddings = data.get("embeddings")
            if embeddings is None:
                embedding = data.get("embedding")
                if isinstance(embedding, list):
                    return [embedding]
            if not isinstance(embeddings, list):
                raise RuntimeError("Ollama embed response missing embeddings list.")
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"Ollama embeddings count mismatch: expected {len(texts)} got {len(embeddings)}"
                )
            return embeddings
        except Exception as exc:
            # If Ollama's batch endpoint fails intermittently, split the batch and retry.
            if _is_http_status(exc, 500) and len(texts) > 1:
                mid = len(texts) // 2
                return self.embed_texts(texts[:mid]) + self.embed_texts(texts[mid:])
            if _is_http_status(exc, 404) or _is_http_status(exc, 400) or _is_http_status(exc, 500):
                return [self._embed_single(text) for text in texts]
            raise RuntimeError(f"Ollama embeddings request failed: {exc}") from exc

    def _embed_single(self, text: str) -> list[float]:
        max_chars = _env_optional_int("OLLAMA_EMBED_TEXT_MAX_CHARS", min_value=1)
        if max_chars is not None and len(text) > max_chars:
            text = text[:max_chars]
        data = self._post_json("/api/embeddings", {"model": self.model_name, "prompt": text})
        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Ollama embeddings response missing embedding.")
        return embedding

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}{path}"
        resp = self._http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Ollama embeddings response invalid.")
        return data


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


def _is_http_status(exc: Exception, status_code: int) -> bool:
    try:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response is not None and exc.response.status_code == status_code
    except Exception:
        return False
    return False


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def _env_optional_int(name: str, *, min_value: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if min_value is not None and value < min_value:
        return min_value
    return value


def _coerce_hf_embeddings(data: Any, *, expected: int) -> list[list[float]]:
    if not isinstance(data, list):
        raise RuntimeError("Hugging Face embeddings response invalid.")

    def is_vector(item: Any) -> bool:
        return isinstance(item, list) and (not item or isinstance(item[0], (int, float)))

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


def get_ollama_client(
    *, model_name: str, base_url: str, timeout_seconds: float
) -> OllamaEmbedClient:
    cache_key = (model_name, base_url, timeout_seconds)
    cached = _OLLAMA_CLIENTS.get(cache_key)
    if cached is not None:
        return cached
    client = OllamaEmbedClient(
        model_name=model_name,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    _OLLAMA_CLIENTS[cache_key] = client
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
