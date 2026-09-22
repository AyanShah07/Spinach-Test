"""Groq (Llama 3.x) adapter — used for the live hosted demo."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.ai.provider import AIResponse, LLMProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class GroqAdapter(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self.timeout = settings.LLM_TIMEOUT_SEC
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY not configured")

        system = (
            "You are a MarTech analyst. Respond ONLY with a JSON object matching "
            "this schema: {\"facts\": [string], \"recommendations\": [string], "
            "\"confidence\": float between 0 and 1}. "
            "facts must be derived only from the provided context numbers. "
            "Never invent statistics. recommendations are suggestions based on those facts."
        )
        user_content = f"Context:\n{json.dumps(context, default=str)}\n\nTask:\n{prompt}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
            resp = await client.post(self.base_url, headers=headers, json=body)
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
