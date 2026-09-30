"""
All LLM provider adapters in one module.

Every provider implements the same ``LLMProvider`` contract and shares ONE
canonical system instruction (``SYSTEM_INSTRUCTION``) and ONE user-message
formatter, so choosing a provider can never change what the model is asked
or how its output is shaped — only the transport does. Provider matrix:

=========================  =============================================
``OpenAICompatibleProvider``  chat/completions transport shared by
                              OpenRouter and Groq (one class, configured
                              per provider)
``GeminiAdapter``          Google Generative Language REST API
``OllamaAdapter``          local Ollama (offline, zero-cost fallback)
``LangChainAdapter``       LangChain ``ChatOpenAI`` integration layer
                           (lazy import; resume-aligned)
=========================  =============================================

``build_provider(name, api_key=None)`` is the single factory used by both
the app default (``app.main.create_llm``) and per-request overrides via the
``x-ai-provider`` / ``x-ai-key`` headers (``app.api.ai.get_effective_llm``).
It returns ``None`` for unknown or unconfigured providers, which the caller
translates into the rule-based fallback path.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.ai.provider import AIResponse, LLMProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ── The one canonical instruction ─────────────────────────────────────────
SYSTEM_INSTRUCTION = (
    "You are a MarTech campaign analyst.\n"
    "Respond with exactly ONE JSON object and nothing else — no prose, no "
    "markdown, no code fences — matching this schema:\n"
    '{"facts": [string], "recommendations": [string], "confidence": <float between 0 and 1>}\n'
    "\n"
    "Grounding rules (strict, non-negotiable):\n"
    "1. Every fact must restate a value literally present in the provided "
    "context. Never compute new statistics, never estimate, never extrapolate.\n"
    "2. Never state a percentage, count, currency amount, multiplier, or date "
    "that is not literally present in the context. Every number you output is "
    "verified against SQL aggregates, and any unverified number causes the "
    "whole response to be rejected.\n"
    "3. Recommendations must be actionable marketing next steps grounded in "
    "the facts. If you suggest a target, express it as a small relative "
    "change (for example 'increase open rate by 5%'); never state an "
    "absolute figure that is not in the context.\n"
    "4. If the context lacks the data needed for a claim, omit the claim and "
    "say what data is missing instead of guessing.\n"
    "5. Set confidence to how completely the provided context supports the "
    "analysis, not to how good the recommendations sound. Your confidence is "
    "advisory — the platform recalibrates it against measured data support."
)


def format_user_message(prompt: str, context: dict[str, Any]) -> str:
    """Shared user-message shape: bounded, serialized context + the task."""
    return f"Context:\n{json.dumps(context, default=str)}\n\nTask:\n{prompt}"


def _parse_ai_response(content: str) -> AIResponse:
    """Parse model text into an AIResponse; malformed output raises so the
    AnalysisService circuit breaker sees the failure and falls back."""
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Model returned JSON that is not an object")
    return AIResponse(
        facts=parsed.get("facts", []),
        recommendations=parsed.get("recommendations", []),
        confidence=float(parsed.get("confidence", 0.5)),
        source="llm",
    )


# ── Shared transport: OpenAI-compatible /chat/completions ─────────────────
class OpenAICompatibleProvider(LLMProvider):
    """One class for OpenRouter, Groq, and any OpenAI-compatible endpoint."""

    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.extra_headers = extra_headers or {}
        self.timeout = get_settings().LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError(f"{self.provider_name.upper()}_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": format_user_message(prompt, context)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()

        return _parse_ai_response(data["choices"][0]["message"]["content"])


class OpenRouterAdapter(OpenAICompatibleProvider):
    """OpenRouter — OpenAI-compatible API, many models behind one key.

    https://openrouter.ai/docs — primary hosted LLM for the SaaS demo.
    """

    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        settings = get_settings()
        super().__init__(
            api_key=api_key or settings.OPENROUTER_API_KEY,
            model=model or settings.OPENROUTER_MODEL,
            base_url=base_url or settings.OPENROUTER_BASE_URL,
            extra_headers={
                k: v
                for k, v in {
                    "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                    "X-Title": settings.OPENROUTER_SITE_NAME,
                }.items()
                if v
            },
        )


class GroqAdapter(OpenAICompatibleProvider):
    """Groq (Llama 3.x) — used for the live hosted demo."""

    provider_name = "groq"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        super().__init__(
            api_key=api_key or settings.GROQ_API_KEY,
            model=model or settings.GROQ_MODEL,
            base_url="https://api.groq.com/openai/v1",
        )


# ── Google Gemini transport ───────────────────────────────────────────────
class GeminiAdapter(LLMProvider):
    """Google Gemini REST API supporting gemini-2.5-flash / gemini-1.5-flash."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = settings.LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": format_user_message(prompt, context)}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_ai_response(content)


# ── Local Ollama transport ────────────────────────────────────────────────
class OllamaAdapter(LLMProvider):
    """Ollama local adapter — zero-cost offline fallback for reproducible runs."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = settings.LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": format_user_message(prompt, context)},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()

        return _parse_ai_response(data.get("message", {}).get("content", "{}"))


# ── LangChain integration layer ───────────────────────────────────────────
class LangChainAdapter(LLMProvider):
    """LangChain-backed adapter (resume-aligned).

    Uses LangChain's ChatOpenAI-compatible client pointed at OpenRouter (or
    any OpenAI-compatible base URL). Keeps the LLMProvider contract so
    business logic never depends on LangChain types. The reliability model
    (validation + circuit breaker + fallback) stays outside this adapter.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = (
            api_key or settings.OPENROUTER_API_KEY or settings.GROQ_API_KEY
        )
        self.model = model or settings.OPENROUTER_MODEL or "openai/gpt-4o-mini"
        self.base_url = settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
        self.timeout = settings.LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError(
                "API key required for LangChainAdapter "
                "(OPENROUTER_API_KEY or GROQ_API_KEY)"
            )
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage
        except ImportError as exc:
            raise RuntimeError(
                "langchain-openai not installed. "
                "uv pip install langchain-openai langchain-core"
            ) from exc

        llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0.2,
            timeout=self.timeout,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        msg = await llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_INSTRUCTION),
                HumanMessage(content=format_user_message(prompt, context)),
            ]
        )
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        return _parse_ai_response(content)


# ── Single factory ────────────────────────────────────────────────────────
def build_provider(name: str | None, api_key: str | None = None) -> LLMProvider | None:
    """Map a provider name to its adapter, or ``None`` when unconfigured.

    ``api_key`` overrides the configured key (used by the per-request
    ``x-ai-key`` header path). Providers that require a key return ``None``
    when none is available so callers fall back to the rule-based summary
    instead of failing per request.
    """
    name = (name or "").strip().lower()
    settings = get_settings()

    if name == "openrouter":
        key = api_key or settings.OPENROUTER_API_KEY
        return OpenRouterAdapter(api_key=key) if key else None
    if name == "groq":
        key = api_key or settings.GROQ_API_KEY
        return GroqAdapter(api_key=key) if key else None
    if name == "gemini":
        key = api_key or settings.GEMINI_API_KEY
        return GeminiAdapter(api_key=key) if key else None
    if name == "ollama":
        return OllamaAdapter()  # local server, no key required
    if name == "langchain":
        if api_key or settings.OPENROUTER_API_KEY or settings.GROQ_API_KEY:
            return LangChainAdapter(api_key=api_key)
        return None
    return None
