# Bedrock Provider and Embeddings Design

Date: 2026-04-02
Status: Approved in conversation, pending implementation

## Goal

Add native AWS Bedrock support to the backend so research runs and chat flows can use Bedrock-hosted foundation models as a first-class LLM provider. Also add an optional Bedrock embedding provider that can be selected independently from the text-generation provider and still satisfies the current research pipeline's parallel embedding throughput requirements.

## Scope

In scope:

- Add `bedrock` as a supported `llm_provider` for research runs and chat requests.
- Add a native Bedrock LLM client for text generation in the backend LLM abstraction.
- Add an optional Bedrock embedding provider selected through embedding configuration.
- Preserve stage-model routing so Bedrock model IDs can be supplied globally, per run, or per stage.
- Preserve parallel embedding throughput by implementing bounded concurrent Bedrock embedding requests with stable output ordering.
- Add tests covering provider resolution, request validation, configuration failures, and Bedrock embedding concurrency behavior.
- Document required environment variables in the example env file and relevant docs.

Out of scope:

- Live integration tests against AWS Bedrock.
- UI changes beyond accepting the new provider where the current API contract requires it.
- Automatic migration of existing hosted/OpenAI-compatible users to Bedrock.
- Replacing the local sentence-transformers multiprocess pool.

## Current State

The backend currently supports only a single remote LLM provider path, `hosted`, through the LLM abstraction in `backend/libs/llm/__init__.py`. API request schemas and service guards explicitly restrict `llm_provider` to `hosted`. Embedding resolution is separate and currently chooses between local, Ollama, and Hugging Face style providers based on environment variables and optional provider hints.

This separation is useful and should be preserved. Bedrock should be added as:

- a first-class LLM provider in the LLM abstraction, and
- a first-class embedding provider in the embedding resolution path.

These two capabilities should remain independently selectable.

## Requirements

### Functional Requirements

1. Research runs must accept `llm_provider=bedrock`.
2. Chat requests must accept `llm_provider=bedrock`.
3. Bedrock model selection must support the same routing hierarchy already used by the pipeline:
   - explicit stage override
   - balanced profile env model
   - run-level model
   - provider default model
4. Bedrock embeddings must be selectable with `EMBED_PROVIDER=bedrock`.
5. Bedrock embeddings must support parallel processing compatible with the current retrieval pipeline.
6. Bedrock embedding results must preserve input order.
7. Missing Bedrock configuration must fail explicitly with actionable errors.
8. Existing `hosted` behavior must remain unchanged.

### Non-Functional Requirements

1. The implementation must not reduce current local embedding throughput or alter its worker-pool behavior.
2. Bedrock embedding parallelism must be bounded and configurable to avoid unbounded request fan-out.
3. The design must remain testable without real AWS credentials.
4. Errors must identify Bedrock-specific configuration or request failures rather than falling back silently.

## Approach Options Considered

### Option 1: First-class Bedrock provider for LLMs and embeddings

Add a dedicated Bedrock branch in the LLM client factory and a dedicated Bedrock embedding provider in the embedding resolver. Keep embeddings independently configurable via `EMBED_PROVIDER`.

Pros:

- Matches the current architecture cleanly.
- Keeps provider behavior explicit.
- Avoids coupling embedding behavior to text-generation provider selection.
- Minimizes regression risk for existing `hosted` users.

Cons:

- Slightly more implementation work than forcing Bedrock through existing `hosted` assumptions.

### Option 2: Auto-switch embeddings to Bedrock when `llm_provider=bedrock`

Use Bedrock embeddings by default whenever the LLM provider is Bedrock, unless overridden.

Pros:

- Convenient defaults for some users.

Cons:

- Hides cost and performance choices.
- Creates surprising retrieval behavior from an LLM-only request.
- Makes embedding config less explicit.

### Option 3: Bedrock generation only

Implement only Bedrock text generation and defer embeddings.

Pros:

- Smallest initial change.

Cons:

- Does not satisfy the approved requirement.

## Chosen Design

Implement Option 1.

Bedrock becomes a first-class provider in both the LLM path and embedding path. Embeddings remain independently controlled through embedding configuration, and Bedrock embeddings implement parallel remote batching instead of trying to reuse the local multiprocess worker pool.

## Architecture

### 1. LLM Provider Layer

Files primarily affected:

- `backend/libs/llm/__init__.py`
- API schema and validation layers that currently hard-code `hosted`

Add a Bedrock client implementation under the existing LLM abstraction. The client should:

- conform to the current `LLMProvider` protocol
- accept a Bedrock model ID
- use AWS Bedrock runtime or inference APIs for text generation
- surface failures as `LLMError`
- populate token counts when usage metadata is available, without failing if usage metadata is absent

The provider factory should accept `provider="bedrock"` and resolve a Bedrock client using AWS configuration and the resolved model name.

### 2. Bedrock Model Resolution

The current `resolve_model_for_stage()` flow should remain intact. Bedrock should reuse that routing behavior rather than introducing a parallel model-routing system.

Provider-specific default resolution should be extended so:

- hosted/OpenAI-compatible clients continue to use hosted defaults
- Bedrock clients use a Bedrock default model env var when no explicit model is passed

This keeps stage overrides and run-level model selection consistent across providers.

### 3. API Validation and Run Setup

Files primarily affected:

- `backend/services/api/routes/projects.py`
- `backend/services/api/routes/chat_schemas.py`
- `backend/services/api/app_services/project_runs.py`
- any related chat-route validation that normalizes allowed providers

Current request validation only allows `hosted`. This should be updated to allow `bedrock` as well.

Run creation should:

