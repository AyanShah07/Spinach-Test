"""Ollama local adapter — zero-cost offline fallback for reproducible runs."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.ai.provider import AIResponse, LLMProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OllamaAdapter(LLMProvider):
    def __init__(self, base_url: str | None = None, model: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = settings.LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        system = (
            "You are a MarTech analyst. Respond ONLY with a JSON object matching "
            "this schema: {\"facts\": [string], \"recommendations\": [string], "
            "\"confidence\": float between 0 and 1}. "
            "facts must be derived only from the provided context numbers. "
            "Never invent statistics."
        )
        user_content = f"Context:\n{json.dumps(context, default=str)}\n\nTask:\n{prompt}"

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        return AIResponse(
            facts=parsed.get("facts", []),
            recommendations=parsed.get("recommendations", []),
            confidence=float(parsed.get("confidence", 0.5)),
            source="llm",
        )
