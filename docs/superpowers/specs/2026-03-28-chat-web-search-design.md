# Chat Web Search — Design Spec

**Date:** 2026-03-28
**Status:** Approved

## Summary

Add web search capability to the ResearchOps Studio chat quick-answer path. The LLM decides autonomously when a web search is needed via tool calling. Search is powered by Tavily, which is purpose-built for LLM agents.

---

## Background

The chat feature has two response paths:

1. **Quick answer** — plain LLM call with recent conversation history (last 6 messages). No tools. Current behaviour.
2. **Research pipeline** — full orchestrator with academic source retrieval (OpenAlex, ArXiv, etc.).

Web search is being added exclusively to the quick answer path. The research pipeline is out of scope.

---

## Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Search provider | Tavily | Purpose-built for LLM agents, clean results, free tier |
| Trigger mechanism | LLM tool calling | LLM decides when to search; no wasted quota |
| LLM model | `HOSTED_LLM_MODEL` (current: `openai/gpt-4o-mini`) | Already configured, supports tool calling on OpenRouter |
| Model override | `CHAT_SEARCH_MODEL` env var | Allows independent chat model without touching pipeline config |
| Max searches per message | 1 | Keeps latency predictable |

---

## Architecture

The quick answer path in `_generate_quick_answer()` is upgraded from a single LLM call to a **tool-calling loop**:

```
User message
     │
     ▼
LLM call (with web_search tool definition)
     │
     ├─ Plain text response → return to user
     │
     └─ Tool call: web_search(query)
               │
               ▼
          Tavily search → [title, url, snippet, ...]
               │
               ▼
          LLM call (tool result injected as message)
               │
               ▼
          Final text response → return to user
```

---

## Components

### New: `backend/libs/search/tavily.py`

Thin wrapper around the `tavily-python` SDK.

```python
@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

async def search(query: str, max_results: int = 5) -> list[SearchResult]:
    ...
```

- Reads `TAVILY_API_KEY` from env
- If key is missing, raises `SearchNotConfiguredError` (caught upstream)
- Returns at most `max_results` results (default 5)

### Modified: `backend/libs/llm/__init__.py`

Pass optional `tools` parameter through to the OpenAI-compatible `/v1/chat/completions` call. No other changes to the LLM client.

### Modified: `backend/services/api/routes/chat.py` → `_generate_quick_answer()`

1. On startup / first call: check if `TAVILY_API_KEY` is set. If yes, include `web_search` tool definition in the LLM request. If no, omit tools (search silently disabled).
2. Parse LLM response:
   - If `finish_reason == "tool_calls"` → extract query → call `tavily.search()` → append tool result message → call LLM again for final answer.
   - If plain text → return directly.
3. Max one search round-trip per message.

### `.env` additions

```env
# =============================================================================
# Web Search (Tavily)
# =============================================================================
# Required to enable web search in the chat quick-answer path.
# Get a key at https://tavily.com — free tier: 1000 searches/month.
# Leave blank to disable web search (chat still works without it).
TAVILY_API_KEY=

# Optional: override the model used for chat quick answers with web search.
# Leave blank to use HOSTED_LLM_MODEL.
# Must be a model that supports tool/function calling on your provider.
# Browse tool-calling models: https://openrouter.ai/collections/tool-calling-models
CHAT_SEARCH_MODEL=
```

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| `TAVILY_API_KEY` not set | Log warning at startup; tool definition omitted; chat works normally without search |
| Tavily API error (timeout, rate limit, 5xx) | Catch exception; LLM answers from its own knowledge; no user-facing error |
| LLM returns no tool call | Return LLM's plain text answer directly |
| LLM model doesn't support tool calling | Same as above — `tools` parameter is ignored by the provider, plain answer returned |

---

## Testing

| Test | What it verifies |
|------|-----------------|
| `test_tavily_wrapper` | Mocked HTTP: correct result parsing, `SearchNotConfiguredError` when key missing |
| `test_quick_answer_with_tool_call` | Mock LLM returns tool call → Tavily called → result fed back → final answer returned |
| `test_quick_answer_plain_text` | Mock LLM returns plain text → Tavily never called |
| `test_quick_answer_tavily_error` | Tavily raises exception → LLM still produces answer → no crash |
| `test_quick_answer_no_api_key` | `TAVILY_API_KEY` unset → tools omitted from LLM call → plain answer returned |

---

## Out of Scope

- Web search in the research pipeline (uses academic MCP connectors)
- Multi-turn tool calling (more than 1 search per message)
- Surfacing search source links in the UI (may be a follow-up)
- Rate limiting / caching Tavily results
