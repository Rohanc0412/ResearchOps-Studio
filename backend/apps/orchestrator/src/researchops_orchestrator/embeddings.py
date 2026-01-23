from __future__ import annotations

from dataclasses import dataclass


_EMBED_CLIENTS: dict[tuple, "SentenceTransformerEmbedClient"] = {}
_EMBED_MODEL_CONFIGS: dict[str, set[tuple]] = {}


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
