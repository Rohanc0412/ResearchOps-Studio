# Chat Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Tavily-powered web search to the chat quick-answer path via LLM tool calling — the LLM decides when to search, max one search per message.

**Architecture:** A new `backend/libs/search/tavily.py` wrapper calls the Tavily REST API using the already-present `httpx` dependency. A new `generate_with_tools()` method on `OpenAICompatibleClient` sends the tool definition and returns the raw message dict. `_generate_quick_answer()` in `chat.py` runs the two-step loop: first LLM call → if tool call returned, execute search and call LLM again → return text.

**Tech Stack:** Python, httpx (already installed), Tavily REST API, OpenAI-compatible tool calling.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/libs/search/__init__.py` | Package marker |
| Create | `backend/libs/search/tavily.py` | Tavily REST wrapper — `SearchResult`, `SearchNotConfiguredError`, `search()` |
| Modify | `backend/libs/llm/__init__.py` | Add `generate_with_tools()` to `OpenAICompatibleClient` |
| Modify | `backend/services/api/routes/chat.py` | Add `WEB_SEARCH_TOOL`, `_resolve_chat_model()`, update `_generate_quick_answer()` |
| Modify | `.env` | Add `TAVILY_API_KEY` and `CHAT_SEARCH_MODEL` variables |
| Create | `backend/tests/unit/test_tavily_search.py` | Unit tests for Tavily wrapper |
| Create | `backend/tests/unit/test_llm_tool_calling.py` | Unit tests for `generate_with_tools()` |
| Create | `backend/tests/unit/test_chat_web_search.py` | Unit tests for the tool-calling loop in `_generate_quick_answer()` |

---

## Task 1: Tavily search wrapper

**Files:**
- Create: `backend/libs/search/__init__.py`
- Create: `backend/libs/search/tavily.py`
- Create: `backend/tests/unit/test_tavily_search.py`

- [ ] **Step 1: Write the failing tests**

Note: `conftest.py` already adds `backend/libs` to sys.path, so no manual path manipulation is needed.

Create `backend/tests/unit/test_tavily_search.py`:

```python
from __future__ import annotations

import unittest.mock as mock

import pytest


def test_search_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from search.tavily import SearchNotConfiguredError, search
    with pytest.raises(SearchNotConfiguredError):
        search("test query")


def test_search_returns_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fake_response = {
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
        ]
    }
    mock_resp = mock.MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with mock.patch("httpx.post", return_value=mock_resp) as mock_post:
        from search import tavily
        import importlib
        importlib.reload(tavily)
        from search.tavily import search, SearchResult
        results = search("AI research")

    assert len(results) == 2
    assert results[0] == SearchResult(title="Result 1", url="https://example.com/1", snippet="Snippet 1")
    assert results[1] == SearchResult(title="Result 2", url="https://example.com/2", snippet="Snippet 2")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["query"] == "AI research"
    assert call_kwargs[1]["json"]["api_key"] == "test-key"


def test_search_respects_max_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fake_response = {
        "results": [
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Snippet {i}"}
            for i in range(10)
        ]
    }
    mock_resp = mock.MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with mock.patch("httpx.post", return_value=mock_resp):
        from search.tavily import search
        results = search("query", max_results=3)

    assert len(results) == 3
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && python -m pytest tests/unit/test_tavily_search.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'search'`

- [ ] **Step 3: Create the package and implementation**

Create `backend/libs/search/__init__.py` (empty):
```python
```

Create `backend/libs/search/tavily.py`:
```python
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

TAVILY_API_URL = "https://api.tavily.com/search"


class SearchNotConfiguredError(RuntimeError):
    """Raised when TAVILY_API_KEY is not set."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search(query: str, *, max_results: int = 5) -> list[SearchResult]:
    """Search the web via Tavily.

    Raises SearchNotConfiguredError if TAVILY_API_KEY is not set.
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise SearchNotConfiguredError("TAVILY_API_KEY is not set")

    response = httpx.post(
        TAVILY_API_URL,
        json={"api_key": api_key, "query": query, "max_results": max_results},
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("content", ""),
        )
        for r in data.get("results", [])[:max_results]
    ]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_tavily_search.py -v
