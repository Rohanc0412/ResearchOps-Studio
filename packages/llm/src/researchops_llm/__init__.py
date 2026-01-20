from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    model_name: str

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> str: ...


class LLMError(RuntimeError):
    """Raised when an LLM request fails."""


@dataclass
class OllamaClient:
    base_url: str
    model_name: str
    timeout_seconds: float = 60.0

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/api/generate"
        logger.info(
            "llm_request",
            extra={"provider": "ollama", "model": self.model_name, "url": url},
        )
        payload: dict = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
        except Exception as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        content = data.get("response")
        if not isinstance(content, str):
            raise LLMError("Ollama response missing content")
        logger.info(
            "llm_response",
            extra={"provider": "ollama", "model": self.model_name, "chars": len(content)},
        )
        return content.strip()


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
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        logger.info(
            "llm_request",
            extra={"provider": "hosted", "model": self.model_name, "url": url},
        )
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
        logger.info(
            "llm_response",
            extra={"provider": "hosted", "model": self.model_name, "chars": len(content)},
        )
        return content.strip()


def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
) -> LLMProvider | None:
    """
    Resolve an LLM client based on provider/model overrides and environment defaults.

    Providers:
      - local: Ollama (default)
      - hosted: OpenAI-compatible API
    """
    provider_name = (provider or os.getenv("LLM_PROVIDER", "local")).strip().lower()
    if provider_name in {"", "none", "disabled"}:
        logger.info("llm_disabled")
        return None

    if provider_name == "local":
        model_name = model or os.getenv("LLM_LOCAL_MODEL", "llama3.1:8b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        logger.info(
            "llm_client_selected",
            extra={"provider": "local", "model": model_name, "base_url": base_url},
        )
        return OllamaClient(base_url=base_url, model_name=model_name)

    if provider_name == "hosted":
        base_url = os.getenv("HOSTED_LLM_BASE_URL")
        api_key = os.getenv("HOSTED_LLM_API_KEY")
        model_name = model or os.getenv("HOSTED_LLM_MODEL")
        if not base_url or not api_key or not model_name:
            raise LLMError(
                "Hosted LLM not configured. Set HOSTED_LLM_BASE_URL, HOSTED_LLM_API_KEY, HOSTED_LLM_MODEL."
            )
        logger.info(
            "llm_client_selected",
            extra={"provider": "hosted", "model": model_name, "base_url": base_url},
        )
        return OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )

    raise LLMError(f"Unknown LLM provider: {provider_name}")
