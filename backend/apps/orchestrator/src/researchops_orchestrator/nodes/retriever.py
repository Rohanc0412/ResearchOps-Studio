"""
Retriever node - generates diverse queries and retrieves sources.

Uses OpenAlex + arXiv to collect candidate sources, deduplicate, rank,
and select a diverse set of sources for the run.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import math
import os
import re
import time
from typing import Iterable, Protocol


from sqlalchemy.orm import Session

from db.models.run_checkpoints import RunCheckpointRow
from db.models.run_sources import RunSourceRow
from db.models.source_embeddings import SourceEmbeddingRow
from db.models.sources import SourceRow
from researchops_connectors import ArXivConnector, OpenAlexConnector
from researchops_connectors.base import RetrievedSource
from researchops_connectors.dedup import deduplicate_sources
from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import OrchestratorState, SourceRef
from researchops_llm import LLMError, get_llm_client_for_stage, json_response_format
from researchops_orchestrator.embeddings import get_sentence_transformer_client

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


def _log_llm_exchange(label: str, content: str) -> None:
    if not content:
        return
    message = "LLM request sent for retrieval" if label == "request" else "LLM response received for retrieval"
    log_full = os.getenv("LLM_LOG_FULL", "").strip().lower() in {"1", "true", "yes", "on"}
    if log_full:
        logger.info(f"{message}\n{content}")
        logger.info(
            message,
            extra={
                "event": "pipeline.llm",
                "stage": "retrieve",
                "label": label,
                "chars": len(content),
            },
        )
        return
    logger.info(
        message,
        extra={
            "event": "pipeline.llm",
            "stage": "retrieve",
            "label": label,
            "chars": len(content),
            "content": content,
        },
    )


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


def _env_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def _resolve_rerank_topk(candidate_count: int) -> int:
    if candidate_count <= 0:
        return 0
    topk = _env_int("RETRIEVER_RERANK_TOPK", 120, min_value=1)
    topk = min(topk, 200)
    return min(topk, candidate_count)


def _build_query_plan(
    question: str,
    llm_provider: str | None,
    llm_model: str | None,
) -> tuple[list[QueryPlan], bool]:
    base = " ".join(question.split())
    if not base:
        return [], False

    max_queries = _env_int("RETRIEVER_QUERY_COUNT", 8, min_value=6)

    llm_plans = _build_query_plan_with_llm(
        question=base,
        max_queries=max_queries,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    if not llm_plans:
        raise ValueError("LLM query generation failed or returned no queries.")

    return llm_plans, True


def _extract_json_payload(text: str) -> dict | list | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    start_candidates = [pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos != -1]
    if not start_candidates:
        return None
    start = min(start_candidates)
    end = cleaned.rfind("}") if cleaned[start] == "{" else cleaned.rfind("]")
    if end == -1 or end <= start:
        return None
    snippet = cleaned[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


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
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _clean_query_line(line: str) -> str:
    cleaned = re.sub(r"^\s*[-*•\d\)\.:\s]+", "", line).strip()
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
) -> list[QueryPlan]:
    try:
        llm_client = get_llm_client_for_stage("retrieve", llm_provider, llm_model)
    except LLMError as exc:
        logger.warning(
            "LLM client unavailable for query generation",
            extra={
                "event": "pipeline.llm.error",
                "stage": "retrieve",
                "reason": str(exc),
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )
        return []

    if llm_client is None:
        logger.warning(
            "LLM client disabled for query generation",
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
        "Generate 6 to 10 diverse academic search queries for the research question below.\n"
        "Return ONLY JSON with this schema:\n"
        "{\n"
        '  "queries": [\n'
        '    {"intent": "survey|methods|benchmarks|failure modes|future directions|recent work", "query": "..."}\n'
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
        _log_llm_exchange("request", prompt)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=600,
            temperature=0.4,
            response_format=json_response_format("query_plan", QUERY_PLAN_SCHEMA),
        )
    except LLMError as exc:
        logger.warning(
            "LLM query generation request failed",
            extra={
                "event": "pipeline.llm.error",
                "stage": "retrieve",
                "reason": str(exc),
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )
        return []

    _log_llm_exchange("response", response)
    payload = _extract_json_payload(response)
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
                "response_preview": response[:600] if response else "",
            },
        )
        fallback = _fallback_query_plan_from_text(response or "", max_queries)
        if fallback:
            logger.info(
                "Fallback query parsing recovered queries",
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

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def _resolve_embed_provider(llm_provider: str | None) -> str:
    raw = os.getenv("RETRIEVER_EMBED_PROVIDER")
    if raw and raw.strip():
        return raw.strip().lower()
    if llm_provider and llm_provider.strip():
        return llm_provider.strip().lower()
    return os.getenv("LLM_PROVIDER", "hosted").strip().lower()


def _resolve_embed_model(provider_name: str) -> str:
    for name in ("RETRIEVER_EMBED_MODEL",):
        raw = os.getenv(name)
        if raw and raw.strip():
            return raw.strip()
    if provider_name in {"local", "sentence-transformers", "bge"}:
        return "BAAI/bge-m3"
    return "text-embedding-3-small"


def _resolve_embed_device() -> str:
    raw = os.getenv("RETRIEVER_EMBED_DEVICE") or os.getenv("EMBEDDING_DEVICE")
    if raw and raw.strip():
        return raw.strip()
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_embed_dtype(device: str) -> str | None:
    raw = os.getenv("RETRIEVER_EMBED_DTYPE")
    if raw and raw.strip():
        return raw.strip().lower()
    if device.startswith("cuda"):
        return "float16"
    return None


def _resolve_embed_normalize() -> bool:
    raw = os.getenv("RETRIEVER_EMBED_NORMALIZE")
    if not raw:
        return True
    return raw.strip().lower() not in {"0", "false", "no"}


def _resolve_embed_max_seq_len() -> int | None:
    raw = os.getenv("RETRIEVER_EMBED_MAX_SEQ_LEN")
    if not raw or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _resolve_embed_trust_remote_code(model_name: str) -> bool:
    raw = os.getenv("RETRIEVER_EMBED_TRUST_REMOTE_CODE")
    if raw and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes"}
    return "bge-m3" in model_name.lower()


def _get_embed_client(llm_provider: str | None) -> EmbeddingClient | None:
    provider_name = _resolve_embed_provider(llm_provider)
    if provider_name in {"", "none", "disabled"}:
        raise EmbedError("Embeddings are required for reranking but provider is disabled.")
    if provider_name in {"local", "sentence-transformers", "bge"}:
        model_name = _resolve_embed_model(provider_name)
        device = _resolve_embed_device()
        normalize = _resolve_embed_normalize()
        max_seq_length = _resolve_embed_max_seq_len()
        dtype = _resolve_embed_dtype(device)
        trust_remote_code = _resolve_embed_trust_remote_code(model_name)
        return get_sentence_transformer_client(
            model_name=model_name,
            device=device,
            normalize_embeddings=normalize,
            max_seq_length=max_seq_length,
            dtype=dtype,
            trust_remote_code=trust_remote_code,
        )
    raise EmbedError(f"Unknown embedding provider: {provider_name}")


def _embedding_text_for_source(source: RetrievedSource) -> str:
    title = (source.title or "").strip()
    abstract = (source.abstract or "").strip()
    if title and abstract:
        text = f"{title}\n\n{abstract}"
    else:
        text = title or abstract
    text = text.strip()
    max_chars = _env_int("RETRIEVER_EMBED_TEXT_MAX_CHARS", 7000, min_value=1000)
    if len(text) > max_chars:
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
    for l_val, r_val in zip(left, right):
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
    now = datetime.utcnow()
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
    current_year = datetime.utcnow().year
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
        for plan, tokens in zip(query_plan, query_tokens):
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
        if not query_text.strip():
            raise EmbedError("Embeddings require a non-empty query text.")
        embed_client = _get_embed_client(llm_provider)
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
            text = _embedding_text_for_source(sources_list[idx])
            if not text:
                stats["cache_misses"] += 1
                continue
            text_hash = _embedding_text_hash(text)
            canonical_id = canonical_map[idx]
            cached_row = cached.get(canonical_id)
            if cached_row and cached_row.text_hash == text_hash:
                stats["cache_hits"] += 1
                embed_norms[idx] = (1.0 + _cosine_similarity(query_embedding, cached_row.embedding_json)) / 2.0
                continue
            stats["cache_misses"] += 1
            texts_to_embed.append(text)
            pending.append((idx, canonical_id, text_hash, cached_row))

        batch_size = _env_int("RETRIEVER_EMBED_BATCH", 32, min_value=1)
        stats["batch_count"] = math.ceil(len(texts_to_embed) / batch_size) if texts_to_embed else 0
        if texts_to_embed:
            vectors = _embed_texts_batched(embed_client, texts_to_embed, batch_size=batch_size)
            if len(vectors) != len(texts_to_embed):
                raise EmbedError(
                    f"Embedding batch size mismatch: expected {len(texts_to_embed)} got {len(vectors)}"
                )
            for (idx, canonical_id, text_hash, cached_row), vector in zip(pending, vectors):
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
                embed_norms[idx] = (1.0 + _cosine_similarity(query_embedding, vector)) / 2.0

    weights = {
        "bm25": _env_float("RETRIEVER_WEIGHT_BM25", 0.55, min_value=0.0),
        "embed": _env_float("RETRIEVER_WEIGHT_EMBED", 0.30, min_value=0.0),
        "recency": _env_float("RETRIEVER_WEIGHT_RECENCY", 0.10, min_value=0.0),
        "citation": _env_float("RETRIEVER_WEIGHT_CITATION", 0.05, min_value=0.0),
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

    for candidate in candidates:
        if len(selected) >= target_count:
            break
        intent = candidate.intent
        if intent_counts.get(intent, 0) >= per_intent_cap:
            continue
        selected.append(candidate)
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

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
    canonical_id = source.to_canonical_string()
    row = (
        session.query(SourceRow)
        .filter(SourceRow.tenant_id == tenant_id, SourceRow.canonical_id == canonical_id)
        .one_or_none()
    )
    now = datetime.utcnow()
    metadata = _build_metadata(source)

    doi = source.canonical_id.doi
    arxiv_id = source.canonical_id.arxiv_id

    if row:
        updated = False
        if source.title and row.title != source.title:
            row.title = source.title
            updated = True
        if source.authors and row.authors_json != source.authors:
            row.authors_json = source.authors
            updated = True
        if source.year and row.year != source.year:
            row.year = source.year
            updated = True
        if source.venue and row.venue != source.venue:
            row.venue = source.venue
            updated = True
        if doi and row.doi != doi:
            row.doi = doi
            updated = True
        if arxiv_id and row.arxiv_id != arxiv_id:
            row.arxiv_id = arxiv_id
            updated = True
        if source.url and row.url != source.url:
            row.url = source.url
            updated = True
        if origin and row.origin != origin:
            row.origin = origin
            updated = True
        if source.citations_count is not None:
            if row.cited_by_count is None or source.citations_count > row.cited_by_count:
                row.cited_by_count = source.citations_count
                updated = True
        if metadata:
            merged = dict(row.metadata_json or {})
            for key, value in metadata.items():
                if value is None:
                    continue
                if key not in merged or merged[key] in (None, "", [], {}):
                    merged[key] = value
            if merged != row.metadata_json:
                row.metadata_json = merged
                updated = True
        if updated:
            row.updated_at = now
            session.flush()
        return row

    row = SourceRow(
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        source_type=str(source.source_type.value),
        title=source.title,
        authors_json=source.authors or [],
        year=source.year,
        venue=source.venue,
        doi=doi,
        arxiv_id=arxiv_id,
        url=source.url,
        origin=origin,
        cited_by_count=source.citations_count,
        metadata_json=metadata,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


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


def _create_run_checkpoint(session: Session, *, tenant_id, run_id, stage: str, payload: dict) -> None:
    row = RunCheckpointRow(
        tenant_id=tenant_id,
        run_id=run_id,
        stage=stage,
        payload_json=payload,
    )
    session.add(row)
    session.flush()


@instrument_node("retrieve")
def retriever_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    question = state.user_query
    query_plan, llm_used = _build_query_plan(
        question=question,
        llm_provider=state.llm_provider,
        llm_model=state.llm_model,
    )
    if not query_plan:
        raise ValueError("Question is required for retrieval")

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.plan_created",
        stage="retrieve",
        data={
            "query_count": len(query_plan),
            "queries": [{"intent": p.intent, "query": p.query} for p in query_plan],
            "llm_used": llm_used,
        },
    )

    openalex = OpenAlexConnector(email=os.getenv("OPENALEX_EMAIL"))
    arxiv = ArXivConnector()

    openalex_max = _env_int("RETRIEVER_OPENALEX_MAX", 5, min_value=1)
    arxiv_max = _env_int("RETRIEVER_ARXIV_MAX", 5, min_value=1)

    openalex_sources: list[RetrievedSource] = []
    arxiv_sources: list[RetrievedSource] = []

    for plan in query_plan:
        try:
            sources = openalex.search(query=plan.query, max_results=openalex_max)
            for src in sources:
                meta = dict(src.extra_metadata or {})
                meta.update({"intent": plan.intent, "query": plan.query})
                src.extra_metadata = meta
            openalex_sources.extend(sources)
        except Exception as exc:
            pass

        try:
            sources = arxiv.search(query=plan.query, max_results=arxiv_max)
            for src in sources:
                meta = dict(src.extra_metadata or {})
                meta.update({"intent": plan.intent, "query": plan.query})
                src.extra_metadata = meta
            arxiv_sources.extend(sources)
        except Exception as exc:
            pass

    all_sources = openalex_sources + arxiv_sources
    deduped_sources, dedup_stats = deduplicate_sources(all_sources, prefer_connector="openalex")

    kept_openalex = sum(1 for s in deduped_sources if s.connector == "openalex")
    kept_arxiv = sum(1 for s in deduped_sources if s.connector == "arxiv")

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.openalex_completed",
        stage="retrieve",
        data={"found": len(openalex_sources), "kept": kept_openalex},
    )
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.arxiv_completed",
        stage="retrieve",
        data={"found": len(arxiv_sources), "kept": kept_arxiv},
    )

    candidate_count = len(deduped_sources)
    rerank_topk = _resolve_rerank_topk(candidate_count)
    emit_run_event(
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
    )
    latency_ms = int((time.monotonic() - rerank_start) * 1000)
    emit_run_event(
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
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.rerank.completed",
        stage="retrieve",
        data={"latency_ms": latency_ms},
    )

    min_sources = _env_int("RETRIEVER_MIN_SOURCES", 10, min_value=1)
    max_sources = _env_int("RETRIEVER_MAX_SOURCES", 20, min_value=min_sources)
    available = len(ranked)
    if available >= min_sources:
        target_count = min(max_sources, available)
    else:
        target_count = available

    per_intent_cap = max(1, math.ceil(target_count / max(len(ALLOWED_INTENTS), 1)))
    selected = _select_diverse(ranked, target_count, per_intent_cap)

    selected_refs: list[SourceRef] = []
    for candidate in selected:
        source = candidate.source
        origin = source.connector
        row = _upsert_source(session, tenant_id=state.tenant_id, source=source, origin=origin)
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
                    authors=list(row.authors_json or source.authors or []),
                    abstract=source.abstract,
                    year=row.year or source.year,
                    venue=row.venue,
                    doi=row.doi,
                arxiv_id=row.arxiv_id,
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
            "found_openalex": len(openalex_sources),
            "found_arxiv": len(arxiv_sources),
            "kept_openalex": kept_openalex,
            "kept_arxiv": kept_arxiv,
            "deduped_sources": len(deduped_sources),
            "selected_sources": len(selected_refs),
            "intent_counts": intent_counts,
        },
    )

    emit_run_event(
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