- accept `bedrock`
- resolve the default model using provider-aware logic
- reject unknown providers with a clear client-facing error

No silent coercion from `bedrock` to `hosted` should occur.

### 4. Embedding Provider Layer

Files primarily affected:

- `backend/services/orchestrator/embeddings.py`
- `backend/services/orchestrator/nodes/retriever.py`
- any supporting module created for Bedrock request execution

Add a Bedrock embedding client that supports:

- batch embedding requests where supported by the selected Bedrock model/API
- splitting large input lists into request-sized chunks
- bounded parallel execution across those chunks
- reassembly into original input order

This client should be selected when `resolve_embed_provider()` returns `bedrock`.

### 5. Parallel Processing Strategy for Bedrock Embeddings

The existing local path uses a multiprocess worker pool because the model is local and compute-bound. Bedrock embeddings are remote and network-bound, so parallelism should be implemented with bounded concurrent requests instead of local worker processes.

The Bedrock embedding client should:

- divide input texts into batches using a configurable batch size
- submit multiple batches concurrently using a bounded concurrency limit
- preserve original ordering by tracking batch indices
- fail fast if any batch returns an invalid shape or irrecoverable provider error

This satisfies the current pipeline requirement for parallel embedding throughput without misusing the local worker-pool abstraction.

### 6. Error Handling

Bedrock-specific failures should produce actionable errors:

- missing AWS region or credentials
- missing Bedrock text model when required
- missing Bedrock embedding model when `EMBED_PROVIDER=bedrock`
- response count mismatch
- malformed response payload
- provider HTTP or SDK failure

The system must not silently fall back to `hosted` or to another embedding provider.

## Configuration

### LLM Configuration

Add support for Bedrock-oriented environment variables:

- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN`
- `BEDROCK_MODEL`

The first implementation should keep stage-tier routing on the existing generic env vars `LLM_MODEL_CHEAP` and `LLM_MODEL_CAPABLE`, because the stage routing logic already returns raw model IDs. The only Bedrock-specific default required in the first pass is `BEDROCK_MODEL` for the final fallback case when no explicit model has been supplied by stage override, tier config, or run-level request.

### Embedding Configuration

Add Bedrock embedding configuration:

- `EMBED_PROVIDER=bedrock`
- `BEDROCK_EMBED_MODEL`
- `BEDROCK_EMBED_BATCH_SIZE`
- `BEDROCK_EMBED_CONCURRENCY`
- optional `BEDROCK_EMBED_TIMEOUT_SECONDS`

Embedding provider selection rules remain:

1. explicit embedding provider env var
2. llm provider hint
3. global `LLM_PROVIDER`
4. default local provider

When `EMBED_PROVIDER=bedrock`, the Bedrock embedding path is always used regardless of the text-generation provider.

## Data Flow

### Research Run with Bedrock LLM

1. API accepts `llm_provider=bedrock`.
2. Run creation resolves the effective Bedrock model.
3. Pipeline nodes call `get_llm_client_for_stage(...)`.
4. The LLM factory returns a Bedrock client.
5. Nodes generate text through the shared `generate(...)` interface.

### Retrieval with Bedrock Embeddings

1. Retrieval resolves `EMBED_PROVIDER`.
2. When the provider is `bedrock`, the retriever obtains a Bedrock embedding client.
3. The client splits texts into request-sized batches.
4. Batches execute concurrently up to the configured concurrency limit.
5. Results are reordered and flattened to match input order.
6. Downstream retrieval logic receives a standard `list[list[float]]`.

## Testing Strategy

### Unit Tests

Add tests for:

- `get_llm_client("bedrock", ...)` resolving a Bedrock client with valid config
- missing Bedrock config producing Bedrock-specific errors
- provider-aware default model resolution
- API schema acceptance of `bedrock`
- project-run creation accepting `bedrock`
- embedding provider resolution returning `bedrock`
- Bedrock embedding batching preserving order
- Bedrock embedding concurrency using bounded parallel execution
- Bedrock embedding response-shape validation

These tests should mock Bedrock transport or SDK calls. No live AWS dependency should be required.

### Regression Focus

Existing `hosted` tests should continue passing unchanged. If any test hard-codes `hosted` as the only valid provider, it should be updated only where the API contract intentionally changes.

## Implementation Notes

1. Prefer isolating provider-specific logic behind small client classes instead of growing a single monolithic client.
2. Keep Bedrock-specific env resolution in helper functions near the provider implementation.
3. Avoid broad refactors of the retrieval pipeline; add the Bedrock embedding path by extending existing provider-selection seams.
4. If Bedrock SDK usage introduces a new dependency, keep it narrow and document it in backend dependencies.

## Risks

1. Bedrock request and response formats vary by model family. The implementation should target the selected Bedrock API shape explicitly and avoid over-generalizing unsupported models.
2. Token usage metadata may not always be available in a shape matching the current hosted client assumptions.
3. Embedding model request limits may require conservative batch sizing defaults.
4. If the current embedding interfaces assume synchronous calls only, the concurrency implementation may need an internal executor while still presenting a synchronous external interface.

## Acceptance Criteria

The design is considered successfully implemented when:

1. A research run can be created with `llm_provider=bedrock`.
2. Chat requests can specify `llm_provider=bedrock`.
3. Bedrock model selection respects current stage routing behavior.
4. `EMBED_PROVIDER=bedrock` selects a Bedrock embedding client.
5. Bedrock embeddings process large text lists through bounded parallel batching and preserve order.
6. Missing Bedrock configuration fails with clear errors.
7. Existing hosted-provider behavior remains intact.
8. Automated tests cover the new provider and embedding-selection behavior.
