"""Google Gemini adapter supporting gemini-2.5-flash / gemini-1.5-flash."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.ai.provider import AIResponse, LLMProvider
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class GeminiAdapter(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = settings.LLM_TIMEOUT_SEC

    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")

        system = (
            "You are a MarTech analyst. Respond ONLY with a JSON object matching "
            "this schema: {\"facts\": [string], \"recommendations\": [string], "
            "\"confidence\": float between 0 and 1}. "
            "facts must be derived only from the provided context numbers. "
            "Never invent statistics. recommendations are actionable marketing suggestions based on those facts."
        )
        user_content = f"Context:\n{json.dumps(context, default=str)}\n\nTask:\n{prompt}"

        # Standard Google Gemini REST API with structured JSON output
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        body = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse Gemini response: %s", exc)
            parsed = {}

        return AIResponse(
            facts=parsed.get("facts", []),
            recommendations=parsed.get("recommendations", []),
            confidence=float(parsed.get("confidence", 0.85)),
            source="llm",
        )