```


Expected:
```
test_tavily_search.py::test_search_raises_when_key_missing PASSED
test_tavily_search.py::test_search_returns_results PASSED
test_tavily_search.py::test_search_respects_max_results PASSED
```

- [ ] **Step 6: Commit**

```bash
git add backend/libs/search/__init__.py backend/libs/search/tavily.py backend/tests/unit/test_tavily_search.py backend/tests/conftest.py
git commit -m "feat: add Tavily search wrapper with SearchResult and SearchNotConfiguredError"
```

---

## Task 2: Add `generate_with_tools()` to the LLM client

**Files:**
- Modify: `backend/libs/llm/__init__.py` (after line 153, inside `OpenAICompatibleClient`)
- Create: `backend/tests/unit/test_llm_tool_calling.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_llm_tool_calling.py`:

```python
from __future__ import annotations

import json
import unittest.mock as mock

from llm import LLMError, OpenAICompatibleClient

CLIENT = OpenAICompatibleClient(
    base_url="https://openrouter.ai/api",
    api_key="test-key",
    model_name="openai/gpt-4o-mini",
)

TOOL_DEF = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def _make_plain_response(content: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": content, "tool_calls": None}}]
    }
    return resp


def _make_tool_call_response(query: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": query}),
                            },
                        }
                    ],
                }
            }
        ]
    }
    return resp


def test_generate_with_tools_returns_plain_text():
    messages = [{"role": "user", "content": "Hello"}]
    with mock.patch("httpx.post", return_value=_make_plain_response("Hi there!")):
        result = CLIENT.generate_with_tools(messages, TOOL_DEF)
    assert result["content"] == "Hi there!"
    assert not result.get("tool_calls")


def test_generate_with_tools_returns_tool_call():
    messages = [{"role": "user", "content": "What happened today?"}]
    with mock.patch("httpx.post", return_value=_make_tool_call_response("today's news")):
        result = CLIENT.generate_with_tools(messages, TOOL_DEF)
    assert result.get("tool_calls") is not None
    assert result["tool_calls"][0]["function"]["name"] == "web_search"
    args = json.loads(result["tool_calls"][0]["function"]["arguments"])
    assert args["query"] == "today's news"


def test_generate_with_tools_raises_llm_error_on_empty_choices():
    messages = [{"role": "user", "content": "Hello"}]
    bad_resp = mock.MagicMock()
    bad_resp.raise_for_status.return_value = None
    bad_resp.json.return_value = {"choices": []}
    with mock.patch("httpx.post", return_value=bad_resp):
        import pytest
        with pytest.raises(LLMError, match="missing choices"):
            CLIENT.generate_with_tools(messages, TOOL_DEF)


def test_generate_with_tools_sends_tools_in_payload():
    messages = [{"role": "user", "content": "Hello"}]
    with mock.patch("httpx.post", return_value=_make_plain_response("ok")) as mock_post:
        CLIENT.generate_with_tools(messages, TOOL_DEF)
    payload = mock_post.call_args[1]["json"]
    assert "tools" in payload
    assert payload["tools"] == TOOL_DEF
    assert payload["messages"] == messages
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && python -m pytest tests/unit/test_llm_tool_calling.py -v 2>&1 | head -20
```

Expected: `AttributeError: 'OpenAICompatibleClient' object has no attribute 'generate_with_tools'`

- [ ] **Step 3: Add `generate_with_tools()` to `OpenAICompatibleClient`**

In `backend/libs/llm/__init__.py`, add the following method inside `OpenAICompatibleClient`, after the existing `generate()` method (after line 153):

```python
    def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 512,
        temperature: float = 0.4,
    ) -> dict:
        """Call the LLM with tool definitions. Returns the raw message dict from choices[0].

        The returned dict may contain:
        - "content": str | None — text response (None when tool_calls is set)
        - "tool_calls": list | None — tool call requests from the model
        """
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
        }
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                resp = exc.response
                body = resp.text if resp is not None else ""
                if body and len(body) > 600:
                    body = body[:600] + "...(truncated)"
                status = resp.status_code if resp is not None else "unknown"
                raise LLMError(
                    f"Hosted LLM request failed: HTTP {status}. Response: {body or 'no body'}"
                ) from exc
            raise LLMError(f"Hosted LLM request failed: {exc}") from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("Hosted LLM response missing choices")
        return choices[0].get("message", {})
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_llm_tool_calling.py -v
```

Expected:
```
test_llm_tool_calling.py::test_generate_with_tools_returns_plain_text PASSED
test_llm_tool_calling.py::test_generate_with_tools_returns_tool_call PASSED
test_llm_tool_calling.py::test_generate_with_tools_raises_llm_error_on_empty_choices PASSED
test_llm_tool_calling.py::test_generate_with_tools_sends_tools_in_payload PASSED
```

- [ ] **Step 5: Commit**

```bash
git add backend/libs/llm/__init__.py backend/tests/unit/test_llm_tool_calling.py
git commit -m "feat: add generate_with_tools() to OpenAICompatibleClient"
```

---

## Task 3: Update `_generate_quick_answer()` with tool-calling loop

**Files:**
- Modify: `backend/services/api/routes/chat.py`
- Create: `backend/tests/unit/test_chat_web_search.py`

- [ ] **Step 1: Write the failing tests**

Note: `conftest.py` puts `backend/services/api` on sys.path, so route modules import as e.g. `routes.chat` (not `services.api.routes.chat`).

Create `backend/tests/unit/test_chat_web_search.py`:

```python
from __future__ import annotations

