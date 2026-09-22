"""
OpenRouter adapter — OpenAI-compatible API, many models behind one key.

https://openrouter.ai/docs
Primary hosted LLM for the SaaS assessment demo (replaces Groq as default).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.ai.provider import AIResponse, LLMProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OpenRouterAdapter(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.model = model or settings.OPENROUTER_MODEL
        self.base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")
        self.timeout = settings.LLM_TIMEOUT_SEC
        self.site_url = settings.OPENROUTER_SITE_URL
        self.site_name = settings.OPENROUTER_SITE_NAME

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not configured")

        system = (
            "You are a MarTech analyst. Respond ONLY with a JSON object matching "
            'this schema: {"facts": [string], "recommendations": [string], '
            '"confidence": float between 0 and 1}. '
            "facts must be derived only from the provided context numbers. "
            "Never invent statistics. recommendations are suggestions based on those facts."
        )
        user_content = f"Context:\n{json.dumps(context, default=str)}\n\nTask:\n{prompt}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return AIResponse(
            facts=parsed.get("facts", []),
            recommendations=parsed.get("recommendations", []),
            confidence=float(parsed.get("confidence", 0.5)),
            source="llm",
        )
