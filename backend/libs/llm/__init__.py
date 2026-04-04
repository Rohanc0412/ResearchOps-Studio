from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class LLMProvider(Protocol):
    model_name: str

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        response_format: str | dict | None = None,
    ) -> str: ...


class LLMError(RuntimeError):
    """Raised when an LLM request fails."""


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_HOSTED_MODEL = "gpt-5-nano"
DEFAULT_BEDROCK_MODEL = "amazon.nova-lite-v1:0"


# Stage names must match the strings passed to get_llm_client_for_stage() in each node.
BALANCED_PROFILE: dict[str, str] = {
    "retrieve": "cheap",
    "outline": "capable",
    "draft": "capable",
    "evaluate": "cheap",
    "repair": "capable",
}


def resolve_model_for_stage(
    stage: str,
    stage_models: dict[str, str | None] | None,
    provider: str | None,
    model: str | None,
) -> str | None:
    """
    Resolve the model name for a pipeline stage using the 4-level priority chain:
    1. Explicit stage_models[stage] override (non-null)
    2. Balanced profile tier env var (LLM_MODEL_CAPABLE or LLM_MODEL_CHEAP)
    3. run-level llm_model argument
    4. HOSTED_LLM_MODEL env var global default
    """
    # Level 1: explicit user override
    if stage_models is not None:
        override = stage_models.get(stage)
        if override is not None:
            return override

    # Level 2: balanced profile tier
    tier_model = _resolve_balanced_profile_model(stage, provider)
    if tier_model:
        return tier_model.strip() or None

    # Level 3: run-level model
    if model:
        return model

    # Level 4: global default
    return _resolve_default_model_name(provider, model)


