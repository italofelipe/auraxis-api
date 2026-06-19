"""LLM provider abstraction for the AI advisory engine.

Provider pattern: configure via LLM_PROVIDER env var.
  - "stub"   (default) — rule-based insights, no external calls
  - "openai" — OpenAI chat completions (requires OPENAI_API_KEY)
  - "claude" — Anthropic Messages API (requires ANTHROPIC_API_KEY)

Required env vars (do NOT set here — configure in .env):
  - LLM_PROVIDER: "openai" | "claude" | "stub"
  - OPENAI_API_KEY: required when LLM_PROVIDER=openai
  - ANTHROPIC_API_KEY: required when LLM_PROVIDER=claude
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class LLMProviderError(Exception):
    """Raised when the LLM provider fails."""


@dataclass
class LLMResponse:
    """Structured response from an LLM provider, including usage metadata."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    latency_ms: int

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate cost in USD based on token counts and model pricing.

        Prices per 1M tokens (input_price, output_price).
        Falls back to conservative defaults for unknown models.
        """
        _PRICES: dict[str, tuple[float, float]] = {
            "gpt-4o": (2.50, 10.00),
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-4.1": (2.00, 8.00),
            "gpt-4.1-mini": (0.40, 1.60),
            "claude-haiku-4-5-20251001": (0.25, 1.25),
        }
        input_price, output_price = _PRICES.get(self.model, (0.002, 0.008))
        return (
            self.prompt_tokens * input_price + self.completion_tokens * output_price
        ) / 1_000_000


_DEFAULT_MAX_TOKENS = 512


def _resolve_max_tokens(max_tokens: int | None) -> int:
    """Resolve the output token budget for a single LLM call.

    Callers (e.g. the AI advisory service) pass a period-specific budget so deep
    reports (~15 min reading) get enough room while daily insights stay lean.
    Falls back to ``AI_INSIGHT_MAX_TOKENS_DEFAULT`` (then 512) for back-compat.
    """
    if max_tokens is not None and max_tokens > 0:
        return int(max_tokens)
    try:
        return max(1, int(os.getenv("AI_INSIGHT_MAX_TOKENS_DEFAULT", "512")))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_TOKENS


def _timeout_for_max_tokens(max_tokens: int) -> int:
    """Scale the HTTP timeout with the output budget.

    A 6k-token report can take far longer than the old 20s default; scale up
    (capped at 120s) so long generations are not cut off mid-stream.
    """
    return min(120, max(20, max_tokens // 25))


@runtime_checkable
class LLMProvider(Protocol):
    def generate(self, prompt: str) -> str:
        """Generate a response for *prompt*. Raises LLMProviderError on failure."""
        ...

    def generate_with_usage(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a response and return structured usage data."""
        ...


class StubLLMProvider:
    """Canned response — useful for testing and environments without API keys."""

    _STUB_MODEL = "stub"
    _STUB_CONTENT = (
        "Com base nos seus dados financeiros, identifiquei os seguintes insights: "
        "1. Gastos discricionários >30% das despesas — revise esses valores. "
        "2. Você tem metas ativas que podem estar em risco caso o ritmo de gastos atual continue. "  # noqa: E501
        "3. Há uma oportunidade de economia de até 15% caso reduza gastos variáveis nos próximos 60 dias."  # noqa: E501
    )

    def generate(self, prompt: str) -> str:
        del prompt
        return self._STUB_CONTENT

    def generate_with_usage(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        del prompt, max_tokens
        content = self._STUB_CONTENT
        if (
            response_schema
            and response_schema.get("name") == "financial_insight_response"
        ):
            content = (
                '{"summary":"Resumo financeiro gerado com sucesso.",'
                '"items":[{"type":"saude_financeira","title":"Resumo financeiro",'
                '"message":"Seus dados financeiros foram analisados com sucesso.",'
                '"evidence":["current_period.paid.balance"]}]}'
            )
        elif response_schema is not None:
            content = (
                '{"items":[{"type":"saude_financeira","title":"Resumo financeiro",'
                '"message":"Seus dados financeiros foram analisados com sucesso."}]}'
            )
        return LLMResponse(
            content=content,
            prompt_tokens=150,
            completion_tokens=80,
            total_tokens=230,
            model=self._STUB_MODEL,
            latency_ms=0,
        )


class OpenAILLMProvider:
    """Calls the OpenAI Chat Completions API (requires `requests` + OPENAI_API_KEY)."""

    _BASE_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        # Strong model by default (#1386): richer, more assertive insights.
        # Cost is bounded by the per-user monthly budget + 1/day cap.
        self._model = os.getenv("OPENAI_ADVISORY_MODEL", "gpt-4o")

    def generate(self, prompt: str) -> str:
        return self.generate_with_usage(prompt).content

    def generate_with_usage(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise LLMProviderError("OPENAI_API_KEY is not configured.")
        import requests  # lazy import to keep startup fast

        resolved_max_tokens = _resolve_max_tokens(max_tokens)
        start = time.monotonic()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": resolved_max_tokens,
            "temperature": 0.4,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": response_schema,
            }

        try:
            resp = requests.post(
                self._BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=_timeout_for_max_tokens(resolved_max_tokens),
            )
            resp.raise_for_status()
            latency_ms = int((time.monotonic() - start) * 1000)
            data = resp.json()
            usage = data.get("usage", {})
            content = str(data["choices"][0]["message"]["content"])
            return LLMResponse(
                content=content,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
                model=str(data.get("model", self._model)),
                latency_ms=latency_ms,
            )
        except Exception as exc:
            raise LLMProviderError(f"OpenAI call failed: {exc}") from exc


class ClaudeLLMProvider:
    """Calls the Anthropic Messages API (requires `requests` + ANTHROPIC_API_KEY)."""

    _BASE_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self) -> None:
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._model = os.getenv("ANTHROPIC_ADVISORY_MODEL", "claude-haiku-4-5-20251001")

    def generate(self, prompt: str) -> str:
        return self.generate_with_usage(prompt).content

    def generate_with_usage(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        _ = response_schema
        if not self._api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is not configured.")
        import requests

        resolved_max_tokens = _resolve_max_tokens(max_tokens)
        start = time.monotonic()
        try:
            resp = requests.post(
                self._BASE_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": resolved_max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=_timeout_for_max_tokens(resolved_max_tokens),
            )
            resp.raise_for_status()
            latency_ms = int((time.monotonic() - start) * 1000)
            data = resp.json()
            usage = data.get("usage", {})
            content = str(data["content"][0]["text"])
            return LLMResponse(
                content=content,
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
                total_tokens=int(usage.get("input_tokens", 0))
                + int(usage.get("output_tokens", 0)),
                model=str(data.get("model", self._model)),
                latency_ms=latency_ms,
            )
        except Exception as exc:
            raise LLMProviderError(f"Claude call failed: {exc}") from exc


def get_llm_provider() -> LLMProvider:
    """Factory: reads LLM_PROVIDER env var and returns the appropriate provider."""
    provider_name = os.getenv("LLM_PROVIDER", "stub").lower()
    if provider_name == "openai":
        return OpenAILLMProvider()
    if provider_name == "claude":
        return ClaudeLLMProvider()
    return StubLLMProvider()


__all__ = [
    "ClaudeLLMProvider",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponse",
    "OpenAILLMProvider",
    "StubLLMProvider",
    "get_llm_provider",
]
