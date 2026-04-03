"""
Retriever node - generates diverse queries and retrieves sources.

Uses Scientific Papers MCP to collect candidate sources across multiple
academic databases, deduplicate, rank, and select a diverse set of
sources for the run.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import math
import os
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol

from cancellation import raise_if_run_cancel_requested
from connectors import ScientificPapersMCPConnector
from connectors.base import RetrievedSource
from connectors.dedup import deduplicate_sources
from core.env import env_float, env_int
from core.orchestrator.state import OrchestratorState, SourceRef
from core.pipeline_events import instrument_node
from core.pipeline_events.events import emit_node_progress
from db.models.run_checkpoints import RunCheckpointRow
from db.models.run_sources import RunSourceRow
from db.models.snapshots import SnapshotRow
from db.models.source_embeddings import SourceEmbeddingRow
from db.models.sources import SourceRow
from db.repositories.corpus import (
    create_or_get_source_sync as create_or_get_source,
)
from db.repositories.corpus import (
    get_source_identifier,
    list_source_author_names,
)
from embeddings import (
    BedrockEmbedClient,
    MODEL_EMBED_RAM_GB,
    SentenceTransformerEmbedClient,
    get_bedrock_client,
    get_embed_worker_pool,
    get_free_ram_gb,
    get_hf_client,
    get_ollama_client,
    get_sentence_transformer_client,
    resolve_bedrock_embed_batch_size,
    resolve_bedrock_embed_concurrency,
    resolve_bedrock_embed_region_name,
    resolve_bedrock_embed_timeout_seconds,
    resolve_embed_device,
    resolve_embed_dtype,
    resolve_embed_max_seq_len,
    resolve_embed_model,
    resolve_embed_normalize,
    resolve_embed_provider,
    resolve_embed_trust_remote_code,
    resolve_embed_workers,
)
from ingestion import ingest_source
from langfuse.decorators import observe
from llm import (
    LLMError,
    explain_llm_error,
    extract_json_payload,
    get_llm_client_for_stage,
    json_response_format,
    log_llm_exchange,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    query: str


@dataclass(frozen=True)
class RankedCandidate:
    source: RetrievedSource
    score: float
    intent: str


ALLOWED_INTENTS = [
    "survey",
    "methods",
    "benchmarks",
    "failure modes",
    "future directions",
    "recent work",
]

QUERY_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["intent", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["queries"],
    "additionalProperties": False,
}


def _resolve_rerank_topk(candidate_count: int) -> int:
    if candidate_count <= 0:
        return 0
    topk = env_int("RETRIEVER_RERANK_TOPK", 120, min_value=1)
    topk = min(topk, 200)
    return min(topk, candidate_count)


def _build_query_plan(
    question: str,
    llm_provider: str | None,
    llm_model: str | None,
    stage_models: dict[str, str | None] | None = None,
) -> tuple[list[QueryPlan], bool]:
    base = " ".join(question.split())
    if not base:
        return [], False

    max_queries = env_int("RETRIEVER_QUERY_COUNT", 8, min_value=6)

    llm_plans = _build_query_plan_with_llm(
        question=base,
        max_queries=max_queries,
        llm_provider=llm_provider,
        llm_model=llm_model,
        stage_models=stage_models,
    )
    if not llm_plans:
        raise ValueError("LLM query generation failed or returned no queries.")

    return llm_plans, True


def _normalize_intent(intent: str) -> str | None:
    normalized = intent.strip().lower().replace("_", " ")
    mapping = {
        "failure modes": "failure modes",
        "failure mode": "failure modes",
        "failures": "failure modes",
        "future directions": "future directions",
        "future direction": "future directions",
        "recent work": "recent work",
        "recent": "recent work",
    }
    normalized = mapping.get(normalized, normalized)
    if normalized in ALLOWED_INTENTS:
        return normalized
    return None


def _strip_code_fence(text: str) -> str:
    match = re.search(
        r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL
    )
    return match.group(1).strip() if match else text


def _clean_query_line(line: str) -> str:
    cleaned = re.sub(r"^\s*[-*\d\)\.:\s]+", "", line).strip()
    return cleaned.strip().strip('"').strip("'").strip()


def _fallback_query_plan_from_text(text: str, max_queries: int) -> list[QueryPlan]:
    if not text:
        return []
    content = _strip_code_fence(text)
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    plans: list[QueryPlan] = []
    seen_queries: set[str] = set()

    def add_plan(query: str, intent: str | None) -> None:
        normalized_query = " ".join(query.split())
        if len(normalized_query) < 6:
            return
        if normalized_query in seen_queries:
            return
        plans.append(QueryPlan(intent=intent or "survey", query=normalized_query))
        seen_queries.add(normalized_query)

    for line in lines:
        cleaned = _clean_query_line(line)
        if not cleaned:
            continue

        intent = None
        query = cleaned

        match = re.match(r"^\[?([A-Za-z\s]+)\]?\s*[:\-]\s*(.+)$", cleaned)
        if match:
            intent = _normalize_intent(match.group(1))
            query = match.group(2).strip()
        else:
            match = re.match(r"^([A-Za-z\s]+)\s*-\s*(.+)$", cleaned)
            if match:
                intent = _normalize_intent(match.group(1))
                query = match.group(2).strip()

        add_plan(query, intent)
        if len(plans) >= max_queries:
            break

    if not plans:
        chunks = [c.strip() for c in re.split(r"[;\n]+", content) if c.strip()]
        for chunk in chunks:
            add_plan(_clean_query_line(chunk), None)
            if len(plans) >= max_queries:
                break

    return plans


def _build_query_plan_with_llm(
    *,
    question: str,
    max_queries: int,
    llm_provider: str | None,
    llm_model: str | None,
    stage_models: dict[str, str | None] | None = None,
) -> list[QueryPlan]:
    try:
        llm_client = get_llm_client_for_stage(
            "retrieve", llm_provider, llm_model, stage_models=stage_models
        )
    except LLMError as exc:
        logger.warning(
            "Could not prepare query generation LLM client",
            extra={
                "event": "pipeline.llm.error",
                "stage": "retrieve",
                "reason": str(exc),
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )
        raise ValueError(explain_llm_error(str(exc))) from exc

    if llm_client is None:
        logger.warning(
            "Query generation skipped because the LLM client is disabled",
            extra={
                "event": "pipeline.llm.error",
                "stage": "retrieve",
                "reason": "llm_disabled",
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )
        return []

    intents = ", ".join(ALLOWED_INTENTS)
    prompt = (
        f"Generate exactly {max_queries} diverse academic search queries for the research question below.\n"
        "Return ONLY JSON with this schema:\n"
        "{\n"
        '  "queries": [\n'
        '    {"intent": "survey|methods|benchmarks|failure modes|future '
        'directions|recent work", "query": "..."}\n'
        "  ]\n"
        "}\n\n"
        f"Question: {question}\n"
        f"Allowed intents: {intents}\n"
        "Rules:\n"
        "- Use each intent at least once when possible\n"
        "- Keep queries concise and specific\n"
        "- Do not include numbering or commentary\n"
    )
    system = "You generate search queries as strict JSON only."
    try:
        log_llm_exchange("request", prompt, stage="retrieve", logger=logger)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=600,
            temperature=0.4,
            response_format=json_response_format("query_plan", QUERY_PLAN_SCHEMA),
        )
    except LLMError as exc:
        logger.warning(
            "LLM query generation failed",
            extra={
                "event": "pipeline.llm.error",
                "stage": "retrieve",
                "reason": str(exc),
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )
        raise ValueError(explain_llm_error(str(exc))) from exc

    log_llm_exchange("response", response, stage="retrieve", logger=logger)
    payload = extract_json_payload(response)
    items = None
    if isinstance(payload, dict):
        items = payload.get("queries") or payload.get("items")
    elif isinstance(payload, list):
        items = payload

    if not isinstance(items, list):
        logger.warning(
            "LLM query generation returned invalid JSON",
            extra={
                "event": "pipeline.llm.error",
                "stage": "retrieve",
                "reason": "invalid_response",
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "preview": response[:600] if response else "",
            },
        )
        fallback = _fallback_query_plan_from_text(response or "", max_queries)
        if fallback:
            logger.info(
                "Recovered queries from fallback parsing",
                extra={
                    "event": "pipeline.llm.fallback",
                    "stage": "retrieve",
                    "query_count": len(fallback),
                },
            )
            return fallback
        return []

    plans: list[QueryPlan] = []
    seen_queries: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        intent_raw = str(item.get("intent", "")).strip()
        query_raw = str(item.get("query", "")).strip()
        if not query_raw:
            continue
        intent = _normalize_intent(intent_raw)
        if not intent:
            continue
        query = " ".join(query_raw.split())
        if query in seen_queries:
            continue
        plans.append(QueryPlan(intent=intent, query=query))
        seen_queries.add(query)
        if len(plans) >= max_queries:
            break

    return plans


class EmbedError(RuntimeError):
    """Raised when embedding calls fail."""


class EmbeddingClient(Protocol):
    model_name: str
    dimensions: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def _get_embed_client(llm_provider: str | None) -> EmbeddingClient | None:
    provider_name = resolve_embed_provider(llm_provider)
    if provider_name in {"", "none", "disabled"}:
        raise EmbedError(
            "Embeddings are required for reranking but provider is disabled."
        )
    if provider_name == "ollama":
        model_name = resolve_embed_model(provider_name)
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        timeout_seconds = env_int("OLLAMA_TIMEOUT_SECONDS", 60, min_value=5)
        return get_ollama_client(
            model_name=model_name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    if provider_name in {"hf", "huggingface", "hosted", "inference"}:
        model_name = resolve_embed_model(provider_name)
        base_url = os.getenv(
            "HF_INFERENCE_BASE_URL",
            "https://router.huggingface.co/hf-inference/models",
        ).strip()
        api_key = os.getenv("HF_TOKEN", "").strip()
        if not api_key:
            raise EmbedError("HF_TOKEN is required for hosted embeddings.")
        timeout_seconds = env_int("HF_TIMEOUT_SECONDS", 60, min_value=5)
        wait_for_model = os.getenv("HF_WAIT_FOR_MODEL", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        return get_hf_client(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            wait_for_model=wait_for_model,
        )
    if provider_name == "bedrock":
        region_name = resolve_bedrock_embed_region_name()
        model_name = resolve_embed_model(provider_name)
        if not region_name:
            raise EmbedError(
                "Bedrock embeddings require BEDROCK_EMBED_REGION or "
                "BEDROCK_REGION/AWS_REGION/AWS_DEFAULT_REGION."
            )
        if not model_name or not model_name.strip():
            raise EmbedError("Bedrock embeddings require BEDROCK_EMBED_MODEL.")
        return get_bedrock_client(
            model_name=model_name,
            region_name=region_name,
            batch_size=resolve_bedrock_embed_batch_size(),
            max_concurrency=resolve_bedrock_embed_concurrency(),
            timeout_seconds=resolve_bedrock_embed_timeout_seconds(),
        )
    if provider_name in {"local", "sentence-transformers", "bge"}:
        model_name = resolve_embed_model(provider_name)
        device = resolve_embed_device()
        dtype = resolve_embed_dtype(device)
        return get_sentence_transformer_client(
            model_name=model_name,
            device=device,
            normalize_embeddings=resolve_embed_normalize(),
            max_seq_length=resolve_embed_max_seq_len(),
            dtype=dtype,
            trust_remote_code=resolve_embed_trust_remote_code(model_name),
        )
    raise EmbedError(f"Unknown embedding provider: {provider_name}")


def _embedding_text_for_source(
    source: RetrievedSource, *, abstract_only: bool = False
) -> str:
    title = (source.title or "").strip()
    abstract = (source.abstract or "").strip()
    if abstract_only or not source.full_text:
        text = f"{title}\n\n{abstract}" if title and abstract else title or abstract
    else:
        full_text = source.full_text.strip()
        text = f"{title}\n\n{full_text}" if title else full_text
    text = text.strip()
    raw = os.getenv("RETRIEVER_EMBED_TEXT_MAX_CHARS")
    if raw and raw.strip():
        try:
            max_chars = int(raw)
        except ValueError:
            max_chars = 0
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars]
    return text


def _embedding_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bm25_text_for_source(source: RetrievedSource) -> str:
    title = (source.title or "").strip()
    abstract = (source.abstract or "").strip()
    if title and abstract:
        return f"{title}\n\n{abstract}"
    return title or abstract


def _bm25_tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    buffer: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            buffer.append(ch)
            continue
        if buffer:
            token = "".join(buffer)
            if len(token) > 2:
                tokens.append(token)
            buffer = []
    if buffer:
        token = "".join(buffer)
        if len(token) > 2:
            tokens.append(token)
    return tokens


def _bm25_score(
    query_tokens: list[str],
    doc_counts: Counter[str],
    doc_len: int,
    avg_doc_len: float,
    doc_freq: Counter[str],
    corpus_size: int,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens or doc_len <= 0:
        return 0.0
    score = 0.0
    unique_terms = set(query_tokens)
    denom_base = k1 * (1.0 - b + b * (doc_len / max(avg_doc_len, 1.0)))
    for term in unique_terms:
        tf = doc_counts.get(term, 0)
        if tf <= 0:
            continue
        df = doc_freq.get(term, 0)
        idf = math.log(1.0 + (corpus_size - df + 0.5) / (df + 0.5))
        score += idf * ((tf * (k1 + 1.0)) / (tf + denom_base))
    return score


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for l_val, r_val in zip(left, right, strict=True):
        dot += l_val * r_val
        left_norm += l_val * l_val
        right_norm += r_val * r_val
    denom = math.sqrt(left_norm) * math.sqrt(right_norm)
    if denom == 0.0:
        return 0.0
    return dot / denom


def _embed_texts_batched(
    client: EmbeddingClient, texts: list[str], *, batch_size: int
) -> list[list[float]]:
    if not texts:
        return []
    if isinstance(client, BedrockEmbedClient):
        return client.embed_texts(texts)
    # Use multiprocess pool for local SentenceTransformer when workers > 1
    if isinstance(client, SentenceTransformerEmbedClient):
        cpu_cap = max(1, (os.cpu_count() or 2) // 2)
        free_ram = get_free_ram_gb()
        ram_cap = (
            max(1, int(free_ram / MODEL_EMBED_RAM_GB))
            if free_ram is not None
            else cpu_cap
        )
        hard_cap = resolve_embed_workers()
        # pool_size = model instances (RAM-bound); n_chunks = parallelism hint (can exceed pool_size)
        pool_size = min(cpu_cap, ram_cap, hard_cap)
        n_chunks = env_int("EMBED_CHUNKS", pool_size, min_value=1)
        if pool_size > 1:
            try:
                pool = get_embed_worker_pool(
                    model_name=client.model_name,
                    device=client.device,
                    normalize_embeddings=client.normalize_embeddings,
                    max_seq_length=client.max_seq_length,
                    dtype=client.dtype,
                    trust_remote_code=client.trust_remote_code,
                    n_workers=pool_size,
                    preloaded_model=(
                        None
                        if str(client.device).startswith("cuda")
                        else getattr(client, "_model", None)
                    ),
                )
                return pool.encode(texts, n_chunks=n_chunks)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EmbedWorkerPool failed, falling back to sequential: %s", exc
                )
    # Sequential fallback (Ollama, HF, or pool unavailable / workers=1)
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(client.embed_texts(batch))
    return embeddings


def _load_embedding_cache(
    session: Session,
    *,
    tenant_id,
    canonical_ids: list[str],
    embedding_model: str,
) -> dict:
    if not canonical_ids:
        return {}
    rows = (
        session.query(SourceEmbeddingRow)
        .filter(
            SourceEmbeddingRow.tenant_id == tenant_id,
            SourceEmbeddingRow.canonical_id.in_(canonical_ids),
            SourceEmbeddingRow.embedding_model == embedding_model,
        )
        .all()
    )
    return {row.canonical_id: row for row in rows}


def _upsert_source_embedding(
    session: Session,
    *,
    tenant_id,
    canonical_id: str,
    embedding_model: str,
    embedding_vector: list[float],
    text_hash: str,
    existing: SourceEmbeddingRow | None = None,
) -> tuple[SourceEmbeddingRow, bool]:
    if existing and existing.text_hash == text_hash:
        return existing, False
    now = datetime.now(UTC)
    if existing:
        existing.embedding_json = embedding_vector
        existing.embedding_dim = len(embedding_vector)
        existing.text_hash = text_hash
        existing.updated_at = now
        session.flush()
        return existing, True

    row = SourceEmbeddingRow(
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        embedding_model=embedding_model,
        embedding_dim=len(embedding_vector),
        embedding_json=embedding_vector,
        text_hash=text_hash,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row, True


def _recency_score(year: int | None) -> float:
    if not year:
        return 0.0
    current_year = datetime.now(UTC).year
    years_old = max(0, current_year - year)
    return max(0.0, min(1.0, 1.0 - (years_old / 10.0)))


def _citation_score(cited_by_count: int | None) -> float:
    if not cited_by_count:
        return 0.0
    return min(1.0, math.log(cited_by_count + 1) / 10.0)


def _rank_sources(
    sources: Iterable[RetrievedSource],
    query_plan: list[QueryPlan],
    *,
    session: Session,
    tenant_id,
    query_text: str,
    llm_provider: str | None,
    stats: dict | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> list[RankedCandidate]:
    ranked: list[RankedCandidate] = []
    sources_list = list(sources)
    if stats is None:
        stats = {}
    stats.setdefault("cache_hits", 0)
    stats.setdefault("cache_misses", 0)
    stats.setdefault("embedded_now", 0)
    stats.setdefault("batch_count", 0)
    stats.setdefault("used_embeddings", False)

    if not sources_list:
        stats["topk"] = 0
        return ranked

    doc_texts = [_bm25_text_for_source(source) for source in sources_list]
    doc_tokens = [_bm25_tokenize(text) for text in doc_texts]
    doc_counts = [Counter(tokens) for tokens in doc_tokens]
    doc_lens = [len(tokens) for tokens in doc_tokens]
    avg_doc_len = sum(doc_lens) / max(len(doc_lens), 1)
    doc_freq: Counter[str] = Counter()
    for tokens in doc_tokens:
        doc_freq.update(set(tokens))

    query_tokens = [_bm25_tokenize(plan.query) for plan in query_plan]

    bm25_scores: list[float] = []
    intents: list[str] = []
    for idx, counts in enumerate(doc_counts):
        best_intent = query_plan[0].intent if query_plan else "survey"
        best_score = 0.0
        for plan, tokens in zip(query_plan, query_tokens, strict=True):
            score = _bm25_score(
                tokens,
                counts,
                doc_lens[idx],
                avg_doc_len,
                doc_freq,
                len(sources_list),
            )
            if score > best_score:
                best_score = score
                best_intent = plan.intent
        bm25_scores.append(best_score)
        intents.append(best_intent)

    max_bm25 = max(bm25_scores) if bm25_scores else 0.0
    bm25_norm = [(score / max_bm25) if max_bm25 > 0 else 0.0 for score in bm25_scores]

    embed_norms = [0.0 for _ in sources_list]
    topk = _resolve_rerank_topk(len(sources_list))
    stats["topk"] = topk

    if topk > 0:
        if cancel_check is not None:
            cancel_check()
        if not query_text.strip():
            raise EmbedError("Embeddings require a non-empty query text.")
        embed_client = _get_embed_client(llm_provider)
        if cancel_check is not None:
            cancel_check()
        query_embedding = embed_client.embed_texts([query_text.strip()])[0]

        sorted_indices = sorted(
            range(len(sources_list)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )
        topk_indices = sorted_indices[:topk]
        canonical_map: dict[int, str] = {}
        for idx in topk_indices:
            canonical_map[idx] = sources_list[idx].to_canonical_string()

        canonical_ids = [canonical_map[idx] for idx in topk_indices]
        cached = _load_embedding_cache(
            session,
            tenant_id=tenant_id,
            canonical_ids=canonical_ids,
            embedding_model=embed_client.model_name,
        )

        texts_to_embed: list[str] = []
        pending: list[tuple[int, str, str, SourceEmbeddingRow | None]] = []

        for idx in topk_indices:
            text = _embedding_text_for_source(sources_list[idx], abstract_only=True)
            if not text:
                stats["cache_misses"] += 1
                continue
            text_hash = _embedding_text_hash(text)
            canonical_id = canonical_map[idx]
            cached_row = cached.get(canonical_id)
            if cached_row and cached_row.text_hash == text_hash:
                stats["cache_hits"] += 1
                embed_norms[idx] = (
                    1.0 + _cosine_similarity(query_embedding, cached_row.embedding_json)
                ) / 2.0
                continue
            stats["cache_misses"] += 1
            texts_to_embed.append(text)
            pending.append((idx, canonical_id, text_hash, cached_row))

        batch_size = env_int("RETRIEVER_EMBED_BATCH", 32, min_value=1)
        stats["batch_count"] = (
            math.ceil(len(texts_to_embed) / batch_size) if texts_to_embed else 0
        )
        if texts_to_embed:
            if cancel_check is not None:
                cancel_check()
            vectors = _embed_texts_batched(
                embed_client, texts_to_embed, batch_size=batch_size
            )
            if len(vectors) != len(texts_to_embed):
                raise EmbedError(
                    "Embedding batch size mismatch: expected "
                    f"{len(texts_to_embed)} got {len(vectors)}"
                )
            for (idx, canonical_id, text_hash, cached_row), vector in zip(
                pending, vectors, strict=True
            ):
                if not vector:
                    continue
                _upsert_source_embedding(
                    session,
                    tenant_id=tenant_id,
                    canonical_id=canonical_id,
                    embedding_model=embed_client.model_name,
                    embedding_vector=vector,
                    text_hash=text_hash,
                    existing=cached_row,
                )
                stats["embedded_now"] += 1
                embed_norms[idx] = (
                    1.0 + _cosine_similarity(query_embedding, vector)
                ) / 2.0
            if cancel_check is not None:
                cancel_check()

    weights = {
        "bm25": env_float("RETRIEVER_WEIGHT_BM25", 0.55, min_value=0.0),
        "embed": env_float("RETRIEVER_WEIGHT_EMBED", 0.30, min_value=0.0),
        "recency": env_float("RETRIEVER_WEIGHT_RECENCY", 0.10, min_value=0.0),
        "citation": env_float("RETRIEVER_WEIGHT_CITATION", 0.05, min_value=0.0),
    }

    stats["used_embeddings"] = True if topk > 0 else False

    for idx, source in enumerate(sources_list):
        recency = _recency_score(source.year)
        citation = _citation_score(source.citations_count)
        score = (
            bm25_norm[idx] * weights["bm25"]
            + embed_norms[idx] * weights["embed"]
            + recency * weights["recency"]
            + citation * weights["citation"]
        )
        ranked.append(RankedCandidate(source=source, score=score, intent=intents[idx]))

    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked


def _select_diverse(
    candidates: list[RankedCandidate],
    target_count: int,
    per_intent_cap: int,
) -> list[RankedCandidate]:
    selected: list[RankedCandidate] = []
    intent_counts: dict[str, int] = {intent: 0 for intent in ALLOWED_INTENTS}
    connector_counts: dict[str, int] = {}
    max_connector_fraction = env_float(
        "RETRIEVER_MAX_CONNECTOR_FRACTION", 0.6, min_value=0.0
    )
    connector_cap = max(1, math.ceil(target_count * max_connector_fraction))

    for candidate in candidates:
        if len(selected) >= target_count:
            break
        intent = candidate.intent
        if intent_counts.get(intent, 0) >= per_intent_cap:
            continue
        connector = candidate.source.connector or ""
        if connector_counts.get(connector, 0) >= connector_cap:
            continue
        selected.append(candidate)
        intent_counts[intent] = intent_counts.get(intent, 0) + 1
        connector_counts[connector] = connector_counts.get(connector, 0) + 1

    if len(selected) < target_count:
        for candidate in candidates:
            if len(selected) >= target_count:
                break
            if candidate in selected:
                continue
            selected.append(candidate)

    return selected


def _build_metadata(source: RetrievedSource) -> dict:
    metadata: dict[str, object] = {}
    if source.keywords:
        metadata["keywords"] = list(source.keywords)
    if source.canonical_id.openalex_id:
        metadata["openalex_id"] = source.canonical_id.openalex_id
    if source.extra_metadata:
        metadata["connector_metadata"] = source.extra_metadata
    return metadata


def _upsert_source(
    session: Session,
    *,
    tenant_id,
    source: RetrievedSource,
    origin: str,
) -> SourceRow:
    metadata = _build_metadata(source)
    return create_or_get_source(
        session=session,
        tenant_id=tenant_id,
        canonical_id=source.to_canonical_string(),
        source_type=str(source.source_type.value),
        title=source.title,
        authors=source.authors or [],
        year=source.year,
        venue=source.venue,
        origin=origin,
        cited_by_count=source.citations_count,
        url=source.url,
        doi=source.canonical_id.doi,
        arxiv_id=source.canonical_id.arxiv_id,
        metadata=metadata,
    )


def _upsert_run_source(
    session: Session,
    *,
    tenant_id,
    run_id,
    source_id,
    score: float,
    origin: str,
) -> RunSourceRow:
    row = (
        session.query(RunSourceRow)
        .filter(
            RunSourceRow.tenant_id == tenant_id,
            RunSourceRow.run_id == run_id,
            RunSourceRow.source_id == source_id,
        )
        .one_or_none()
    )
    if row:
        if score > row.score:
            row.score = score
        if origin and not row.origin:
            row.origin = origin
        session.flush()
        return row

    row = RunSourceRow(
        tenant_id=tenant_id,
        run_id=run_id,
        source_id=source_id,
        score=score,
        origin=origin,
    )
    session.add(row)
    session.flush()
    return row


class _EmbeddingProviderAdapter:
    """Adapt retriever embedding clients to the ingestion pipeline protocol."""

    def __init__(self, client: EmbeddingClient):
        self._client = client
        self._dimensions: int | None = getattr(client, "dimensions", None)

    @property
    def model_name(self) -> str:
        return self._client.model_name

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            raise ValueError(
                "Embedding dimensions are unknown until at least one batch is "
                "embedded."
            )
        return self._dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = self._client.embed_texts(texts)
        if vectors and self._dimensions is None:
            self._dimensions = len(vectors[0])
        return vectors


def _snapshot_exists_for_source(session: Session, *, tenant_id, source_id) -> bool:
    row = (
        session.query(SnapshotRow.id)
        .filter(SnapshotRow.tenant_id == tenant_id, SnapshotRow.source_id == source_id)
        .first()
    )
    return row is not None


def _latest_snapshot_sha(session: Session, *, tenant_id, source_id) -> str | None:
    row = (
        session.query(SnapshotRow.sha256)
        .filter(SnapshotRow.tenant_id == tenant_id, SnapshotRow.source_id == source_id)
        .order_by(SnapshotRow.snapshot_version.desc())
        .first()
    )
    return row[0] if row else None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _content_for_ingestion(source: RetrievedSource) -> tuple[str | None, str]:
    full_text = (source.full_text or "").strip()
    if full_text:
        return full_text, "full_text"
    abstract = (source.abstract or "").strip()
    if abstract:
        return abstract, "abstract"
    title = (source.title or "").strip()
    if title:
        return title, "title"
    return None, "missing"


def _fetch_selected_source_content(
    connector: ScientificPapersMCPConnector,
    source: RetrievedSource,
) -> RetrievedSource | None:
    identifier = source.to_canonical_string()
    try:
        fetched = connector.get_by_id(identifier)
    except Exception as exc:
        logger.warning("MCP content fetch failed for '%s': %s", identifier, exc)
        return None
    if not fetched:
        return None

    # Preserve search-time metadata when fetch-time payload does not include it.
    if not fetched.abstract:
        fetched.abstract = source.abstract
    if not fetched.pdf_url:
        fetched.pdf_url = source.pdf_url
    if not fetched.url:
        fetched.url = source.url
    if not fetched.authors:
        fetched.authors = source.authors
    if not fetched.year:
        fetched.year = source.year
    if source.citations_count is not None and fetched.citations_count is None:
        fetched.citations_count = source.citations_count

    merged_extra = dict(source.extra_metadata or {})
    merged_extra.update(fetched.extra_metadata or {})
    fetched.extra_metadata = merged_extra or None
    return fetched


def _ingest_selected_sources(
    *,
    session: Session,
    tenant_id,
    llm_provider: str | None,
    connector: ScientificPapersMCPConnector,
    selected: list[RankedCandidate],
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, int]:
    stats = {
        "attempted": 0,
        "ingested": 0,
        "skipped_existing": 0,
        "fallback_only": 0,
        "failed": 0,
    }
    if not selected:
        return stats

    if cancel_check is not None:
        cancel_check()
    embed_client = _get_embed_client(llm_provider)
    embedding_provider = _EmbeddingProviderAdapter(embed_client)

    # Phase 1: parallel fetch (pure I/O — no DB, no session)
    max_workers = env_int("RETRIEVER_INGEST_WORKERS", 4, min_value=1)
    fetched_map: dict[int, RetrievedSource | None] = {}

    def _fetch_one(
        args: tuple[int, RankedCandidate],
    ) -> tuple[int, RetrievedSource | None]:
        idx, candidate = args
        return idx, _fetch_selected_source_content(connector, candidate.source)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_one, (idx, c)): idx for idx, c in enumerate(selected)
        }
        for future in concurrent.futures.as_completed(futures):
            orig_idx = futures[future]
            try:
                result_idx, fetched = future.result()
                fetched_map[result_idx] = fetched
            except Exception as exc:
                fetched_map[orig_idx] = None
                logger.warning(
                    "Parallel fetch failed for candidate %d: %s", orig_idx, exc
                )
            if cancel_check is not None:
                cancel_check()

    # Phase 2: sequential DB ingest (SQLAlchemy sessions are not thread-safe)
    for idx, candidate in enumerate(selected):
        if cancel_check is not None:
            cancel_check()
        stats["attempted"] += 1
        source = candidate.source
        content_source = fetched_map.get(idx) or source
        content, content_origin = _content_for_ingestion(content_source)
        if not content:
            stats["failed"] += 1
            continue

        canonical_id = source.to_canonical_string()
        row = create_or_get_source(
            session=session,
            tenant_id=tenant_id,
            canonical_id=canonical_id,
            source_type=str(source.source_type.value),
            title=content_source.title,
            authors=content_source.authors or [],
            year=content_source.year,
            venue=content_source.venue,
            origin=source.connector,
            cited_by_count=content_source.citations_count,
            url=content_source.url,
            doi=content_source.canonical_id.doi,
            arxiv_id=content_source.canonical_id.arxiv_id,
            metadata=_build_metadata(content_source),
        )

        current_sha = _sha256_text(content)
        latest_sha = _latest_snapshot_sha(
            session, tenant_id=tenant_id, source_id=row.id
        )
        if latest_sha == current_sha:
            stats["skipped_existing"] += 1
            continue

        had_existing = _snapshot_exists_for_source(
            session, tenant_id=tenant_id, source_id=row.id
        )
        metadata = dict(content_source.extra_metadata or {})
        metadata.update(
            {
                "content_origin": content_origin,
                "ingested_via": "retriever",
            }
        )
        blob_ref = f"mcp:{canonical_id}:{content_origin}"
        ingest_source(
            session=session,
            tenant_id=tenant_id,
            canonical_id=canonical_id,
            source_type=str(content_source.source_type.value),
            raw_content=content,
            embedding_provider=embedding_provider,
            title=content_source.title,
            authors=content_source.authors or [],
            year=content_source.year,
            url=content_source.url,
            pdf_url=content_source.pdf_url,
            content_type="text/plain",
            blob_ref=blob_ref,
            metadata=metadata,
        )
        stats["ingested"] += 1
        if content_origin != "full_text":
            stats["fallback_only"] += 1
        if had_existing:
            logger.info(
                "Created new snapshot version for updated source '%s'", canonical_id
            )


def _create_run_checkpoint(
    session: Session,
    *,
    tenant_id,
    run_id,
    stage: str,
    payload: dict,
) -> None:
    row = RunCheckpointRow(
        tenant_id=tenant_id,
        run_id=run_id,
        stage=stage,
        payload_json=payload,
    )
    session.add(row)
    session.flush()


def _plan_step_labels(
    question: str,
    llm_provider: str | None,
    llm_model: str | None,
    stage_models: dict[str, str | None] | None = None,
) -> list[str] | None:
    """Return 6 LLM-planned step labels tailored to the research question.

    Returns None on any error so the caller can fall back to hardcoded labels.
    Never raises.
    """
    try:
        llm_client = get_llm_client_for_stage(
            "retrieve", llm_provider, llm_model, stage_models=stage_models
        )
        if llm_client is None:
            return None

        system = (
            "You are a research pipeline planner. Write exactly 6 short action phrases "
            "(max 10 words each) describing the steps of a research pipeline for the given "
            "question. The 6 steps are always: (1) search papers, (2) outline the report, "
            "(3) package evidence per section, (4) draft each section, (5) evaluate quality, "
            "(6) export the report. Tailor each phrase to the specific question. "
            "Return a JSON array of exactly 6 strings. No other output."
        )
        response = llm_client.generate(
            question,
            system=system,
            max_tokens=300,
            temperature=0.3,
        )
        payload = extract_json_payload(response)
        if (
            isinstance(payload, list)
            and len(payload) == 6
            and all(isinstance(s, str) for s in payload)
        ):
            return [s.strip() for s in payload]
        logger.warning(
            "Step label planning returned unexpected shape",
            extra={
                "event": "pipeline.llm.step_labels",
                "payload_type": type(payload).__name__,
            },
        )
        return None
    except Exception as exc:
        logger.warning(
            "Step label planning failed, using fallback labels",
            extra={"event": "pipeline.llm.step_labels", "reason": str(exc)},
        )
        return None


def _parallel_mcp_search(
    query_plan: list,
    connector,
    *,
    mcp_max_per_source: int,
    cancel_check: Callable[[], None] | None = None,
) -> list:
    """Search all query-plan entries in parallel using ThreadPoolExecutor."""
    parallel_queries = env_int("RETRIEVER_MCP_PARALLEL_QUERIES", 6, min_value=1)

    def _search_one(plan) -> list:
        try:
            sources = connector.search(query=plan.query, max_results=mcp_max_per_source)
            for src in sources:
                meta = dict(src.extra_metadata or {})
                meta.update({"intent": plan.intent, "query": plan.query})
                src.extra_metadata = meta
            return sources
        except Exception as exc:
            logger.warning("MCP retrieval failed for query '%s': %s", plan.query, exc)
            return []

    all_sources: list = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=parallel_queries
    ) as executor:
        futures = [executor.submit(_search_one, plan) for plan in query_plan]
        for future in concurrent.futures.as_completed(futures):
            if cancel_check is not None:
                cancel_check()
            all_sources.extend(future.result())
    return all_sources


@observe(name="retriever")
@instrument_node("retrieve")
def retriever_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    def _cancel_check() -> None:
        raise_if_run_cancel_requested(session, state.tenant_id, state.run_id)

    _cancel_check()
    question = state.user_query
    state.step_labels = _plan_step_labels(
        question=question,
        llm_provider=state.llm_provider,
        llm_model=state.llm_model,
        stage_models=state.stage_models,
    )

    query_plan, llm_used = _build_query_plan(
        question=question,
        llm_provider=state.llm_provider,
        llm_model=state.llm_model,
        stage_models=state.stage_models,
    )
    if not query_plan:
        raise ValueError("Question is required for retrieval")

    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.plan_created",
        stage="retrieve",
        data={
            "query_count": len(query_plan),
            "queries": [{"intent": p.intent, "query": p.query} for p in query_plan],
            "step_labels": state.step_labels,
            "llm_used": llm_used,
        },
    )

    mcp_rate = env_float("RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND", 2.0, min_value=0.1)
    logger.info(
        "MCP rate limit: %.1f req/s (RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND)", mcp_rate
    )
    mcp_connector = ScientificPapersMCPConnector(max_requests_per_second=mcp_rate)
    mcp_max_per_source = env_int("RETRIEVER_MCP_MAX_PER_SOURCE", 5, min_value=1)
    retrieved_by_source: dict[str, list[RetrievedSource]] = {}

    raw_sources = _parallel_mcp_search(
        query_plan,
        mcp_connector,
        mcp_max_per_source=mcp_max_per_source,
        cancel_check=_cancel_check,
    )
    _cancel_check()
    for src in raw_sources:
        retrieved_by_source.setdefault(src.connector, []).append(src)

    all_sources = [
        source for sources in retrieved_by_source.values() for source in sources
    ]
    deduped_sources, dedup_stats = deduplicate_sources(
        all_sources, prefer_connector="openalex"
    )
    found_by_source = {
        source: len(items) for source, items in retrieved_by_source.items()
    }
    kept_by_source = {
        source: count for source, count in dedup_stats.connectors_merged.items()
    }

    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.mcp_completed",
        stage="retrieve",
        data={
            "sources": mcp_connector.sources,
            "found_by_source": found_by_source,
            "kept_by_source": kept_by_source,
        },
    )

    candidate_count = len(deduped_sources)
    rerank_topk = _resolve_rerank_topk(candidate_count)
    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.rerank.started",
        stage="retrieve",
        data={"candidate_count": candidate_count, "topk": rerank_topk},
    )
    rerank_start = time.monotonic()
    rerank_stats: dict[str, int | bool] = {}
    ranked = _rank_sources(
        deduped_sources,
        query_plan,
        session=session,
        tenant_id=state.tenant_id,
        query_text=question,
        llm_provider=state.llm_provider,
        stats=rerank_stats,
        cancel_check=_cancel_check,
    )
    _cancel_check()
    latency_ms = int((time.monotonic() - rerank_start) * 1000)
    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.rerank.cache",
        stage="retrieve",
        data={
            "hits": int(rerank_stats.get("cache_hits", 0) or 0),
            "misses": int(rerank_stats.get("cache_misses", 0) or 0),
            "embedded_now": int(rerank_stats.get("embedded_now", 0) or 0),
            "batch_count": int(rerank_stats.get("batch_count", 0) or 0),
        },
    )
    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.rerank.completed",
        stage="retrieve",
        data={"latency_ms": latency_ms},
    )

    min_sources = env_int("RETRIEVER_MIN_SOURCES", 10, min_value=1)
    max_sources = env_int("RETRIEVER_MAX_SOURCES", 20, min_value=min_sources)
    available = len(ranked)
    if available >= min_sources:
        target_count = min(max_sources, available)
    else:
        target_count = available

    per_intent_cap = max(1, math.ceil(target_count / max(len(ALLOWED_INTENTS), 1)))
    selected = _select_diverse(ranked, target_count, per_intent_cap)
    ingestion_stats = _ingest_selected_sources(
        session=session,
        tenant_id=state.tenant_id,
        llm_provider=state.llm_provider,
        connector=mcp_connector,
        selected=selected,
        cancel_check=_cancel_check,
    )
    _cancel_check()

    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.ingestion.completed",
        stage="retrieve",
        data=ingestion_stats,
    )

    selected_refs: list[SourceRef] = []
    for candidate in selected:
        _cancel_check()
        source = candidate.source
        origin = source.connector
        row = _upsert_source(
            session, tenant_id=state.tenant_id, source=source, origin=origin
        )
        _upsert_run_source(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            source_id=row.id,
            score=candidate.score,
            origin=origin,
        )
        selected_refs.append(
            SourceRef(
                source_id=row.id,
                canonical_id=row.canonical_id,
                title=row.title or source.title,
                authors=list_source_author_names(row) or source.authors or [],
                abstract=source.abstract,
                year=row.year or source.year,
                venue=row.venue,
                doi=get_source_identifier(row, "doi"),
                arxiv_id=get_source_identifier(row, "arxiv_id"),
                url=row.url or source.url,
                pdf_url=source.pdf_url,
                connector=origin,
                origin=row.origin,
                cited_by_count=row.cited_by_count,
                quality_score=0.0,
            )
        )

    intent_counts: dict[str, int] = {}
    for candidate in selected:
        intent_counts[candidate.intent] = intent_counts.get(candidate.intent, 0) + 1

    _create_run_checkpoint(
        session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        stage="retrieval_summary",
        payload={
            "query_count": len(query_plan),
            "queries": [{"intent": p.intent, "query": p.query} for p in query_plan],
            "llm_used": llm_used,
            "retrieval_backend": "scientific-papers-mcp",
            "mcp_sources": mcp_connector.sources,
            "found_by_source": found_by_source,
            "kept_by_source": kept_by_source,
            "deduped_sources": len(deduped_sources),
            "selected_sources": len(selected_refs),
            "ingestion": ingestion_stats,
            "intent_counts": intent_counts,
        },
    )

    emit_node_progress(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.summary",
        stage="retrieve",
        data={"selected_sources_total": len(selected_refs)},
    )

    state.generated_queries = [p.query for p in query_plan]
    state.retrieved_sources = selected_refs
    state.vetted_sources = selected_refs
    state.evidence_snippets = []

    return state