def _resolve_hosted_base_url() -> str | None:
    return (
        os.getenv("HOSTED_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or DEFAULT_OPENAI_BASE_URL
    )


def _resolve_hosted_api_key() -> str | None:
    return os.getenv("HOSTED_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")


def _resolve_hosted_model_name(model: str | None = None) -> str | None:
    return model or os.getenv("HOSTED_LLM_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_HOSTED_MODEL


def _resolve_bedrock_region_name() -> str | None:
    return (
        os.getenv("BEDROCK_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
    )


def _resolve_bedrock_model_name(model: str | None = None) -> str | None:
    return model or os.getenv("BEDROCK_MODEL") or DEFAULT_BEDROCK_MODEL


def _resolve_default_model_name(
    provider: str | None,
    model: str | None = None,
) -> str | None:
    provider_name = (provider or os.getenv("LLM_PROVIDER", "hosted")).strip().lower()
    if provider_name == "bedrock":
        return _resolve_bedrock_model_name(model)
    return _resolve_hosted_model_name(model)


def _resolve_balanced_profile_model(stage: str, provider: str | None) -> str | None:
    provider_name = (provider or os.getenv("LLM_PROVIDER", "hosted")).strip().lower()
    if provider_name == "bedrock":
        return None
    tier = BALANCED_PROFILE.get(stage)
    if tier == "capable":
        return os.getenv("LLM_MODEL_CAPABLE") or os.getenv("LLM_MODEL_CHEAP")
    if tier == "cheap":
        return os.getenv("LLM_MODEL_CHEAP")
    return None


def _response_format_system_instruction(response_format: str | dict | None) -> str | None:
    if response_format is None:
        return None
    if isinstance(response_format, str):
        if response_format in {"json", "json_object"}:
            return "Return only valid JSON. Do not include markdown or commentary."
        if response_format == "json_schema":
            return "Return only valid JSON matching the expected schema."
        return None
    if isinstance(response_format, dict):
        format_type = response_format.get("type")
        if format_type == "json_schema":
            schema = response_format.get("json_schema") or {}
            return (
                "Return only valid JSON matching the expected schema. "
                f"Schema hint: {json.dumps(schema, ensure_ascii=True)}"
            )
        if format_type == "json_object":
            return "Return only valid JSON. Do not include markdown or commentary."
    return None


def _compose_system_prompt(
    system: str | None,
    response_format: str | dict | None,
) -> str | None:
    format_instruction = _response_format_system_instruction(response_format)
    if system and format_instruction:
        return f"{system}\n\n{format_instruction}"
    return system or format_instruction


def explain_llm_error(reason: str) -> str:
    text = (reason or "").strip()
    lowered = text.lower()
    if any(token in lowered for token in ("http 429", "resource_exhausted", "quota", "rate limit")):
        return (
            "The configured LLM provider rejected the request due to quota or rate limits. "
            "Check billing or retry later."
        )
    if "bedrock" in lowered and "not configured" in lowered:
        return (
            "The Bedrock LLM is not configured. Set BEDROCK_REGION or AWS_REGION/AWS_DEFAULT_REGION "
            "and verify BEDROCK_MODEL."
        )
    if "not configured" in lowered:
        return (
            "The hosted LLM is not configured. Set HOSTED_LLM_API_KEY or OPENAI_API_KEY "
            "and verify the base URL/model settings."
        )
    if text:
        return text
    return "The configured LLM provider could not complete the request."


@dataclass
class OpenAICompatibleClient:
    base_url: str
    api_key: str
    model_name: str
    timeout_seconds: float = 60.0
    # Populated after each generate() call � used by Langfuse instrumentation
    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0

    def _chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if re.search(r"/v\d+(?:beta\d*)?/openai$", base):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _request_model_name(self) -> str:
        base = self.base_url.rstrip("/").lower()
        model = self.model_name.strip()
        if "generativelanguage.googleapis.com" in base and model.startswith("google/"):
            return model.split("/", 1)[1]
        return model

    def _uses_max_completion_tokens(self) -> bool:
        """Some newer OpenAI models require max_completion_tokens instead of max_tokens."""
        model = self.model_name.strip().lower()
        return model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3") or model.startswith("o4")

    def _temperature_unsupported(self) -> bool:
        """Models that only accept the default temperature (1) and reject any other value."""
        model = self.model_name.strip().lower()
        return self._uses_max_completion_tokens() or "nano" in model

    def _build_base_payload(self, messages: list[dict], max_tokens: int, temperature: float) -> dict:
        payload: dict = {
            "model": self._request_model_name(),
            "messages": messages,
        }
        if self._uses_max_completion_tokens():
            payload["max_completion_tokens"] = max_tokens
            payload["reasoning_effort"] = "low"
        else:
            payload["max_tokens"] = max_tokens
        if not self._temperature_unsupported():
            payload["temperature"] = temperature
        return payload

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        response_format: str | dict | None = None,
    ) -> str:
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = self._build_base_payload(messages, max_tokens, temperature)
        if response_format:
            if isinstance(response_format, str):
                if response_format == "json":
                    payload["response_format"] = {"type": "json_object"}
                else:
                    payload["response_format"] = {"type": response_format}
            elif isinstance(response_format, dict):
                payload["response_format"] = response_format
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
        usage = data.get("usage") or {}
        self.last_prompt_tokens = int(usage.get("prompt_tokens") or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens") or 0)
        # Emit token counts into active Langfuse span (no-op when not enabled)
        try:
            from langfuse import langfuse_context
            langfuse_context.update_current_observation(
                usage={
                    "input": self.last_prompt_tokens,
                    "output": self.last_completion_tokens,
                },
                model=self.model_name,
            )
        except Exception:
            pass  # Never fail the pipeline due to observability
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("Hosted LLM response missing choices")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Hosted LLM response missing content")
        content = content.strip()
        if _should_attempt_json_repair(response_format):
            repaired = _repair_json_response(
                content,
                response_format=response_format,
                client=self,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if repaired is not None:
                return repaired
        return content

    def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 512,
        temperature: float = 0.4,
        tool_choice: str = "auto",
    ) -> dict:
        """Call the LLM with tool definitions. Returns the raw message dict from choices[0].

        The returned dict may contain:
        - "content": str | None — text response (None when tool_calls is set)
        - "tool_calls": list | None — tool call requests from the model
        """
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_base_payload(messages, max_tokens, temperature)
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
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
        usage = data.get("usage") or {}
        self.last_prompt_tokens = int(usage.get("prompt_tokens") or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens") or 0)
        # Emit token counts into active Langfuse span (no-op when not enabled)
        try:
            from langfuse import langfuse_context
            langfuse_context.update_current_observation(
                usage={
                    "input": self.last_prompt_tokens,
                    "output": self.last_completion_tokens,
                },
                model=self.model_name,
            )
        except Exception:
            pass  # Never fail the pipeline due to observability
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("Hosted LLM response missing choices")
        return choices[0].get("message", {})


@dataclass
class BedrockClient:
    model_name: str
    region_name: str
    timeout_seconds: float = 60.0
    _runtime_client: Any | None = None
    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0

    def _get_runtime_client(self) -> Any:
        if self._runtime_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise LLMError(
                    "Bedrock support requires boto3. Install backend dependencies with boto3>=1.34."
                ) from exc
            config = None
            try:
                from botocore.config import Config

                config = Config(read_timeout=self.timeout_seconds, connect_timeout=self.timeout_seconds)
            except Exception:
                config = None
            kwargs: dict[str, Any] = {"region_name": self.region_name}
            if config is not None:
                kwargs["config"] = config
            self._runtime_client = boto3.client("bedrock-runtime", **kwargs)
        return self._runtime_client

    def _converse(self, **kwargs: Any) -> dict[str, Any]:
        return self._get_runtime_client().converse(**kwargs)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        response_format: str | dict | None = None,
    ) -> str:
        effective_system = _compose_system_prompt(system, response_format)
        payload: dict[str, Any] = {
            "modelId": self.model_name,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if effective_system:
            payload["system"] = [{"text": effective_system}]
        try:
            response = self._converse(**payload)
        except Exception as exc:
            raise LLMError(f"Bedrock LLM request failed: {exc}") from exc

        usage = response.get("usage") or {}
        self.last_prompt_tokens = int(usage.get("inputTokens") or 0)
        self.last_completion_tokens = int(usage.get("outputTokens") or 0)
        try:
            from langfuse import langfuse_context

            langfuse_context.update_current_observation(
                usage={
                    "input": self.last_prompt_tokens,
                    "output": self.last_completion_tokens,
                },
                model=self.model_name,
            )
        except Exception:
            pass

        content_blocks = (
            ((response.get("output") or {}).get("message") or {}).get("content") or []
        )
        for block in content_blocks:
            text = block.get("text")
            if isinstance(text, str):
                content = text.strip()
                if _should_attempt_json_repair(response_format):
                    repaired = _repair_json_response(
                        content,
                        response_format=response_format,
                        client=self,
                        system=effective_system,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    if repaired is not None:
                        return repaired
                return content
        raise LLMError("Bedrock LLM response missing text content")


def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
    *,
    timeout_seconds: float | None = None,
) -> LLMProvider | None:
    """
    Resolve an LLM client based on provider/model overrides and environment defaults.

    Providers:
      - hosted: OpenAI-compatible API
    """
    provider_name = (provider or os.getenv("LLM_PROVIDER", "hosted")).strip().lower()
    if provider_name in {"", "none", "disabled"}:
        return None

    if provider_name == "local":
        raise LLMError("Local LLM provider is no longer supported.")

    if provider_name == "hosted":
        base_url = _resolve_hosted_base_url()
        api_key = _resolve_hosted_api_key()
        model_name = _resolve_hosted_model_name(model)
        if not base_url or not api_key or not model_name:
            raise LLMError(
                "Hosted LLM not configured. Set HOSTED_LLM_API_KEY or OPENAI_API_KEY, "
                "and optionally HOSTED_LLM_BASE_URL/OPENAI_BASE_URL plus HOSTED_LLM_MODEL/OPENAI_MODEL."
            )
        return OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds or _resolve_timeout_seconds(),
        )

    if provider_name == "bedrock":
        region_name = _resolve_bedrock_region_name()
        model_name = _resolve_bedrock_model_name(model)
        if not region_name:
            raise LLMError(
                "Bedrock LLM not configured. Set BEDROCK_REGION or AWS_REGION/AWS_DEFAULT_REGION."
            )
        if not model_name:
            raise LLMError("Bedrock LLM not configured. Set BEDROCK_MODEL.")
        return BedrockClient(
            model_name=model_name,
            region_name=region_name,
            timeout_seconds=timeout_seconds or _resolve_timeout_seconds(),
        )

    raise LLMError(f"Unknown LLM provider: {provider_name}")


def get_llm_client_for_stage(
    stage: str,
    provider: str | None = None,
    model: str | None = None,
    *,
    stage_models: dict[str, str | None] | None = None,
) -> LLMProvider | None:
    stage_key = stage.strip().upper().replace("-", "_")
    # Operator-level env override (highest priority — sits above user stage_models)
    provider_override = os.getenv(f"LLM_PROVIDER_{stage_key}") or os.getenv(
        f"LLM_{stage_key}_PROVIDER"
    )
    model_override = os.getenv(f"LLM_MODEL_{stage_key}") or os.getenv(f"LLM_{stage_key}_MODEL")
    resolved_provider = provider_override or provider
    # If operator has set an explicit stage env var, use it directly (skip routing)
    if model_override:
        resolved_model = model_override
    else:
        resolved_model = resolve_model_for_stage(stage, stage_models, resolved_provider, model)
    timeout_seconds = _resolve_timeout_seconds(stage_key)
    return get_llm_client(
        resolved_provider,
        resolved_model,
        timeout_seconds=timeout_seconds,
    )


def _resolve_timeout_seconds(stage_key: str | None = None) -> float:
    def _read_timeout(name: str) -> float | None:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    if stage_key:
        for key in (
            f"LLM_TIMEOUT_SECONDS_{stage_key}",
            f"LLM_{stage_key}_TIMEOUT_SECONDS",
            f"HOSTED_LLM_TIMEOUT_SECONDS_{stage_key}",
        ):
            value = _read_timeout(key)
            if value is not None and value > 0:
                return value

    for key in ("LLM_TIMEOUT_SECONDS", "HOSTED_LLM_TIMEOUT_SECONDS"):
        value = _read_timeout(key)
        if value is not None and value > 0:
            return value

    return 60.0


def use_json_schema() -> bool:
    raw = os.getenv("LLM_USE_JSON_SCHEMA")
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def json_schema_response_format(name: str, schema: dict[str, Any], *, strict: bool = True) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": strict,
        },
    }


def json_response_format(
    name: str | None = None,
    schema: dict[str, Any] | None = None,
) -> str | dict:
    if schema and use_json_schema():
        return json_schema_response_format(name or "response", schema, strict=True)
    return "json"


def _should_attempt_json_repair(response_format: str | dict | None) -> bool:
    if response_format is None:
        return False
    raw = os.getenv("LLM_JSON_REPAIR")
    if raw is None or not raw.strip():
        enabled = True
    else:
        enabled = raw.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    if isinstance(response_format, str):
        return response_format in {"json", "json_schema", "json_object"}
    if isinstance(response_format, dict):
        return response_format.get("type") in {"json_schema", "json_object"}
    return False


def log_llm_exchange(
    label: str,
    content: str | None,
    *,
    stage: str,
    section_id: str | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Emit a structured log entry for an LLM request or response."""
    if not content:
        return
    _logger = logger or logging.getLogger(__name__)
    message = (
        f"Prepared LLM request for {stage}"
        if label == "request"
        else f"Received LLM response for {stage}"
    )
    log_full = os.getenv("LLM_LOG_FULL", "").strip().lower() in {"1", "true", "yes", "on"}
    extra: dict = {
        "event": "pipeline.llm",
        "stage": stage,
        "chars": len(content),
        "preview": content,
    }
    if section_id is not None:
        extra["section_id"] = section_id
    if log_full:
        _logger.info(message, extra=extra)
        _logger.info("LLM content follows", extra={"event": "pipeline.llm.full", "stage": stage})
        _logger.info(content)
        return
    _logger.info(message, extra=extra)


def extract_json_payload(text: str) -> dict | list | None:
    if not text:
        return None
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
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


def _repair_prompt(
    content: str,
    *,
    response_format: str | dict | None,
    schema_hint: str | None,
) -> str:
    hint = schema_hint or "Return a single JSON object matching the expected schema."
    return (
        "Your previous response was not valid JSON.\n"
        "Return ONLY valid JSON. Do not include markdown or commentary.\n"
        f"{hint}\n\n"
        "Previous response:\n"
        f"{content}\n"
    )


def _repair_json_response(
    content: str,
    *,
    response_format: str | dict | None,
    client: LLMProvider,
    system: str | None,
    max_tokens: int,
    temperature: float,
) -> str | None:
    if extract_json_payload(content) is not None:
        return None
    max_chars = int(os.getenv("LLM_JSON_REPAIR_MAX_CHARS", "8000"))
    clipped = content if max_chars <= 0 else content[:max_chars]
    schema_hint = None
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        schema_hint = json.dumps(response_format.get("json_schema") or {}, ensure_ascii=True)
    prompt = _repair_prompt(clipped, response_format=response_format, schema_hint=schema_hint)
    repair_temperature = float(os.getenv("LLM_JSON_REPAIR_TEMPERATURE", "0"))
    try:
        repair = client.generate(
            prompt,
            system=system or "You fix JSON formatting and return only valid JSON.",
            max_tokens=max_tokens,
            temperature=repair_temperature,
            response_format=response_format,
        )
    except Exception:
        return None
    if extract_json_payload(repair) is None:
        return None
    return repair.strip()