import json
import os
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(tool_call_response: dict | None = None, plain_text: str = "Final answer"):
    """Return a mock LLM client.

    If tool_call_response is provided the first generate_with_tools() call returns
    a tool call; the second returns a plain text answer.
    If tool_call_response is None, the first call returns a plain text answer.
    """
    client = mock.MagicMock()
    client.generate_with_tools = mock.MagicMock()

    plain_msg = {"role": "assistant", "content": plain_text, "tool_calls": None}

    if tool_call_response is not None:
        client.generate_with_tools.side_effect = [tool_call_response, plain_msg]
    else:
        client.generate_with_tools.return_value = plain_msg

    return client


def _tool_call_msg(query: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": query}),
                },
            }
        ],
    }


def _call_generate_quick_answer(
    client,
    message: str = "What is the weather today?",
    tavily_key: str = "test-tavily-key",
):
    """Call _generate_quick_answer with mocked dependencies.

    conftest.py puts backend/services/api on sys.path, so import as routes.chat.
    """
    import routes.chat as chat_mod

    fake_session = mock.MagicMock()

    with (
        mock.patch.dict(os.environ, {"TAVILY_API_KEY": tavily_key}),
        mock.patch("routes.chat.get_llm_client", return_value=client),
        mock.patch("routes.chat._recent_chat_history", return_value=[]),
        mock.patch("routes.chat._log_step"),
        mock.patch("routes.chat._log_llm_exchange"),
    ):
        from uuid import uuid4
        result = chat_mod._generate_quick_answer(
            session=fake_session,
            tenant_id=uuid4(),
            conversation_id=uuid4(),
            message=message,
            llm_provider="hosted",
            llm_model=None,
        )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plain_text_response_no_search():
    """When LLM returns plain text, Tavily is never called."""
    client = _make_client(plain_text="The sky is blue.")

    with mock.patch("routes.chat.search") as mock_search:
        result = _call_generate_quick_answer(client)

    assert result == "The sky is blue."
    mock_search.assert_not_called()


def test_tool_call_triggers_search_and_returns_final_answer():
    """When LLM returns a tool call, search is executed and final answer returned."""
    client = _make_client(
        tool_call_response=_tool_call_msg("today weather"),
        plain_text="It is sunny today.",
    )

    fake_results = [
        mock.MagicMock(title="Weather", url="https://weather.com", snippet="Sunny, 22°C"),
    ]

    with mock.patch("services.api.routes.chat.search", return_value=fake_results) as mock_search:
        result = _call_generate_quick_answer(client, message="What is the weather today?")

    assert result == "It is sunny today."
    mock_search.assert_called_once_with("today weather")
    # Second LLM call should have tool result in messages
    second_call_messages = client.generate_with_tools.call_args_list[1][0][0]
    tool_result_msg = next(m for m in second_call_messages if m.get("role") == "tool")
    tool_content = json.loads(tool_result_msg["content"])
    assert tool_content[0]["title"] == "Weather"


