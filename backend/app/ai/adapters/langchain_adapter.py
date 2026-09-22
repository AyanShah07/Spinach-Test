"""
LangChain-backed LLM adapter (resume-aligned).

Uses LangChain's ChatOpenAI-compatible client pointed at OpenRouter
(or any OpenAI-compatible base URL). Keeps the same LLMProvider contract
so business logic never depends on LangChain types.

Why this exists:
  Resume highlights LangChain / agentic orchestration. This adapter shows
  production use of LangChain as an integration layer — not a rewrite of
  the reliability model (validation + circuit breaker + fallback stay outside).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.provider import AIResponse, LLMProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LangChainAdapter(LLMProvider):
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.OPENROUTER_API_KEY or settings.GROQ_API_KEY
        self.model = settings.OPENROUTER_MODEL or "openai/gpt-4o-mini"
        self.base_url = settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
        self.timeout = settings.LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError("API key required for LangChainAdapter (OPENROUTER_API_KEY or GROQ_API_KEY)")

        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage
        except ImportError as exc:
            raise RuntimeError(
                "langchain-openai not installed. pip install langchain-openai langchain-core"
            ) from exc

        system = (
            "You are a MarTech analyst. Respond ONLY with a JSON object matching "
            '{"facts": [string], "recommendations": [string], "confidence": float 0-1}. '
            "facts must be derived only from the provided context numbers. Never invent statistics."
        )
        user_content = f"Context:\n{json.dumps(context, default=str)}\n\nTask:\n{prompt}"

        llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0.2,
            timeout=self.timeout,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        # async invoke
        msg = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user_content)]
        )
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        parsed = json.loads(content)
        return AIResponse(
            facts=parsed.get("facts", []),
            recommendations=parsed.get("recommendations", []),
            confidence=float(parsed.get("confidence", 0.5)),
            source="llm",
        )
