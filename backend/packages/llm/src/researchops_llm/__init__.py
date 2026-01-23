from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

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
        response_format: str | None = None,
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
        response_format: str | None = None,
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
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
        except Exception as exc:
            raise LLMError(f"Hosted LLM request failed: {exc}") from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("Hosted LLM response missing choices")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Hosted LLM response missing content")
        return content.strip()


def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
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
        )

    raise LLMError(f"Unknown LLM provider: {provider_name}")
