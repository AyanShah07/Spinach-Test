"""LLMProvider abstract interface."""
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class AIResponse(BaseModel):
    """Validated shape returned by every provider / fallback."""
    facts: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    source: str = "llm"  # "llm" | "fallback"
    grounding_verified: bool = True
    grounding_notes: list[str] = Field(default_factory=list)


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: dict[str, Any]) -> AIResponse:
        ...
