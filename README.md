# ResearchOps Studio

AI-powered research pipeline with automated grounding evaluation.

## What it does

ResearchOps Studio takes a research question, retrieves academic sources from multiple databases (OpenAlex, arXiv, Europe PMC, CORE) via MCP connectors, drafts a structured report with inline citations, then runs an automated grounding evaluation — scoring each section for faithfulness to the source pack and flagging unsupported or contradicted claims.

## Architecture

```mermaid
flowchart LR
    User([User]) --> FE["React Frontend\nVite · TanStack Query\n:5173"]
    FE -->|REST + SSE| API["FastAPI API\n:8000"]
    API --> DB[("PostgreSQL\n+ pgvector")]
    API --> Jobs["Job Queue\n(DB-backed)"]
    Jobs --> Worker["Worker Process\n(poll loop)"]
    Worker --> Pipeline["LangGraph Pipeline"]
    Pipeline --> N1["① Retrieve\nMCP sources"]
    Pipeline --> N2["② Outline"]
    Pipeline --> N3["③ Draft\nw/ citations"]
    Pipeline --> N4["④ Evaluate\ngrounding"]
    Pipeline --> N5["⑤ Repair"]
    Pipeline --> N6["⑥ Export"]
    Pipeline --> DB
    Pipeline -.->|traces| LF["Langfuse\n(optional)"]
    API -->|SSE events| FE
```

## What it produces

After a run completes the evaluation tab shows grounding metrics for every report section:

```json
{
  "grounding_pct": 91,
  "faithfulness_pct": 88,
  "sections_passed": 9,
  "sections_total": 11,
  "issues_by_type": {
    "missing_citation": 3,
    "unsupported": 2
  }
}
```

`grounding_pct` is the share of sections that pass citation verification. `faithfulness_pct` measures claim-to-source alignment. `issues_by_type` enumerates detected problems by category so you can see at a glance where the draft needs attention.

## Quickstart

**Prerequisites:** Python 3.11, Node 20, PostgreSQL 16 with the `pgvector` extension.

```bash
# 1. Clone and configure
cp .env.example .env   # fill in required vars below

# 2. Python dependencies
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 3. Database
alembic upgrade head          # run from backend/

# 4. Start API (new terminal)
cd backend
PYTHONPATH=./services/api:./services/orchestrator:./libs:./data \
  python -m main

# 5. Start worker (new terminal)
cd backend
PYTHONPATH=./services/workers:./services/orchestrator:./libs:./data \
  python -m main

# 6. Start frontend (new terminal)
cd frontend/dashboard
npm ci && npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

**Required `.env` vars:**

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `HOSTED_LLM_BASE_URL` | OpenAI-compatible endpoint. Optional when using standard OpenAI; defaults to `https://api.openai.com`. |
| `HOSTED_LLM_API_KEY` | API key for the hosted LLM endpoint. `OPENAI_API_KEY` is also accepted. |
| `HOSTED_LLM_MODEL` | Model name override. Defaults to `openai/gpt-4o-mini`; `OPENAI_MODEL` is also accepted. |
| `TAVILY_API_KEY` | Tavily search API key (web search in chat) |

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI, SQLAlchemy (async), asyncpg |
| Pipeline | LangGraph, httpx |
| Storage | PostgreSQL, pgvector |
| Frontend | React 18, Vite, TanStack Query |
| Observability | Structured JSON logs, Langfuse (optional) |
