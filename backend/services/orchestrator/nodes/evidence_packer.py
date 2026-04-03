"""
Evidence pack node - builds section-level evidence packs.

Selects semantically relevant snippets per section and stores membership
in section_evidence to gate what the writer can cite.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from runtime import ResearchRuntime

from core.orchestrator.state import (
    EvidenceSnippetRef,
    OrchestratorState,
    OutlineSection,
)
from core.pipeline_events.events import emit_node_progress
from db.models.run_events import RunEventAudienceDb, RunEventLevelDb
from db.models.section_evidence import SectionEvidenceRow
from db.models.snapshots import SnapshotRow
from db.models.snippet_embeddings import SnippetEmbeddingRow
from db.models.snippets import SnippetRow
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
from langfuse.decorators import observe
from retrieval.search import search_snippets
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    model_name: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


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


def _get_embed_client() -> EmbeddingClient:
    provider = resolve_embed_provider()
    if provider == "ollama":
        model_name = resolve_embed_model(provider)
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        timeout_seconds = _env_int("OLLAMA_TIMEOUT_SECONDS", 60, min_value=5)
        return get_ollama_client(
            model_name=model_name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    if provider in {"hf", "huggingface", "hosted", "inference"}:
        model_name = resolve_embed_model(provider)
        base_url = os.getenv(
            "HF_INFERENCE_BASE_URL",
            "https://router.huggingface.co/hf-inference/models",
        ).strip()
        api_key = os.getenv("HF_TOKEN", "").strip()
        if not api_key:
            raise ValueError("HF_TOKEN is required for hosted embeddings.")
        timeout_seconds = _env_int("HF_TIMEOUT_SECONDS", 60, min_value=5)
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
    if provider == "bedrock":
        region_name = resolve_bedrock_embed_region_name()
        model_name = resolve_embed_model(provider)
        if not region_name:
            raise ValueError(
                "Bedrock embeddings require BEDROCK_EMBED_REGION or "
                "BEDROCK_REGION/AWS_REGION/AWS_DEFAULT_REGION."
            )
        if not model_name or not model_name.strip():
            raise ValueError("Bedrock embeddings require BEDROCK_EMBED_MODEL.")
        return get_bedrock_client(
            model_name=model_name,
            region_name=region_name,
            batch_size=resolve_bedrock_embed_batch_size(),
            max_concurrency=resolve_bedrock_embed_concurrency(),
            timeout_seconds=resolve_bedrock_embed_timeout_seconds(),
        )

    model_name = resolve_embed_model(provider)
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


def _embed_texts_batched(
    client: EmbeddingClient, texts: list[str], *, batch_size: int
) -> list[list[float]]:
    if not texts:
        return []
    if isinstance(client, BedrockEmbedClient):
        return client.embed_texts(texts)
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
        n_chunks = _env_int("EMBED_CHUNKS", pool_size, min_value=1)
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
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(client.embed_texts(batch))
    return embeddings


async def _parallel_search_sections_async(
    section_queries: list[tuple[str, list[list[float]]]],
    async_engine,
    *,
    tenant_id,
    embedding_model: str,
    source_ids: list,
    search_limit: int,
    min_similarity: float,
    min_required: int,
) -> dict[str, list[dict]]:
    """
    Run search_snippets for each section concurrently using asyncio.gather.

    Each section gets its own AsyncSession. Inside each task, session.run_sync
    provides the greenlet context that asyncpg requires — no OS threads involved.
    Returns a dict mapping section_id → raw search results.

    Fail-fast: any section error propagates out of gather, aborting the evidence
    pack. A pgvector error on one section likely indicates a systemic issue and
    proceeding with partial evidence would silently produce an under-evidenced report.
    """
    parallel = _env_int("EVIDENCE_PACK_PARALLEL_SECTIONS", 4, min_value=1)
    semaphore = asyncio.Semaphore(parallel)

    async def _search_one(
        section_id: str, query_embeddings: list[list[float]]
    ) -> tuple[str, list[dict]]:
        async with semaphore:
            async with AsyncSession(async_engine, expire_on_commit=False) as s:
                def _sync(sync_session) -> tuple[str, list[dict]]:
                    all_results: list[dict] = []
                    for qe in query_embeddings:
                        all_results.extend(
                            search_snippets(
                                session=sync_session,
                                tenant_id=tenant_id,
                                query_embedding=qe,
                                embedding_model=embedding_model,
                                limit=search_limit,
                                min_similarity=min_similarity,
                                source_ids=source_ids or None,
                            )
                        )
                    merged = _dedupe_results(all_results)
                    if len(merged) < min_required:
                        relaxed: list[dict] = []
                        for qe in query_embeddings:
                            relaxed.extend(
                                search_snippets(
                                    session=sync_session,
                                    tenant_id=tenant_id,
                                    query_embedding=qe,
                                    embedding_model=embedding_model,
                                    limit=search_limit + 30,
                                    min_similarity=max(0.0, min_similarity - 0.15),
                                    source_ids=source_ids or None,
                                )
                            )
                        merged = _dedupe_results(merged + relaxed)
                    return section_id, merged

                return await s.run_sync(_sync)

    tasks = [_search_one(sid, qe) for sid, qe in section_queries]
    pairs = await asyncio.gather(*tasks)
    return dict(pairs)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _section_query_texts(section: OutlineSection, max_queries: int = 5) -> list[str]:
    """Return up to max_queries search strings for a section.

    Generates one query per angle rather than one combined blob:
      1. title + goal  (main intent)
      2. title + each key point  (specific angles)
      3. each evidence theme  (specific topics)

    More queries → more diverse snippet candidates → better evidence coverage.
    """
    queries: list[str] = []

    # 1. Main query: title + goal
    main = " ".join(p for p in [section.title, section.goal] if p).strip()
    if main:
        queries.append(main)

    # 2. One query per key point (prefixed with title for context)
    for kp in section.key_points:
        if len(queries) >= max_queries:
            break
        kp = kp.strip()
        if kp:
            queries.append(f"{section.title} {kp}".strip() if section.title else kp)

    # 3. One query per evidence theme
    for theme in section.suggested_evidence_themes:
        if len(queries) >= max_queries:
            break
        theme = theme.strip()
        if theme:
            queries.append(theme)

    return queries or ([section.title] if section.title else ["research"])


def _dedupe_results(results: Iterable[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for result in results:
        snippet_id = str(result["snippet_id"])
        if (
            snippet_id not in seen
            or result["similarity"] > seen[snippet_id]["similarity"]
        ):
            seen[snippet_id] = result
    return list(seen.values())


def _select_diverse_snippets(
    results: list[dict],
    *,
    max_count: int,
    per_source_cap: int,
) -> list[dict]:
    selected: list[dict] = []
    selected_ids: set[int] = set()
    source_counts: dict[str, int] = {}

    for result in results:
        if len(selected) >= max_count:
            break
        source_id = str(result["source_id"])
        if source_counts.get(source_id, 0) >= per_source_cap:
            continue
        selected.append(result)
        selected_ids.add(id(result))
        source_counts[source_id] = source_counts.get(source_id, 0) + 1

    if len(selected) < max_count:
        for result in results:
            if len(selected) >= max_count:
                break
            if id(result) in selected_ids:
                continue
            selected.append(result)

    return selected


def _ensure_snippets_from_abstracts(
    session: Session,
    *,
    tenant_id,
    vetted_sources: list,
    embed_client: EmbeddingClient,
    embedding_model: str,
) -> None:
    if not vetted_sources:
        return

    source_ids = [source.source_id for source in vetted_sources]
    # Only skip the abstract fallback if embeddings with the right model already exist.
    # Checking for SnippetRow alone is not enough — old snippets may exist but be embedded
    # under a different model name, in which case the evidence search would still return nothing.
    exists_embedding = (
        session.query(SnippetEmbeddingRow.id)
        .join(SnippetRow, SnippetRow.id == SnippetEmbeddingRow.snippet_id)
        .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
        .filter(
            SnippetEmbeddingRow.tenant_id == tenant_id,
            SnippetEmbeddingRow.embedding_model == embedding_model,
            SnapshotRow.source_id.in_(source_ids),
        )
        .first()
    )
    if exists_embedding:
        return

    # Phase 1: create all snapshots, flush once to get IDs.
    pending: list[tuple[SnapshotRow, str]] = []
    for source in vetted_sources:
        text = (source.abstract or source.title or "").strip()
        if not text:
            continue
        snapshot_version = _next_snapshot_version(session, tenant_id, source.source_id)
        snapshot = SnapshotRow(
            tenant_id=tenant_id,
            source_id=source.source_id,
            snapshot_version=snapshot_version,
            content_type="text/plain",
            blob_ref=f"abstract:{source.canonical_id}",
            sha256=_sha256_hex(text),
            size_bytes=len(text),
            metadata_json={"origin": "abstract_fallback"},
        )
        session.add(snapshot)
        pending.append((snapshot, text))
    if pending:
        session.flush()

    # Phase 2: create all snippets, flush once to get IDs.
    new_snippets: list[tuple[SnippetRow, str]] = []
    for snapshot, text in pending:
        snippet = SnippetRow(
            tenant_id=tenant_id,
            snapshot_id=snapshot.id,
            snippet_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=None,
            sha256=_sha256_hex(text),
            risk_flags_json={},
        )
        session.add(snippet)
        new_snippets.append((snippet, text))
    if new_snippets:
        session.flush()

    if not new_snippets:
        return

    batch_size = _env_int("EVIDENCE_EMBED_BATCH", 16, min_value=1)
    vectors = _embed_texts_batched(
        embed_client,
        [text for _, text in new_snippets],
        batch_size=batch_size,
    )
    if len(vectors) != len(new_snippets):
        raise ValueError(
            "Mismatch between snippets and embeddings for abstract fallback."
        )

    for (snippet, _), vector in zip(new_snippets, vectors, strict=True):
        session.add(
            SnippetEmbeddingRow(
                tenant_id=tenant_id,
                snippet_id=snippet.id,
                embedding_model=embedding_model,
                dims=len(vector),
                embedding=vector,
            )
        )
    session.flush()


def _next_snapshot_version(session: Session, tenant_id, source_id) -> int:
    latest = (
        session.query(SnapshotRow.snapshot_version)
        .filter(SnapshotRow.tenant_id == tenant_id, SnapshotRow.source_id == source_id)
        .order_by(SnapshotRow.snapshot_version.desc())
        .first()
    )
    return (latest[0] + 1) if latest else 1


def _persist_section_evidence(
    session: Session,
    *,
    tenant_id,
    run_id,
    section_id: str,
    snippet_ids: list,
) -> None:
    session.query(SectionEvidenceRow).filter(
        SectionEvidenceRow.tenant_id == tenant_id,
        SectionEvidenceRow.run_id == run_id,
        SectionEvidenceRow.section_id == section_id,
    ).delete()

    rows = [
        SectionEvidenceRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            snippet_id=snippet_id,
        )
        for snippet_id in snippet_ids
    ]
    if rows:
        session.bulk_save_objects(rows)
    session.flush()


@observe(name="evidence_packer")
async def evidence_pack_node(
    state: OrchestratorState, runtime: "ResearchRuntime"
) -> OrchestratorState:
    outline = state.outline
    if outline is None or not outline.sections:
        raise ValueError("Outline is required before building evidence packs.")

    # Emit stage_start
    await runtime.event_store.append(
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        audience=RunEventAudienceDb.progress,
        event_type="stage_start",
        level=RunEventLevelDb.info,
        stage="evidence_pack",
        message="Starting stage: evidence_pack",
        payload={"iteration": state.iteration_count},
    )

    embed_client = _get_embed_client()
    embedding_model = embed_client.model_name

    # Abstract-fallback: write via run_sync (sync ORM helper)
    await runtime.session.run_sync(
        lambda s: _ensure_snippets_from_abstracts(
            s,
            tenant_id=state.tenant_id,
            vetted_sources=state.vetted_sources,
            embed_client=embed_client,
            embedding_model=embedding_model,
        )
    )

    source_ids = [source.source_id for source in state.vetted_sources]
    search_limit = _env_int("EVIDENCE_SEARCH_LIMIT", 60, min_value=10)
    min_similarity = _env_float("EVIDENCE_MIN_SIMILARITY", 0.35, min_value=0.0)
    min_required = _env_int("EVIDENCE_MIN_REQUIRED", 5, min_value=1)
    min_snippets = _env_int("EVIDENCE_SNIPPET_MIN", 8, min_value=1)
    max_snippets = _env_int("EVIDENCE_SNIPPET_MAX", 20, min_value=min_snippets)
    per_source_cap = _env_int("EVIDENCE_PER_SOURCE_CAP", 3, min_value=1)
    embed_batch_size = _env_int("EVIDENCE_EMBED_BATCH", 16, min_value=1)

    evidence_refs: dict[str, EvidenceSnippetRef] = {}
    section_snippet_refs: dict[str, list[EvidenceSnippetRef]] = {}

    max_queries_per_section = _env_int(
        "EVIDENCE_MAX_QUERIES_PER_SECTION", 5, min_value=1
    )
    section_queries: list[tuple[OutlineSection, list[str]]] = []
    for section in outline.sections:
        query_texts = _section_query_texts(section, max_queries=max_queries_per_section)
        if query_texts:
            section_queries.append((section, query_texts))

    # Flatten all query texts into one list for a single batch embed call, then reshape.
    all_query_texts = [text for _, texts in section_queries for text in texts]
    all_query_vectors = _embed_texts_batched(
        embed_client,
        all_query_texts,
        batch_size=embed_batch_size,
    )
    if len(all_query_vectors) != len(all_query_texts):
        raise ValueError("Mismatch between section query texts and embeddings.")

    # Reshape flat vector list back into per-section lists.
    section_vector_lists: list[tuple[OutlineSection, list[list[float]]]] = []
    idx = 0
    for section, texts in section_queries:
        n = len(texts)
        section_vector_lists.append((section, all_query_vectors[idx : idx + n]))
        idx += n

    # Commit abstract-fallback work so per-section sessions can see the new embeddings.
    await runtime.session.commit()

    # Parallel search: each section gets its own AsyncSession
    # AsyncSession.get_bind() delegates to the underlying sync Session and returns
    # a plain Engine, not an AsyncEngine. Wrap it so AsyncSession() accepts it.
    async_engine = AsyncEngine(runtime.session.get_bind())
    search_inputs = [
        (section.section_id, query_embeddings)
        for section, query_embeddings in section_vector_lists
    ]
    section_raw_results = await _parallel_search_sections_async(
        search_inputs,
        async_engine,
        tenant_id=state.tenant_id,
        embedding_model=embedding_model,
        source_ids=source_ids,
        search_limit=search_limit,
        min_similarity=min_similarity,
        min_required=min_required,
    )

    # Post-process and persist (uses main session)
    for section, _ in section_vector_lists:
        results = section_raw_results.get(section.section_id, [])
        results = sorted(results, key=lambda item: item["similarity"], reverse=True)
        selected = _select_diverse_snippets(
            results,
            max_count=max_snippets,
            per_source_cap=per_source_cap,
        )

        if len(selected) < min_snippets and len(results) > len(selected):
            selected = _select_diverse_snippets(
                results,
                max_count=min_snippets,
                per_source_cap=max(per_source_cap, min_snippets),
            )

        snippet_ids = [item["snippet_id"] for item in selected]
        await runtime.session.run_sync(
            lambda s, _sid=section.section_id, _snips=snippet_ids: _persist_section_evidence(
                s,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                section_id=_sid,
                snippet_ids=_snips,
            )
        )

        section_refs: list[EvidenceSnippetRef] = []
        for item in selected:
            snippet_id = str(item["snippet_id"])
            ref = evidence_refs.get(snippet_id)
            if ref is None:
                snippet_text = item["snippet_text"] or ""
                char_start = item["char_start"] if item["char_start"] is not None else 0
                char_end = (
                    item["char_end"]
                    if item["char_end"] is not None
                    else len(snippet_text)
                )
                ref = EvidenceSnippetRef(
                    snippet_id=item["snippet_id"],
                    source_id=item["source_id"],
                    text=snippet_text,
                    char_start=char_start,
                    char_end=char_end,
                )
                evidence_refs[snippet_id] = ref
            section_refs.append(ref)
        section_snippet_refs[section.section_id] = section_refs

        # Emit per-section progress event
        await runtime.event_store.append(
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            audience=RunEventAudienceDb.progress,
            event_type="evidence_pack.created",
            level=RunEventLevelDb.info,
            stage="evidence_pack",
            message="evidence_pack.created: evidence_pack",
            payload={
                "section_id": section.section_id,
                "snippet_count": len(snippet_ids),
            },
        )

    state.evidence_snippets = list(evidence_refs.values())
    state.section_evidence_snippets = section_snippet_refs

    # Emit stage_finish
    await runtime.event_store.append(
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        audience=RunEventAudienceDb.progress,
        event_type="stage_finish",
        level=RunEventLevelDb.info,
        stage="evidence_pack",
        message="Finished stage: evidence_pack",
        payload={"success": True, "iteration": state.iteration_count},
    )

    return state