def test_no_api_key_skips_tools():
    """When TAVILY_API_KEY is not set, tools are omitted and generate_with_tools not called."""
    client = mock.MagicMock()
    client.generate.return_value = "Plain answer without tools."

    with mock.patch("routes.chat.search") as mock_search:
        result = _call_generate_quick_answer(client, tavily_key="")

    assert result == "Plain answer without tools."
    client.generate.assert_called_once()
    client.generate_with_tools.assert_not_called()
    mock_search.assert_not_called()


def test_tavily_error_falls_back_gracefully():
    """When Tavily raises, the tool result is empty and LLM still produces a final answer."""
    client = _make_client(
        tool_call_response=_tool_call_msg("something"),
        plain_text="I could not find current info, but here is what I know.",
    )

    with mock.patch("services.api.routes.chat.search", side_effect=Exception("timeout")):
        result = _call_generate_quick_answer(client)

    # Second LLM call still happened with empty tool result
    assert "could not find" in result
    second_call_messages = client.generate_with_tools.call_args_list[1][0][0]
    tool_result_msg = next(m for m in second_call_messages if m.get("role") == "tool")
    assert tool_result_msg["content"] == "[]"


def test_llm_error_returns_fallback_string():
    """When LLM raises LLMError, the function returns the standard fallback string."""
    from llm import LLMError
    client = mock.MagicMock()
    client.generate_with_tools.side_effect = LLMError("API down")

    result = _call_generate_quick_answer(client)

    assert "trouble" in result
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && python -m pytest tests/unit/test_chat_web_search.py -v 2>&1 | head -30
```

Expected: Import errors or `AttributeError` since the function doesn't have the tool-calling logic yet.

- [ ] **Step 3: Add `import os` to `chat.py` imports**

In `backend/services/api/routes/chat.py`, the `from __future__ import annotations` block starts at line 1. Add `import os` after the existing stdlib imports (after `import re` on line 5):

```python
import os
```

- [ ] **Step 4: Add `search` import to `chat.py`**

After line 41 (`from sqlalchemy import func, select`), add:

```python
from search.tavily import search
```

- [ ] **Step 5: Add `WEB_SEARCH_TOOL` constant and `_resolve_chat_model()` helper**

After the `router = APIRouter(...)` line (line 43), add:

```python
WEB_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use when the question requires "
            "up-to-date facts, recent events, or information beyond your training data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
            },
            "required": ["query"],
        },
    },
}


def _resolve_chat_model(llm_model: str | None) -> str | None:
    """Return CHAT_SEARCH_MODEL if set, else fall back to llm_model."""
    override = os.getenv("CHAT_SEARCH_MODEL", "").strip()
    return override or llm_model or None
```

- [ ] **Step 6: Replace `_generate_quick_answer()` with the tool-calling version**

Replace the entire `_generate_quick_answer()` function (lines 435–488 in the original file) with:

```python
def _generate_quick_answer(
    *,
    session,
    tenant_id: UUID,
    conversation_id: UUID,
    message: str,
    llm_provider: str | None,
    llm_model: str | None,
) -> str:
    _log_step("start", conversation_id=conversation_id, step="quick_answer")
    response_text: str | None = None

    resolved_model = _resolve_chat_model(llm_model)
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    use_tools = bool(tavily_key)

    try:
        client = get_llm_client(llm_provider, resolved_model)
    except LLMError:
        response_text = "I am not configured to generate a response right now."
        _log_step(
            "finish",
            conversation_id=conversation_id,
            step="quick_answer",
            extra={"chars": len(response_text), "reason": "llm_unavailable"},
        )
        return response_text
    if client is None:
        response_text = "I am not configured to generate a response right now."
        _log_step(
            "finish",
            conversation_id=conversation_id,
            step="quick_answer",
            extra={"chars": len(response_text), "reason": "llm_missing"},
        )
        return response_text

    history = _recent_chat_history(
        session=session, tenant_id=tenant_id, conversation_id=conversation_id, limit=6
    )
    prompt = _build_prompt(history, message)
    system = "You are a helpful assistant. Provide a concise response without citations."

    try:
        if not use_tools or not hasattr(client, "generate_with_tools"):
            # Plain path — no Tavily key or client doesn't support tools
            _log_llm_exchange("request", conversation_id, prompt)
            response = client.generate(prompt, system=system, max_tokens=512, temperature=0.4)
            _log_llm_exchange("response", conversation_id, response)
            response_text = response
            return response

        # Tool-calling path
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        _log_llm_exchange("request", conversation_id, prompt)
        first_message = client.generate_with_tools(
            messages, [WEB_SEARCH_TOOL], max_tokens=512, temperature=0.4
        )
        tool_calls = first_message.get("tool_calls") or []

        if tool_calls:
            tool_call = tool_calls[0]
            fn_args = tool_call.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(fn_args)
                query = args.get("query", "")
                results = search(query)
                tool_result = json.dumps(
                    [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results]
                )
            except Exception:
                tool_result = "[]"

            tool_call_id = tool_call.get("id", "call_0")
            messages.append(
                {
                    "role": "assistant",
                    "content": first_message.get("content"),
                    "tool_calls": tool_calls,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result,
                }
            )
            final_message = client.generate_with_tools(
                messages, [WEB_SEARCH_TOOL], max_tokens=512, temperature=0.4
            )
            response_text = (final_message.get("content") or "").strip()
        else:
            response_text = (first_message.get("content") or "").strip()

        _log_llm_exchange("response", conversation_id, response_text or "")
        return response_text or "I am having trouble generating a response right now."

    except LLMError:
        response_text = "I am having trouble generating a response right now."
        return response_text
    finally:
        if response_text is not None:
            _log_step(
                "finish",
                conversation_id=conversation_id,
                step="quick_answer",
                extra={"chars": len(response_text)},
            )
