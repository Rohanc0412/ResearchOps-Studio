from __future__ import annotations

import json
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


@dataclass
class OpenAICompatibleClient:
    base_url: str
    api_key: str
    model_name: str
    timeout_seconds: float = 60.0

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        response_format: str | dict | None = None,
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
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
        base_url = os.getenv("HOSTED_LLM_BASE_URL")
        api_key = os.getenv("HOSTED_LLM_API_KEY")
        model_name = model or os.getenv("HOSTED_LLM_MODEL")
        if not base_url or not api_key or not model_name:
            raise LLMError(
                "Hosted LLM not configured. Set HOSTED_LLM_BASE_URL, HOSTED_LLM_API_KEY, HOSTED_LLM_MODEL."
            )
        return OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds or _resolve_timeout_seconds(),
        )

    raise LLMError(f"Unknown LLM provider: {provider_name}")


def get_llm_client_for_stage(
    stage: str,
    provider: str | None = None,
    model: str | None = None,
) -> LLMProvider | None:
    stage_key = stage.strip().upper().replace("-", "_")
    provider_override = os.getenv(f"LLM_PROVIDER_{stage_key}") or os.getenv(
        f"LLM_{stage_key}_PROVIDER"
    )
    model_override = os.getenv(f"LLM_MODEL_{stage_key}") or os.getenv(f"LLM_{stage_key}_MODEL")
    resolved_provider = provider or provider_override
    resolved_model = model or model_override
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


def json_response_format(name: str | None = None, schema: dict[str, Any] | None = None) -> str | dict:
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


def _extract_json_payload(text: str) -> dict | list | None:
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
    client: OpenAICompatibleClient,
    system: str | None,
    max_tokens: int,
    temperature: float,
) -> str | None:
    if _extract_json_payload(content) is not None:
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
    if _extract_json_payload(repair) is None:
        return None
    return repair.strip()
