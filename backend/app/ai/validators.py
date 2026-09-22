"""Validate LLM output against the AIResponse schema; raise on failure."""
from pydantic import ValidationError

from app.ai.provider import AIResponse


def validate_ai_response(raw: dict) -> AIResponse:
    try:
        return AIResponse.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"AI response failed schema validation: {exc}") from exc