```

- [ ] **Step 7: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_chat_web_search.py -v
```

Expected:
```
test_chat_web_search.py::test_plain_text_response_no_search PASSED
test_chat_web_search.py::test_tool_call_triggers_search_and_returns_final_answer PASSED
test_chat_web_search.py::test_no_api_key_skips_tools PASSED
test_chat_web_search.py::test_tavily_error_falls_back_gracefully PASSED
test_chat_web_search.py::test_llm_error_returns_fallback_string PASSED
```

- [ ] **Step 8: Run the full unit test suite to check for regressions**

```bash
cd backend && python -m pytest tests/unit/ -v 2>&1 | tail -20
```

Expected: All previously passing tests still pass.

- [ ] **Step 9: Commit**

```bash
git add backend/services/api/routes/chat.py backend/tests/unit/test_chat_web_search.py
git commit -m "feat: add web search tool calling to chat quick-answer path"
```

---

## Task 4: Add env vars to `.env`

**Files:**
- Modify: `.env`

- [ ] **Step 1: Add the new variables to `.env`**

At the end of the `# LLM Provider` section (after `ANTHROPIC_API_KEY=`), add a new section:

```env
# =============================================================================
# Web Search (Tavily)
# =============================================================================
# Required to enable web search in the chat quick-answer path.
# Get a key at https://tavily.com — free tier: 1000 searches/month.
# Leave blank to disable web search (chat still works without it).
TAVILY_API_KEY=

# Optional: override the model used for chat quick answers.
# Leave blank to use HOSTED_LLM_MODEL.
# Must support tool/function calling on your provider.
# Browse tool-calling models: https://openrouter.ai/collections/tool-calling-models
CHAT_SEARCH_MODEL=
```

- [ ] **Step 2: Commit**

```bash
git add .env
git commit -m "config: add TAVILY_API_KEY and CHAT_SEARCH_MODEL env vars"
```

---

## Task 5: Smoke test end-to-end

- [ ] **Step 1: Set a real Tavily key in `.env`**

Get a free key from https://tavily.com and set `TAVILY_API_KEY=tvly-...` in `.env`.

- [ ] **Step 2: Start the backend**

```bash
cd backend && uvicorn services.api.main:app --reload --port 8000
```

- [ ] **Step 3: Send a chat message that requires current information**

```bash
curl -s -X POST http://localhost:8000/chat/send \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "<a real conversation id>",
    "message": "What is the latest news about AI today?",
    "client_message_id": "smoke-test-1"
  }' | python -m json.tool
```

Verify:
- Response is a valid JSON with an `assistant` message
- The answer references recent information (not just training data)
- No 500 errors in the backend logs

- [ ] **Step 4: Verify fallback with blank key**

Set `TAVILY_API_KEY=` (empty), restart, send another message. Verify chat still works normally.
